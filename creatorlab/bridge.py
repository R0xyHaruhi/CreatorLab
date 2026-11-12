"""Local-only explicit import bridge for CreatorLab's Chrome extension.

No browser credentials or hidden page requests are collected. The extension sends
only the user's reviewed fields after a button click.
"""
import json
import hashlib
import re
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from creatorlab.links import parse_video_link, LinkError
from creatorlab.storage import init_links, connection

PORT = 8765
FIELDS = ('views', 'likes', 'comments', 'shares')
BATCH_FIELDS = FIELDS + ('favorites',)

def secret_file(root):
    return Path(root) / 'local' / 'bridge_token.txt'

def get_token(root):
    p = secret_file(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        try: os.chmod(p, 0o600)
        except OSError: pass
    return p.read_text(encoding='utf-8').strip()

def clean_import(payload):
    if not isinstance(payload, dict): raise ValueError('Invalid JSON payload')
    raw = str(payload.get('url') or '')
    info = parse_video_link(raw)
    if info['platform'] != 'douyin': raise ValueError('当前浏览器导入仅支持抖音视频链接')
    vals = {}
    for field in FIELDS:
        v = payload.get(field)
        if v is None or v == '': vals[field] = None
        elif isinstance(v, bool) or not str(v).isdigit() or int(v)>2_000_000_000:
            raise ValueError(f'{field} 必须是非负整数或留空')
        else: vals[field] = int(v)
    vals['display_name'] = str(payload.get('name') or '')[:150].strip()
    vals['evidence'] = str(payload.get('evidence') or '')[:400].strip()
    return info, vals

def save_import(db, payload):
    info, vals = clean_import(payload)
    init_links(db)
    with connection(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS browser_import_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, linked_video_id INTEGER NOT NULL,
            imported_at TEXT NOT NULL, source_url TEXT NOT NULL,
            evidence TEXT NOT NULL, fields_updated TEXT NOT NULL
        )''')
        row = con.execute('SELECT id FROM linked_videos WHERE url=?', (info['url'],)).fetchone()
        if row:
            item_id = row['id']
        else:
            cur=con.execute('INSERT INTO linked_videos (platform,url,video_id) VALUES (?,?,?)',
                (info['platform'],info['url'],info['video_id']))
            item_id=cur.lastrowid
        changes = {}
        if vals['display_name']: changes['display_name'] = vals['display_name']
        for field in FIELDS:
            if vals[field] is not None: changes[field] = vals[field]
        if any(k in changes for k in FIELDS): changes['metrics_source']='browser_user_reviewed'
        if changes:
            con.execute('UPDATE linked_videos SET '+', '.join(f'{k}=?' for k in changes)+' WHERE id=?',
                (*changes.values(),item_id))
        con.execute('INSERT INTO browser_import_history (linked_video_id,imported_at,source_url,evidence,fields_updated) VALUES (?,?,?,?,?)',
            (item_id,datetime.now(timezone.utc).isoformat(),info['url'],vals['evidence'],','.join(changes.keys())))
    return {'id':item_id,'updated_fields':list(changes.keys()),'platform':info['platform']}


# Batch imports intentionally accept records without video URLs; Creator Center list
# often does not expose one. Such records stay separate until linked manually.
def clean_batch_row(row):
    if not isinstance(row, dict): raise ValueError('作品记录格式错误')
    title = re.sub(r'\s+', ' ', str(row.get('title') or '')).strip()[:250]
    published = str(row.get('published_at') or '').strip()[:50]
    url = str(row.get('url') or '').strip()
    if len(title) < 2: raise ValueError('缺少作品标题，无法建立记录')
    raw_id=str(row.get('video_id') or '').strip()
    if raw_id and (not re.fullmatch(r'[0-9]{8,30}',raw_id)): raise ValueError('视频 ID 格式不合法')
    if len(published)>50: raise ValueError('发布时间过长')
    if url:
        info = parse_video_link(url)
        if info['platform'] != 'douyin': raise ValueError('仅支持抖音')
        url = info['url']
    metrics={}
    for key in BATCH_FIELDS:
        val = row.get(key)
        if val is None or val == '': metrics[key]=None
        elif isinstance(val, bool) or not str(val).isdigit() or int(val)>2_000_000_000:
            raise ValueError(f'{key} 必须为非负整数或留空')
        else: metrics[key]=int(val)
    fingerprint=hashlib.sha256(('douyin\0'+('id:'+raw_id if raw_id else 'title:'+title+'\0'+published)).encode()).hexdigest()
    extras={}
    for key in ('avg_view_second','avg_view_proportion','bounce_rate_2s','completion_rate','completion_rate_5s'):
        val=row.get(key)
        if val is None or val=='': extras[key]=None
        else:
            try: num=float(val)
            except (TypeError,ValueError): raise ValueError(f'{key} 不是有效数字')
            import math
            if not math.isfinite(num) or num<0 or num>100000: raise ValueError(f'{key} 超出合理范围')
            extras[key]=num
    cover_url=row.get('cover_url') or None
    if all(value is None for value in [*metrics.values(),*extras.values()]):
        raise ValueError('未识别到任何作品指标；请先检查页面')
    visibility=row.get('visibility') if row.get('visibility') in ('public','private','unlisted','deleted') else None
    return {'fingerprint':fingerprint,'video_id':raw_id,'title':title,'published_at':published,'url':url,'cover_url':cover_url,'visibility':visibility,**metrics,**extras}

def init_batch(db):
    with connection(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS creator_center_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL DEFAULT 'douyin',
            title TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER,
            source TEXT NOT NULL DEFAULT 'creator_center_visible_dom',
            verified INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
        )''')
        cols={r['name'] for r in con.execute('PRAGMA table_info(creator_center_videos)')}
        for name,typ in [('favorites','INTEGER'),('video_id','TEXT'),('avg_view_second','REAL'),('avg_view_proportion','REAL'),('bounce_rate_2s','REAL'),('completion_rate','REAL'),('completion_rate_5s','REAL'),('cover_url','TEXT'),('visibility','TEXT')]:
            if name not in cols: con.execute(f'ALTER TABLE creator_center_videos ADD COLUMN {name} {typ}')
        con.execute('''CREATE TABLE IF NOT EXISTS creator_center_metric_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER NOT NULL,
            recorded_at TEXT NOT NULL, views INTEGER, likes INTEGER,
            comments INTEGER, shares INTEGER
        )''')
        hcols={r['name'] for r in con.execute('PRAGMA table_info(creator_center_metric_history)')}
        for name in ('favorites','avg_view_second','avg_view_proportion','bounce_rate_2s','completion_rate','completion_rate_5s'):
            if name not in hcols: con.execute(f'ALTER TABLE creator_center_metric_history ADD COLUMN {name} REAL')

