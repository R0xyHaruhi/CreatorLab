"""Unified local creator accounts, posts, projects and metric snapshots.

Never infers missing metrics; only creator-supplied or explicitly imported records.
"""
import csv
import io
import re
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

PLATFORMS = ('douyin', 'bilibili')
COUNT_FIELDS = ('views', 'likes', 'comments', 'shares', 'favorites', 'coins', 'danmaku')
RATE_FIELDS = ('completion_rate', 'completion_rate_5s', 'bounce_rate_2s', 'avg_view_proportion')
METRIC_FIELDS = COUNT_FIELDS + RATE_FIELDS + ('avg_view_second',)


@contextmanager
def connect(db):
    p = Path(db)
    p.parent.mkdir(parents=True, exist_ok=True)
    from creatorlab.maintenance import database_gate
    with database_gate(db):
        con = sqlite3.connect(str(p), timeout=15)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback();raise
        finally:con.close()


def init_hub(db):
    from creatorlab.maintenance import database_gate,prepare_upgrade
    with database_gate(db):
        backup=prepare_upgrade(db)
        try:
            _init_hub(db)
            with connect(db) as con:con.execute('PRAGMA user_version=20400')
        except Exception:
            if backup:
                from contextlib import closing
                with closing(sqlite3.connect(str(backup))) as source,closing(sqlite3.connect(str(db))) as target:source.backup(target)
            raise


