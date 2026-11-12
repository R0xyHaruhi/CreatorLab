"""Raw field observations: merged snapshots are never backdated as fixed-window evidence."""
from datetime import datetime,timezone,timedelta
import math
from creatorlab.hub import connect,METRIC_FIELDS,utcnow

WINDOWS={'24小时':(24,2),'7天':(168,12),'30天':(720,24)}


def timestamp(value):
    if not value:return None
    try:
        t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        # A date without time is insufficient for fixed-window comparisons.
        if 'T' not in str(value) and ':' not in str(value):return None
        return None if t.tzinfo is None else t.astimezone(timezone.utc)
    except (ValueError,TypeError):return None


def init_measurements(db):
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS clab_metric_observations(
          id INTEGER PRIMARY KEY,post_id INTEGER NOT NULL REFERENCES hub_posts(id),
          metric TEXT NOT NULL,value REAL NOT NULL,observed_at TEXT NOT NULL,source TEXT NOT NULL)''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_clab_observations ON clab_metric_observations(post_id,metric,observed_at)')


def record(db,pid,metrics,observed_at=None,source='manual'):
    init_measurements(db);at=timestamp(observed_at or utcnow())
    if at is None:raise ValueError('采集时间需要精确到时分，例如2026-10-26T12:00:00+08:00')
    if at>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('采集时间不能在未来')
    count=0
    with connect(db) as con:
        for key,v in metrics.items():
            if key not in METRIC_FIELDS or v is None or isinstance(v,bool):continue
            value=float(v)
            if not math.isfinite(value) or value<0:continue
            old=con.execute('SELECT observed_at,value FROM clab_metric_observations WHERE post_id=? AND metric=? AND source=? ORDER BY id DESC LIMIT 1',(pid,key,source)).fetchone()
            if old and old['value']==value and abs((at-timestamp(old['observed_at'])).total_seconds())<30:continue
            con.execute('INSERT INTO clab_metric_observations(post_id,metric,value,observed_at,source) VALUES(?,?,?,?,?)',(pid,key,value,at.isoformat(),source));count+=1
    return count


def window_metrics(db,post,window,now=None):
    if window not in WINDOWS:raise ValueError('未知观察窗口')
    init_measurements(db);published=timestamp(post.get('published_at'));now=now or datetime.now(timezone.utc)
    if published is None:return {'status':'缺少精确发布时间','metrics':{},'observed':{}}
    hours,tol=WINDOWS[window];target=published+timedelta(hours=hours)
    if now<target:return {'status':'尚未到期','target':target.isoformat(),'metrics':{},'observed':{}}
    with connect(db) as con:
        rows=con.execute('SELECT * FROM clab_metric_observations WHERE post_id=? AND observed_at>=? AND observed_at<=? ORDER BY id',(post['id'],(target-timedelta(hours=tol)).isoformat(),min(now,target+timedelta(hours=tol)).isoformat())).fetchall()
    selected={}
    for r in rows:
        distance=abs((timestamp(r['observed_at'])-target).total_seconds())
        if r['metric'] not in selected or distance<selected[r['metric']][0]:selected[r['metric']]=(distance,dict(r))
    values={k:v[1]['value'] for k,v in selected.items()};observed={k:v[1]['observed_at'] for k,v in selected.items()}
    status='已有窗口观测' if 'views' in values else '待补采' if now<=target+timedelta(hours=tol) else '窗口已错过，不能回推'
    return dict(status=status,target=target.isoformat(),metrics=values,observed=observed)


def window_rows(db,rows,window,now=None):
    result=[];statuses=[]
    for r in rows:
        found=window_metrics(db,r,window,now);statuses.append({'作品':r['title'],'窗口状态':found['status'],'目标时间':found.get('target','未知')})
        if found['metrics'].get('views') is None:continue
        item=dict(r,**{k:found['metrics'].get(k) for k in METRIC_FIELDS},metric_recorded_at=found['observed'].get('views'),analysis_window=window,field_observed_at=found['observed'])
        # Ratios require numerator and denominator observed close together.
        item['_ratio_allowed']={k:bool(k in found['observed'] and 'views' in found['observed'] and abs((timestamp(found['observed'][k])-timestamp(found['observed']['views'])).total_seconds())<=7200) for k in ('likes','comments','shares','favorites','coins','danmaku')}
        result.append(item)
    return result,statuses


def due_windows(db,rows,now=None):
    now=now or datetime.now(timezone.utc);out=[]
    for row in rows:
        for name in WINDOWS:
            r=window_metrics(db,row,name,now)
            if r['status']=='待补采':out.append({'post_id':row['id'],'作品':row['title'],'窗口':name,'到期时间':r['target']})
    return out


def latest_observed(db):
    init_measurements(db)
    with connect(db) as con:rows=con.execute('''SELECT post_id,metric,value,observed_at FROM (
      SELECT post_id,metric,value,observed_at,ROW_NUMBER() OVER(PARTITION BY post_id,metric ORDER BY observed_at DESC,id DESC) AS rank
      FROM clab_metric_observations) WHERE rank=1''').fetchall()
    result={}
    for r in rows:result.setdefault(r['post_id'],{})[r['metric']]=dict(value=r['value'],observed_at=r['observed_at'])
    return result


def view_history(db,pid):
    init_measurements(db)
    with connect(db) as con:return [dict(r) for r in con.execute("SELECT value,observed_at,source FROM clab_metric_observations WHERE post_id=? AND metric='views' ORDER BY observed_at,id",(pid,))]