def save_batch(db, payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('rows'),list):
        raise ValueError('批量记录格式错误')
    rows=payload['rows']
    if not (1 <= len(rows) <= 500): raise ValueError('单批仅允许 1–500 条作品')
    clean=[clean_batch_row(r) for r in rows]
    if len(set(r['fingerprint'] for r in clean)) != len(clean):
        raise ValueError('本次批次存在重复作品')
    init_batch(db)
    source = 'creator_center_network_user_confirmed' if payload.get('source') == 'network' else 'creator_center_visible_dom'
    now=datetime.now(timezone.utc).isoformat()
    created=updated=0
    with connection(db) as con:
        for r in clean:
            prev=con.execute('SELECT id FROM creator_center_videos WHERE fingerprint=?',(r['fingerprint'],)).fetchone()
            if not prev and r['video_id']:
                prev=con.execute('SELECT id FROM creator_center_videos WHERE video_id=?',(r['video_id'],)).fetchone()
            if not prev and r['video_id'] and r['published_at']:
                prev=con.execute('SELECT id FROM creator_center_videos WHERE title=? AND published_at=? AND (video_id IS NULL OR video_id=?)',(r['title'],r['published_at'],'')).fetchone()
            if prev:
                video_id=prev['id']; updated+=1
                con.execute('UPDATE creator_center_videos SET fingerprint=? WHERE id=?',(r['fingerprint'],video_id))
                con.execute('''UPDATE creator_center_videos SET title=?, published_at=COALESCE(NULLIF(?,''),published_at), video_id=COALESCE(NULLIF(?,''),video_id),
                   url=CASE WHEN ? != '' THEN ? ELSE url END, cover_url=COALESCE(?,cover_url), visibility=COALESCE(?,visibility),
                   views=COALESCE(?,views), likes=COALESCE(?,likes), comments=COALESCE(?,comments), shares=COALESCE(?,shares),
                   avg_view_second=COALESCE(?,avg_view_second),avg_view_proportion=COALESCE(?,avg_view_proportion),
                   bounce_rate_2s=COALESCE(?,bounce_rate_2s),completion_rate=COALESCE(?,completion_rate),
                   completion_rate_5s=COALESCE(?,completion_rate_5s),source=?,last_seen=? WHERE id=?''',
                   (r['title'],r['published_at'],r['video_id'],r['url'],r['url'],r['cover_url'],r['visibility'],r['views'],r['likes'],r['comments'],r['shares'],
                    r['avg_view_second'],r['avg_view_proportion'],r['bounce_rate_2s'],r['completion_rate'],r['completion_rate_5s'],source,now,video_id))
            else:
                cur=con.execute('''INSERT INTO creator_center_videos
                   (fingerprint,video_id,title,published_at,url,cover_url,visibility,views,likes,comments,shares,avg_view_second,avg_view_proportion,bounce_rate_2s,completion_rate,completion_rate_5s,source,first_seen,last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (r['fingerprint'],r['video_id'],r['title'],r['published_at'],r['url'],r['cover_url'],r['visibility'],r['views'],r['likes'],r['comments'],r['shares'],
                    r['avg_view_second'],r['avg_view_proportion'],r['bounce_rate_2s'],r['completion_rate'],r['completion_rate_5s'],source,now,now))
                video_id=cur.lastrowid;created+=1
            con.execute('UPDATE creator_center_videos SET favorites=COALESCE(?,favorites) WHERE id=?',(r['favorites'],video_id))
            history=con.execute('''INSERT INTO creator_center_metric_history
                (video_id,recorded_at,views,likes,comments,shares,avg_view_second,avg_view_proportion,bounce_rate_2s,completion_rate,completion_rate_5s)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (video_id,now,r['views'],r['likes'],r['comments'],r['shares'],r['avg_view_second'],r['avg_view_proportion'],
                 r['bounce_rate_2s'],r['completion_rate'],r['completion_rate_5s']))
            con.execute('UPDATE creator_center_metric_history SET favorites=? WHERE id=?',(r['favorites'],history.lastrowid))
    return {'created':created,'updated':updated,'total':len(clean)}

