"""Other platforms by CSV, kept apart from the Douyin/Bilibili tables.

These platforms have no collector here. Data comes from files the creator exports
or types in. Stored in its own table so existing Douyin/Bilibili analysis is untouched,
and metric meanings are never merged across platforms.

Header aliases below are *guesses at common column names*, not verified against any
platform's real export. The UI always shows the detected mapping for the user to correct.
"""
import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone, timedelta
from creatorlab.hub import connect, utcnow

CN = timezone(timedelta(hours=8))
LABELS = {'xiaohongshu': '小红书', 'kuaishou': '快手', 'wechat_channels': '视频号', 'wechat_mp': '公众号',
          'youtube': 'YouTube', 'weibo': '微博', 'other': '其他平台'}
FIELDS = ('views', 'likes', 'comments', 'shares', 'favorites')
FIELD_LABELS = {'title': '标题', 'published_at': '发布时间', 'external_id': '作品ID（选填）', 'url': '链接（选填）',
                'views': '播放/阅读', 'likes': '点赞', 'comments': '评论', 'shares': '分享/转发', 'favorites': '收藏'}
# 'impressions' (曝光/展现) are not views and are intentionally NOT aliased to views.
ALIASES = {
    'title': ('标题', '作品标题', '笔记标题', '视频标题', '文章标题', '作品名称', '内容', 'title', 'video title', 'name'),
    'published_at': ('发布时间', '发布日期', '发布于', '发表时间', '创建时间', '日期', 'published', 'published_at', 'publish time', 'date', 'video publish time'),
    'external_id': ('作品id', '作品编号', '笔记id', '视频id', 'id', 'video id', 'video_id'),
    'url': ('链接', '作品链接', '网址', 'url', 'link'),
    'views': ('播放量', '播放', '播放数', '观看量', '观看次数', '观看', '阅读量', '阅读', '阅读数', '浏览量', '浏览', 'views', 'view count', 'plays'),
    'likes': ('点赞', '点赞数', '点赞量', '赞', 'likes', 'like count'),
    'comments': ('评论', '评论数', '评论量', 'comments', 'comment count'),
    'shares': ('分享', '分享数', '转发', '转发数', 'shares', 'share count'),
    'favorites': ('收藏', '收藏数', '收藏量', 'favorites', 'saves'),
}


def _norm(h):
    return re.sub(r'[\s_\-（）()]+', ' ', str(h or '').strip().lower()).strip()


def detect_mapping(headers):
    """canonical field -> header. A header is used for at most one field."""
    used, mapping = set(), {}
    normed = {h: _norm(h) for h in headers}
    for field, names in ALIASES.items():
        for name in names:  # earlier alias = higher priority, regardless of column order
            hit = next((h for h, n in normed.items() if n == _norm(name) and h not in used), None)
            if hit is not None:
                mapping[field] = hit
                used.add(hit)
                break
    return mapping


def parse_count(value):
    """'1.2万' -> 12000, '3,456' -> 3456, '' -> None. Anything else unparseable raises."""
    s = str(value if value is not None else '').strip().replace(',', '').replace('，', '')
    if s in ('', '-', '--', '—', 'None', 'nan'):
        return None
    mult = 1
    for suffix, m in (('亿', 10**8), ('万', 10**4), ('w', 10**4), ('W', 10**4), ('k', 1000), ('K', 1000)):
        if s.endswith(suffix):
            s, mult = s[:-len(suffix)], m
            break
    n = float(s) * mult
    if not math.isfinite(n) or n < 0 or n > 10**13:
        raise ValueError('数值超出范围')
    if not float(n).is_integer():raise ValueError('计数需要为整数')
    return int(n)