def _init_hub(db):
    with connect(db) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS hub_accounts(
          id INTEGER PRIMARY KEY, platform TEXT NOT NULL, handle TEXT NOT NULL,
          display_name TEXT NOT NULL, is_self INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, UNIQUE(platform,handle));
        CREATE TABLE IF NOT EXISTS hub_projects(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hub_posts(
          id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES hub_accounts(id),
          external_id TEXT, title TEXT NOT NULL, published_at TEXT,
          url TEXT, project_id INTEGER REFERENCES hub_projects(id), source TEXT NOT NULL,
          source_ref TEXT, last_synced TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0,
          UNIQUE(account_id,external_id));
        CREATE TABLE IF NOT EXISTS hub_snapshots(
          id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES hub_posts(id) ON DELETE CASCADE,
          recorded_at TEXT NOT NULL, views INTEGER, likes INTEGER, comments INTEGER,
          shares INTEGER, favorites INTEGER, completion_rate REAL,
          completion_rate_5s REAL, bounce_rate_2s REAL,
          avg_view_proportion REAL, avg_view_second REAL,
          source TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_hub_snapshots_post ON hub_snapshots(post_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_hub_posts_account ON hub_posts(account_id);
        ''')
        snapshot_cols={r['name'] for r in con.execute('PRAGMA table_info(hub_snapshots)')}
        for name in ('coins','danmaku'):
            if name not in snapshot_cols:con.execute(f'ALTER TABLE hub_snapshots ADD COLUMN {name} INTEGER')
        cols={r['name'] for r in con.execute('PRAGMA table_info(hub_posts)')}
        for name in ('cover_url','visibility'):
            if name not in cols:con.execute(f'ALTER TABLE hub_posts ADD COLUMN {name} TEXT')

    from creatorlab.content_analysis import init_content
    init_content(db)

def utcnow():
    return datetime.now(timezone.utc).isoformat()


def add_account(db, platform, handle, name=None):
    if platform not in PLATFORMS: raise ValueError('不支持的平台')
    handle = str(handle).strip()
    if not 1 <= len(handle) <= 100: raise ValueError('请填写账号 ID / UID')
    with connect(db) as con:
        con.execute('''INSERT INTO hub_accounts(platform,handle,display_name,created_at)
            VALUES(?,?,?,?) ON CONFLICT(platform,handle)
            DO UPDATE SET display_name=excluded.display_name''',
            (platform,handle,(name or handle).strip()[:120],utcnow()))
        return con.execute('SELECT id FROM hub_accounts WHERE platform=? AND handle=?', (platform,handle)).fetchone()['id']


def accounts(db):
    with connect(db) as con:
        return [dict(r) for r in con.execute('SELECT * FROM hub_accounts ORDER BY id')]


def projects(db):
    with connect(db) as con:
        return [dict(r) for r in con.execute('SELECT * FROM hub_projects ORDER BY id DESC')]


def add_project(db, name, notes=''):
    if not name.strip(): raise ValueError('请输入内容项目名称')
    with connect(db) as con:
        return con.execute('INSERT INTO hub_projects(name,notes,created_at) VALUES(?,?,?)',
                           (name.strip()[:180],notes.strip()[:1000],utcnow())).lastrowid


def assign_project(db, post_id, project_id):
    with connect(db) as con:
        if project_id is not None and not con.execute('SELECT id FROM hub_projects WHERE id=?',(project_id,)).fetchone():
            raise ValueError('项目不存在')
        con.execute('UPDATE hub_posts SET project_id=? WHERE id=?',(project_id,post_id))


def _number(value, field):
    if value is None or str(value).strip()=='': return None
    try: n=float(str(value).replace(',','').replace('，','').strip().rstrip('%'))
    except (TypeError,ValueError): raise ValueError(f'{field} 不是数字')
    import math
    if not math.isfinite(n) or n<0: raise ValueError(f'{field} 不能为负数或无穷')
    if field in COUNT_FIELDS:
        if n!=int(n) or n>10**13: raise ValueError(f'{field} 需要非负整数')
        return int(n)
    if field in RATE_FIELDS:
        raw=str(value).strip()
        if raw.endswith('%'): n/=100
        # Numeric API values are fractions by contract; no guessing based on magnitude.
        if n>1: raise ValueError(f'{field} 必须为 0–1 比例或百分比字符串，例如 25%')
    if n>100000: raise ValueError(f'{field} 超出允许范围')
    return n


def validate_publication_date(value):
    """Accept a calendar date or ISO date and time without inventing a zone."""
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}.*)?', value):
            raise ValueError
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('发布时间无效，请留空或填写 YYYY-MM-DD。精确时间示例：2026-10-26T12:00:00+08:00') from None
    return value


def update_publication_date(db, account_id, post_id, value):
    value = validate_publication_date(value)
    with connect(db) as con:
        updated = con.execute('UPDATE hub_posts SET published_at=? WHERE id=? AND account_id=?',
                              (value, post_id, account_id))
        if not updated.rowcount:
            raise ValueError('这条作品已不在当前账号下')


def upsert_post(db, account_id, title, external_id=None, published_at=None, url=None,
                metrics=None, source='manual', source_ref=None, cover_url=None, visibility=None,observed_at=None):
    title=str(title or '').strip()
    if not title: raise ValueError('作品标题不能为空')
    if len(title)>500: raise ValueError('作品标题过长')
    if source not in ('manual','csv','douyin_creator_center','bilibili_manual','bilibili_space'): raise ValueError('数据来源不合法')
    if source in ('manual', 'csv', 'bilibili_manual'):
        published_at = validate_publication_date(published_at)
    external_id=str(external_id).strip() if external_id else None
    if external_id and len(external_id)>120: raise ValueError('外部 ID 过长')
    if cover_url and not valid_cover(cover_url): cover_url=None
    if visibility not in ('public','private','unlisted','deleted'): visibility=None
    metrics=metrics or {}
    values={k:_number(metrics.get(k),k) for k in METRIC_FIELDS}
    now=utcnow()
    raw_values=dict(values)
    from creatorlab.measurements import timestamp
    if observed_at:
        from datetime import timedelta
        at=timestamp(observed_at)
        if at is None or at>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('采集时间需包含时分和时区，且不能在未来')
    with connect(db) as con:
        if not con.execute('SELECT id FROM hub_accounts WHERE id=?',(account_id,)).fetchone():
            raise ValueError('请选择已添加的账号')
        # No fuzzy title dedupe: identical titles are legitimate separate works.
        existing = con.execute('SELECT id FROM hub_posts WHERE account_id=? AND external_id=?',
                               (account_id,external_id)).fetchone() if external_id else None
        if existing:
            pid=existing['id']
            con.execute('''UPDATE hub_posts SET title=?,published_at=COALESCE(NULLIF(?,''),published_at),
              url=COALESCE(NULLIF(?,''),url),cover_url=COALESCE(?,cover_url),
              visibility=COALESCE(?,visibility),source=?,source_ref=?,last_synced=? WHERE id=?''',
              (title,published_at or '',url or '',cover_url,visibility,source,source_ref,now,pid))
        else:
            pid=con.execute('''INSERT INTO hub_posts(account_id,external_id,title,published_at,url,cover_url,visibility,source,source_ref,last_synced)
              VALUES(?,?,?,?,?,?,?,?,?,?)''',
              (account_id,external_id,title,published_at,url,cover_url,visibility,source,source_ref,now)).lastrowid
        if any(v is not None for v in values.values()):
            # An incremental update must not erase previously known metrics.
            previous=con.execute('SELECT * FROM hub_snapshots WHERE post_id=? ORDER BY id DESC LIMIT 1',(pid,)).fetchone()
            if previous:
                values={k:(v if v is not None else previous[k]) for k,v in values.items()}
            fields=', '.join(METRIC_FIELDS)
            q=','.join('?' for _ in METRIC_FIELDS)
            con.execute(f'''INSERT INTO hub_snapshots(post_id,recorded_at,{fields},source)
              VALUES(?,?,{q},?)''',(pid,now,*(values[k] for k in METRIC_FIELDS),source))
    from creatorlab.measurements import record
    if any(v is not None for v in raw_values.values()) and (source in ('manual','bilibili_space','bilibili_manual') or observed_at):record(db,pid,raw_values,observed_at,source)
    return pid


def latest_posts(db,include_references=False):
    with connect(db) as con:
        q='''SELECT p.*,a.platform,a.handle,a.display_name as account_name,pr.name as project_name,
          s.recorded_at as metric_recorded_at,'''+','.join('s.'+x for x in METRIC_FIELDS)+'''
          FROM hub_posts p JOIN hub_accounts a ON p.account_id=a.id
          LEFT JOIN hub_projects pr ON p.project_id=pr.id
          LEFT JOIN hub_snapshots s ON s.id=(SELECT max(id) FROM hub_snapshots WHERE post_id=p.id)
          WHERE p.demo=0 ORDER BY p.id DESC'''
        if not include_references:q=q.replace('WHERE p.demo=0','WHERE p.demo=0 AND a.is_self=1')
        rows = [dict(r) for r in con.execute(q)]
    from creatorlab.measurements import latest_observed,timestamp
    actual=latest_observed(db)
    for r in rows:
        fields=actual.get(r['id'],{})
        for key,point in fields.items():
            r[key]=int(point['value']) if key in COUNT_FIELDS else point['value']
        r['field_observed_at']={k:v['observed_at'] for k,v in fields.items()}
        r['metric_recorded_at']=r['field_observed_at'].get('views')
        r['_ratio_allowed']={k:bool(k in fields and 'views' in fields and abs((timestamp(fields[k]['observed_at'])-timestamp(fields['views']['observed_at'])).total_seconds())<=7200) for k in ('likes','comments','shares','favorites','coins','danmaku')}
    from creatorlab.work_formats import formats
    known_formats=formats(db)
    rows=[dict(r,media_format=known_formats.get(r['id'],'video' if r['platform']=='bilibili' else 'unknown')) for r in rows]
    from creatorlab.image_reading import enrich as enrich_images
    rows=enrich_images(db,rows)
    from creatorlab.bilibili_metadata import metadata_rows
    metadata=metadata_rows(db)
    rows=[dict(r,**metadata.get(r['id'],{})) for r in rows]
    from creatorlab.content_analysis import enrich
    from creatorlab.genres import genre_rows,LEGACY_TRACK
    result=genre_rows(db,enrich(db,rows))
    return [dict(r,_db=str(db),track=LEGACY_TRACK.get(r['genre']['major'],'其他') if r.get('genre') else r['track']) for r in result]


def _read_csv(data):
    if len(data)>10_000_000:raise ValueError('CSV不能超过10MB')
    if isinstance(data,bytes):
        try:data=data.decode('utf-8-sig')
        except UnicodeDecodeError:data=data.decode('gb18030')
    reader=csv.DictReader(io.StringIO(data))
    if not reader.fieldnames: raise ValueError('CSV 缺少表头')
    reader.fieldnames=[name.strip() for name in reader.fieldnames]
    if len(reader.fieldnames)!=len(set(reader.fieldnames)):raise ValueError('CSV表头存在重复字段')
    if 'title' not in reader.fieldnames: raise ValueError('CSV 需要 title 列')
    from itertools import islice
    numbered_rows=[(reader.line_num, row) for row in islice(reader,5001)]
    rows=[row for _, row in numbered_rows]
    if len(rows)>5000: raise ValueError('单次最多 5000 条')
    if not rows: return []
    # Validate before writing, avoid silent partial imports from invalid values.
    for line_number,r in numbered_rows:
        if None in r:raise ValueError(f'CSV第{line_number}行的字段多于表头，请检查分隔符和引号')
        for key in ('title','external_id','published_at','observed_at'):
            if r.get(key):r[key]=r[key].strip()
        try:
            validate_publication_date(r.get('published_at'))
        except ValueError as exc:
            raise ValueError(f'CSV 第 {line_number} 行：{exc}') from exc
        if not (r.get('title') or '').strip(): raise ValueError('CSV 中存在空标题')
        if len(r['title'].strip())>500:raise ValueError('CSV标题超过500字')
        if len(str(r.get('external_id') or '').strip())>120:raise ValueError('CSV外部ID超过120字符')
        if r.get('observed_at'):
            from creatorlab.measurements import timestamp
            from datetime import timedelta
            at=timestamp(r['observed_at'])
            if at is None or at>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('CSV采集时间需要含时区，且不能在未来')
        for field in METRIC_FIELDS: _number(r.get(field),field)
        if r.get('duration_seconds'):
            try: duration=float(r['duration_seconds'])
            except ValueError: raise ValueError('duration_seconds 不是有效数字')
            if not 0<duration<=86400: raise ValueError('时长需要在 0–86400 秒之间')
    identifiers=[r.get('external_id').strip() for r in rows if r.get('external_id') and r['external_id'].strip()]
    if len(identifiers)!=len(set(identifiers)):raise ValueError('CSV内存在重复视频ID，请先合并同一作品的记录')
    return rows


def preview_csv(db,account_id,data):
    import hashlib
    rows=_read_csv(data);digest=hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()
    with connect(db) as con:
        if not con.execute('SELECT 1 FROM hub_accounts WHERE id=?',(account_id,)).fetchone():raise ValueError('请先选择账号')
        con.execute('CREATE TABLE IF NOT EXISTS clab_csv_imports(account_id INTEGER,file_hash TEXT,created_at TEXT,PRIMARY KEY(account_id,file_hash))')
        duplicate=bool(con.execute('SELECT 1 FROM clab_csv_imports WHERE account_id=? AND file_hash=?',(account_id,digest)).fetchone())
        known={r[0] for r in con.execute('SELECT external_id FROM hub_posts WHERE account_id=?',(account_id,))}
    return {'rows':rows,'hash':digest,'duplicate':duplicate,'updates':sum(r.get('external_id') in known for r in rows),'missing_ids':sum(not r.get('external_id') for r in rows)}


def import_csv(db,account_id,data,*,return_ids=False):
    from creatorlab.maintenance import database_gate,backup_database
    with database_gate(db):
        plan=preview_csv(db,account_id,data);rows=plan['rows']
        if not rows or plan['duplicate']:return [] if return_ids else 0
        backup=backup_database(db,'before-csv')
        imported_ids=[]
        try:
            for r in rows:
                pid=upsert_post(db,account_id,r['title'],external_id=r.get('external_id'),
                            published_at=r.get('published_at'),url=r.get('url'),
                            metrics={k:r.get(k) for k in METRIC_FIELDS},source='csv',
                            cover_url=r.get('cover_url'),visibility=r.get('visibility'),observed_at=r.get('observed_at') or None)
                imported_ids.append(pid)
                if any(r.get(k) for k in ('track','category','topic','duration_seconds')):
                    from creatorlab.content_analysis import annotate
                    with connect(db) as con:previous=con.execute('SELECT * FROM hub_content WHERE post_id=?',(pid,)).fetchone()
                    previous=dict(previous) if previous else {}
                    annotate(db,pid,r.get('track') or previous.get('track','未标注'),r.get('category') or previous.get('category','未分类'),r.get('topic') or previous.get('topic',''),float(r['duration_seconds']) if r.get('duration_seconds') else previous.get('duration_seconds'))
            with connect(db) as con:con.execute('INSERT INTO clab_csv_imports VALUES(?,?,?)',(account_id,plan['hash'],utcnow()))
        except Exception:
            from contextlib import closing
            with closing(sqlite3.connect(str(backup))) as source,closing(sqlite3.connect(str(db))) as target:source.backup(target)
            raise
        return imported_ids if return_ids else len(rows)


def import_douyin_existing(db, account_id, legacy_db):
    """Explicitly copy legacy creator_center_videos to hub; idempotent by original video_id.
    Items without external IDs use stable legacy row IDs, not fuzzy titles.
    """
    from creatorlab.bridge import list_batch
    from creatorlab.maintenance import database_gate,backup_database
    from contextlib import closing
    with database_gate(db):
        with connect(db) as con:
            account=con.execute('SELECT platform,is_self FROM hub_accounts WHERE id=?',(account_id,)).fetchone()
        if not account or account['platform']!='douyin' or not account['is_self']:
            raise ValueError('请选择自己的抖音账号')
        backup=backup_database(db,'before-legacy-import')
        try:
            rows=list_batch(legacy_db)
            count=0
            for r in rows:
                key=str(r.get('video_id') or f"legacy-row-{r['id']}")
                upsert_post(db,account_id,r['title'],external_id=key,published_at=r.get('published_at'),
                            url=r.get('url'), source='douyin_creator_center',source_ref=str(r['id']),
                            cover_url=r.get('cover_url'),visibility=r.get('visibility'),
                            metrics={'views':r.get('views'),'likes':r.get('likes'),'comments':r.get('comments'),
                                     'shares':r.get('shares'),'favorites':r.get('favorites'), 'avg_view_second':r.get('avg_view_second'),
                                     **{k:r.get(k) for k in RATE_FIELDS}})
                count+=1
            return count
        except Exception:
            with closing(sqlite3.connect(str(backup))) as source,closing(sqlite3.connect(str(db))) as target:source.backup(target)
            raise



def snapshots(db, post_id):
    with connect(db) as con:
        return [dict(r) for r in con.execute('SELECT * FROM hub_snapshots WHERE post_id=? ORDER BY id',(post_id,))]


def fmt_count(n):
    if n is None: return '—'
    n=float(n)
    if n>=1e8: return f'{n/1e8:.2f} 亿'
    if n>=1e4: return f'{n/1e4:.2f} 万'
    return f'{int(n):,}'


def fmt_rate(n,decimals=1):
    return '—' if n is None else f'{float(n)*100:.{decimals}f}%'


def fmt_seconds(n):
    return '—' if n is None else f'{float(n):.1f} 秒'


def auto_sync_douyin(db):
    """Import already captured local creator-center data without manual account setup.

    No remote page access, cookies or background requests. Existing account rows
    are reused, and unchanged legacy data does not generate duplicate snapshots.
    """
    from creatorlab.bridge import list_batch
    try:
        rows=list_batch(db)
    except Exception:
        return {'available':False,'processed':0,'reason':'尚无本地抖音采集记录'}
    if not rows:
        return {'available':False,'processed':0,'reason':'尚无本地抖音采集记录'}
    existing=accounts(db)
    own=[a for a in existing if a['platform']=='douyin' and a['is_self']]
    if len(own)>1:return {'available':False,'processed':0,'total':len(rows),'reason':'本地旧采集记录尚未绑定账号，请到设置中选择归属后手动导入'}
    chosen=own[0] if own else None
    aid=chosen['id'] if chosen else add_account(db,'douyin','local_creator_center','我的抖音（已导入）')
    with connect(db) as con:
        current={r['external_id']:dict(r) for r in con.execute(
            'SELECT p.*, s.views,s.likes,s.comments,s.shares,s.favorites,s.completion_rate,s.completion_rate_5s,s.bounce_rate_2s,s.avg_view_proportion,s.avg_view_second FROM hub_posts p LEFT JOIN hub_snapshots s ON s.id=(SELECT max(id) FROM hub_snapshots WHERE post_id=p.id) WHERE p.account_id=?',(aid,))}
    updates=0
    for r in rows:
        key=str(r.get('video_id') or f"legacy-row-{r['id']}")
        fields={'views':r.get('views'),'likes':r.get('likes'),'comments':r.get('comments'),
          'shares':r.get('shares'),'favorites':r.get('favorites'),'avg_view_second':r.get('avg_view_second'),
          **{k:r.get(k) for k in RATE_FIELDS}}
        old=current.get(key)
        if old and old['title']==r['title'] and (not r.get('published_at') or old.get('published_at')==r['published_at']) and (not r.get('cover_url') or old.get('cover_url')==r['cover_url']) and (not r.get('visibility') or old.get('visibility')==r['visibility']) and all(
          value is None or old.get(field)==value for field,value in fields.items()):
            continue
        upsert_post(db,aid,r['title'],external_id=key,published_at=r.get('published_at'),
          url=r.get('url'),cover_url=r.get('cover_url'),visibility=r.get('visibility'),
          source='douyin_creator_center',source_ref=str(r['id']),metrics=fields)
        updates+=1
    return {'available':True,'processed':updates,'total':len(rows),'account_id':aid}


def valid_cover(url):
    if not isinstance(url,str) or len(url)>2048:return False
    parsed=urlparse(url)
    return parsed.scheme=='https' and bool(parsed.hostname) and not parsed.username and not parsed.password

def quality(post):
    """Never infer privacy from a zero metric; separate unknown, suspect and excluded."""
    visibility=post.get('visibility')
    if visibility in ('private','unlisted','deleted'):return '不可公开计量'
    views=post.get('views')
    if views is None:return '播放量缺失'
    if views==0 and any((post.get(k) or 0)>0 for k in ('likes','comments','shares','favorites')):
        return '播放量疑似异常'
    if views==0:return '零播放待核实'
    return '可分析'

def eligible(posts):
    """Only positive and credible observed views participate in traffic comparisons."""
    return [r for r in posts if quality(r)=='可分析']

def sort_posts(rows, order):
    mapping={'最新发布':('published_at',True),'最早发布':('published_at',False),
      '播放量最高':('views',True),'播放量最低':('views',False),
      '点赞最多':('likes',True),'评论最多':('comments',True),
      '分享最多':('shares',True),'完播率最高':('completion_rate',True),
      '跳出率最高':('bounce_rate_2s',True),'平均观看最长':('avg_view_second',True)}
    field,descending=mapping.get(order,('published_at',True))
    # Missing metrics must always sort last. Text dates are ISO in automatic import.
    known=[r for r in rows if r.get(field) not in (None,'')]
    missing=[r for r in rows if r.get(field) in (None,'')]
    return sorted(known,key=lambda r:(str(r[field]) if field=='published_at' else float(r[field])),reverse=descending)+missing
