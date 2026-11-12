"""Learning references with explicit provenance. AI candidates are never verified leaders."""
import json
import math
from datetime import date
from urllib.parse import urlparse
from creatorlab.hub import connect,utcnow
from creatorlab.genres import valid_genre


def profile_url(platform,url):
    p=urlparse(str(url).strip())
    if p.scheme!='https' or p.username or p.password or p.port:raise ValueError('请输入平台官方HTTPS主页链接')
    if platform=='bilibili':
        import re
        if p.hostname!='space.bilibili.com' or not re.fullmatch(r'/[1-9][0-9]*/?',p.path):raise ValueError('B站参照需要space.bilibili.com的UID主页链接')
    elif platform=='douyin':
        if p.hostname not in ('www.douyin.com','douyin.com') or not p.path.startswith('/user/') or len(p.path)<=6:raise ValueError('抖音参照需要douyin.com/user/主页链接')
    else:raise ValueError('不支持的平台')
    return 'https://'+p.netloc+p.path


def init_peers(db):
    with connect(db) as con:con.execute('''CREATE TABLE IF NOT EXISTS clab_learning_refs(
      id INTEGER PRIMARY KEY,platform TEXT NOT NULL,name TEXT NOT NULL,url TEXT NOT NULL,
      major TEXT NOT NULL,minor TEXT NOT NULL,origin TEXT NOT NULL,why TEXT NOT NULL,
      data_json TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(platform,url))''')


def save_peer(db,platform,name,url,major,minor,origin='manual',why='',data=None):
    if not name.strip() or not valid_genre(platform,major,minor):raise ValueError('请填写名称和有效的平台赛道')
    if origin not in ('manual','ai_unverified','public_search'):raise ValueError('未知来源')
    url=profile_url(platform,url);data=dict(data or {})
    allowed={'followers','sample_n','age_band','observed_at','source_url','window_name','views','like_ratio','comment_ratio','share_ratio','favorite_ratio','coin_ratio','completion_rate','matched_titles','matched_videos','evidence_urls'}
    if set(data)-allowed:raise ValueError('未知参照字段')
    for key,value in data.items():
        if key in ('matched_titles','evidence_urls'):
            if not isinstance(value,list) or len(value)>12 or not all(isinstance(t,str) and len(t)<=500 for t in value):raise ValueError('搜索证据格式无效')
            continue
        if key in ('age_band','observed_at','source_url','window_name'):continue
        if value is not None and (isinstance(value,bool) or not math.isfinite(float(value)) or float(value)<0):raise ValueError('参照数字需要为非负有限数')
    if data.get('sample_n') is not None and (not isinstance(data['sample_n'],int) or isinstance(data['sample_n'],bool)):raise ValueError('样本数需要为整数')
    if data.get('completion_rate') is not None and data['completion_rate']>1:raise ValueError('完播率不能超过100%')
    if data.get('observed_at'):date.fromisoformat(data['observed_at'])
    if origin=='ai_unverified':data={}  # models must not supply fabricated numeric benchmarks
    init_peers(db)
    with connect(db) as con:
        old=con.execute('SELECT origin FROM clab_learning_refs WHERE platform=? AND url=?',(platform,url)).fetchone()
        if old and old['origin']=='manual' and origin!='manual':return False
        con.execute('INSERT INTO clab_learning_refs(platform,name,url,major,minor,origin,why,data_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(platform,url) DO UPDATE SET name=excluded.name,major=excluded.major,minor=excluded.minor,origin=excluded.origin,why=excluded.why,data_json=excluded.data_json,updated_at=excluded.updated_at',(platform,name[:100],url,major,minor,origin,why[:1500],json.dumps(data,ensure_ascii=False),utcnow()))
    return True


def peer_rows(db,platform,major,minor):
    init_peers(db)
    with connect(db) as con:rows=[dict(r) for r in con.execute('SELECT * FROM clab_learning_refs WHERE platform=? AND major=? AND minor=? ORDER BY id DESC',(platform,major,minor))]
    for r in rows:r['data']=json.loads(r.pop('data_json'))
    return rows


def comparable(peer,age_band,today=None,window='当前累计',min_n=5):
    d=peer['data'];today=today or date.today()
    try:age=(today-date.fromisoformat(d.get('observed_at',''))).days
    except (TypeError,ValueError):return False
    p=urlparse(str(d.get('source_url','')))
    source_ok=p.scheme=='https' and bool(p.hostname) and not p.username and not p.password
    return source_ok and peer['origin']=='manual' and d.get('sample_n',0)>=min_n and (window!='当前累计' or d.get('age_band')==age_band) and d.get('window_name','当前累计')==window and 0<=age<=90 and bool(d.get('source_url'))