def parse_time(value):
    """Return ISO string with offset. Naive times are read as China time (UTC+8). Empty -> None."""
    s = str(value or '').strip()
    if not s:
        return None
    if re.fullmatch(r'\d{10}(\d{3})?', s):
        n = int(s)
        return datetime.fromtimestamp(n / 1000 if len(s) == 13 else n, timezone.utc).astimezone(CN).isoformat()
    if re.fullmatch(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',s):
        return datetime.strptime(s.replace('/','-'),'%Y-%m-%d').date().isoformat()
    s = s.replace('年', '-').replace('月', '-').replace('日', ' ').replace('/', '-').replace('T', ' ').strip()
    for fmt in ('%Y-%m-%d %H:%M:%S%z', '%Y-%m-%d %H:%M%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            t = datetime.strptime(re.sub(r'\s+', ' ', s).replace('Z', '+0000'), fmt)
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=CN)
        return t.astimezone(CN).isoformat()
    raise ValueError('无法识别的时间格式')


def init_ext(db):
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS clab_ext_posts(
          id INTEGER PRIMARY KEY, platform TEXT NOT NULL, account TEXT NOT NULL, key TEXT NOT NULL,
          title TEXT NOT NULL, published_at TEXT, url TEXT, views INTEGER, likes INTEGER, comments INTEGER,
          shares INTEGER, favorites INTEGER, imported_at TEXT NOT NULL, UNIQUE(platform,account,key))''')


def _key(external_id, title, published_at):
    if external_id:
        return 'id:' + str(external_id).strip()[:120]
    raise ValueError('无ID的作品需使用文件与行号标识')


def preview_csv(platform,account,data,mapping=None):
    if platform not in LABELS:raise ValueError('不支持的平台')
    if not str(account or '').strip():raise ValueError('请填写账号名称')
    if len(account.strip())>80:raise ValueError('账号名称最多80字')
    if len(data)>10_000_000:raise ValueError('CSV不能超过10MB')
    if isinstance(data,bytes):
        try:data=data.decode('utf-8-sig')
        except UnicodeDecodeError:data=data.decode('gb18030')
    reader=csv.DictReader(io.StringIO(data));headers=reader.fieldnames or []
    if len(headers)!=len(set(headers)):raise ValueError('CSV表头重复')
    mapping=detect_mapping(headers) if mapping is None else mapping
    if 'title' not in mapping:raise ValueError('没有找到「标题」列，请手动选择')
    if not any(f in mapping for f in FIELDS):raise ValueError('没有找到指标列')
    if any(f not in FIELD_LABELS or h not in headers for f,h in mapping.items()) or len(set(mapping.values()))!=len(mapping):raise ValueError('列对应无效或同一列重复使用')
    digest=hashlib.sha256(data.encode()).hexdigest();prepared=[];errors=[];skipped=0;ids=set()
    for line,row in enumerate(reader,2):
        if line>5001:raise ValueError('单次最多5000条')
        try:
            if None in row:raise ValueError('列数多于表头')
            title=str(row.get(mapping['title']) or '').strip()
            if not title:skipped+=1;continue
            if len(title)>500:raise ValueError('标题超过500字')
            published=parse_time(row.get(mapping.get('published_at'))) if 'published_at' in mapping else None
            vals={f:parse_count(row.get(mapping[f])) if f in mapping else None for f in FIELDS}
            approximate=[f for f in FIELDS if f in mapping and re.search(r'[万亿wWkK]$',str(row.get(mapping[f]) or '').strip())]
            external=str(row.get(mapping.get('external_id')) or '').strip()
            if len(external)>120:raise ValueError('作品ID过长')
            key='id:'+external if external else 'file:'+digest+':'+str(line)
            if external and key in ids:raise ValueError('同一文件含重复作品ID')
            ids.add(key)
            url=str(row.get(mapping.get('url')) or '').strip()[:500]
            if url and not re.match(r'https?://',url):url=None
            prepared.append(dict(title=title,published_at=published,url=url,key=key,approx_fields=approximate,**vals))
        except (ValueError,OverflowError,OSError) as exc:
            skipped+=1
            if len(errors)<10:errors.append(f'第 {line} 行：{exc}')
    return dict(rows=prepared,skipped=skipped,errors=errors,mapping=mapping)


def import_csv(db,platform,account,data,mapping=None):
    plan=preview_csv(platform,account,data,mapping);init_ext(db)
    from creatorlab.maintenance import database_gate,backup_database
    out=dict(inserted=0,updated=0,skipped=plan['skipped'],errors=plan['errors'],mapping=plan['mapping'])
    with database_gate(db):
        backup_database(db,'before-external-csv')
        with connect(db) as con:
            if 'approx_fields' not in {r[1] for r in con.execute('PRAGMA table_info(clab_ext_posts)')}:con.execute("ALTER TABLE clab_ext_posts ADD COLUMN approx_fields TEXT NOT NULL DEFAULT '[]'")
            for row in plan['rows']:
                existing=con.execute('SELECT * FROM clab_ext_posts WHERE platform=? AND account=? AND key=?',(platform,account.strip()[:80],row['key'])).fetchone()
                if existing:
                    approx=set(json.loads(existing['approx_fields']))
                    for field in FIELDS:
                        if row[field] is not None:
                            approx.discard(field)
                            if field in row['approx_fields']:approx.add(field)
                    con.execute('UPDATE clab_ext_posts SET title=?,published_at=COALESCE(?,published_at),url=COALESCE(?,url),'+','.join(f'{f}=COALESCE(?,{f})' for f in FIELDS)+',imported_at=?,approx_fields=? WHERE id=?',(row['title'],row['published_at'],row['url'],*[row[f] for f in FIELDS],utcnow(),json.dumps(sorted(approx)),existing['id']))
                    out['updated']+=1
                else:
                    con.execute('INSERT INTO clab_ext_posts(platform,account,key,title,published_at,url,'+','.join(FIELDS)+',imported_at,approx_fields) VALUES('+','.join('?' for _ in range(13))+')',(platform,account.strip()[:80],row['key'],row['title'],row['published_at'],row['url'],*[row[f] for f in FIELDS],utcnow(),json.dumps(row['approx_fields'])))
                    out['inserted']+=1
    return out


def ext_posts(db, platform=None):
    """Rows shaped like the main post rows (platform, account_name, title, published_at, metrics)."""
    init_ext(db)
    q, args = 'SELECT * FROM clab_ext_posts', ()
    if platform:
        q, args = q + ' WHERE platform=?', (platform,)
    with connect(db) as con:
        rows = [dict(r) for r in con.execute(q + ' ORDER BY id DESC', args)]
    for r in rows:
        r['account_name'] = r['account']
        r['approx_fields']=json.loads(r.get('approx_fields') or '[]')
    return rows


def delete_account(db, platform, account):
    init_ext(db)
    from creatorlab.maintenance import backup_database
    backup_database(db,'before-external-delete')
    with connect(db) as con:
        return con.execute('DELETE FROM clab_ext_posts WHERE platform=? AND account=?', (platform, account)).rowcount
