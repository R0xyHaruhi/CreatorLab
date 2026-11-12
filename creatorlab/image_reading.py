"""Source-observed image reading metrics, kept separate from video retention."""
import math
from creatorlab.hub import connect,utcnow

FIELDS=('image_count','avg_image_views','swipe_away_rate','text_expand_rate')


def valid(key,value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):return False
    if key=='image_count':return 1<=value<=1000 and int(value)==value
    if key=='avg_image_views':return 0<=value<=1000
    return key in ('swipe_away_rate','text_expand_rate') and 0<=value<=1


def save(db,pid,values,observed_at=None):
    at=observed_at or utcnow()
    with connect(db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS clab_image_observations(id INTEGER PRIMARY KEY,post_id INTEGER NOT NULL,metric TEXT NOT NULL,value REAL NOT NULL,observed_at TEXT NOT NULL)')
        for key in FIELDS:
            v=values.get(key)
            if valid(key,v):con.execute('INSERT INTO clab_image_observations(post_id,metric,value,observed_at) VALUES(?,?,?,?)',(pid,key,v,at))


def enrich(db,rows):
    with connect(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='clab_image_observations'").fetchone():return rows
        found={}
        for r in con.execute('SELECT * FROM clab_image_observations ORDER BY observed_at,id'):
            item=found.setdefault(r['post_id'],{'image_observed_at':{}})
            item[r['metric']]=r['value'];item['image_observed_at'][r['metric']]=r['observed_at']
    return [dict(r,**found.get(r['id'],{})) for r in rows]


def value(row,key):
    window=row.get('analysis_window')
    if row.get('media_format')!='image' or (isinstance(window,str) and window not in ('','当前累计')):return None
    if key=='image_depth':
        total=row.get('image_count');average=row.get('avg_image_views')
        if not valid('image_count',total) or not valid('avg_image_views',average) or average>total:return None
        from creatorlab.measurements import timestamp
        times=row.get('image_observed_at',{})
        if not isinstance(times,dict):times={}
        if times:
            a=timestamp(times.get('image_count'));b=timestamp(times.get('avg_image_views'))
            if not a or not b or abs((a-b).total_seconds())>7200:return None
        return average/total
    v=row.get(key)
    return v if valid(key,v) else None


def readiness(row):
    """Explain which input is absent instead of displaying an unexplained dash."""
    if row.get('media_format')!='image':return None
    count=value(row,'image_count');avg=value(row,'avg_image_views')
    if count is None and avg is None:return dict(state='not_collected',message='图文新指标尚未采集：缺少总图片数和平均浏览图片数，请同步补采。')
    if count is None:return dict(state='count_missing',message='已有平均浏览数据，但缺少总图片数。同步时会尝试从原作品页的图片计数补读；也可核对原作品后手动确认张数。')
    if avg is None:return dict(state='average_missing',message='已取得总图片数，但缺少平均浏览图片数，请从创作者中心同步补采。公开作品页不能提供平均浏览数据。')
    if value(row,'image_depth') is None:return dict(state='invalid',message='图片数与平均浏览数据不匹配或观测时间相隔过远，请重新同步；不会截成100%或把缺失当0。')
    return dict(state='ready',message='图文阅读数据已就绪。')


PUBLIC_IMAGE_COUNT=r'''() => {
 const players=[...document.querySelectorAll('.basePlayerContainer')];
 const totals=players.flatMap(p=>[...p.querySelectorAll('.YoycnaPk')].map(e=>e.innerText.trim()).filter(t=>/^\d+\s*\/\s*\d+$/.test(t)).map(t=>+t.split('/')[1]));
 return totals.length===1&&totals[0]>=1&&totals[0]<=1000?totals[0]:null;
}'''


def public_count(page,item):
    from urllib.parse import urlparse
    parsed=urlparse(page.url)
    expected=str(item['video_id'])
    if parsed.scheme!='https' or parsed.hostname not in ('www.douyin.com','douyin.com') or parsed.path.rstrip('/') not in ('/video/'+expected,'/note/'+expected):return None
    if item.get('media_format')!='image':return None
    title=' '.join(str(item.get('title') or '').split())
    if not title:return None
    visible=' '.join(page.locator('main').inner_text().split())
    if title not in visible:return None
    n=page.evaluate(PUBLIC_IMAGE_COUNT)
    return n if valid('image_count',n) else None