def list_batch(db):
    init_batch(db)
    with connection(db) as con:
        return [dict(r) for r in con.execute('SELECT * FROM creator_center_videos ORDER BY last_seen DESC,id DESC')]

def handler_factory(db, token):
    bridge_id = hashlib.sha256(token.encode()).hexdigest()[:12]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args): pass
        def send(self, code, data):
            blob=json.dumps(data,ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            origin=self.headers.get('Origin','')
            if origin.startswith('chrome-extension://') and '/' not in origin[len('chrome-extension://'):]:
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Headers','Content-Type,X-CreatorLab-Token')
                self.send_header('Access-Control-Allow-Methods','POST,OPTIONS')
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(blob)))
            self.end_headers(); self.wfile.write(blob)
        def do_GET(self):
            if self.path != '/health': return self.send(404,{'error':'Not found'})
            return self.send(200,{'ok':True,'version':'0.9.1','bridge_id':bridge_id})
        def do_OPTIONS(self):
            self.send(204,{})
        def do_POST(self):
            if self.path not in ('/import','/import-batch','/verify'): return self.send(404,{'error':'Not found'})
            if not secrets.compare_digest(self.headers.get('X-CreatorLab-Token',''),token):
                return self.send(401,{'error':'本地连接密钥不正确'})
            if self.path == '/verify': return self.send(200,{'ok':True,'version':'0.9.1','bridge_id':bridge_id})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>2000000: raise ValueError('请求内容过长或为空')
                payload=json.loads(self.rfile.read(length))
                result=save_batch(db,payload) if self.path=='/import-batch' else save_import(db,payload)
                return self.send(200,{'ok':True,**result})
            except (ValueError,LinkError,json.JSONDecodeError) as e:
                return self.send(400,{'error':str(e)})
            except Exception:
                return self.send(500,{'error':'导入失败，请查看本地服务日志'})
    return Handler

def run(root):
    root=Path(root)
    token=get_token(root)
    db=Path(os.getenv('CREATORLAB_DB',str(root/'local'/'creatorlab.db')))
    init_links(db)
    print('CreatorLab v0.9.1 import bridge: http://127.0.0.1:8765',flush=True)
    print('只监听本机，不读取登录凭据。',flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',PORT),handler_factory(db,token))
    server.serve_forever()

if __name__ == '__main__':
    run(Path(__file__).resolve().parent.parent)
