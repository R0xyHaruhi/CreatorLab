"""Small-sample onboarding, frozen reference sets, linked experiments and window evaluation."""
import json
from datetime import datetime,timezone
from statistics import median
from creatorlab.hub import connect,utcnow,METRIC_FIELDS
from creatorlab.measurements import window_metrics,due_windows


def init_loop(db):
    from creatorlab.growth import init_experiments
    init_experiments(db)
    with connect(db) as con:
        cols={r['name'] for r in con.execute('PRAGMA table_info(clab_experiments)')}
        for name,typ in [('baseline_ids','TEXT'),('variant_ids','TEXT'),('window_name','TEXT'),('baseline_value','REAL'),('baseline_evidence','TEXT')]:
            if name not in cols:con.execute(f'ALTER TABLE clab_experiments ADD COLUMN {name} {typ}')
        con.execute('''CREATE TABLE IF NOT EXISTS clab_frozen_baselines(
           id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES hub_accounts(id),name TEXT NOT NULL,
           window_name TEXT NOT NULL,created_at TEXT NOT NULL,rows_json TEXT NOT NULL)''')


def starter_observations(rows):
    good=[r for r in rows if (r.get('views') or 0)>0 and r.get('visibility') not in ('private','unlisted','deleted')]
    if not good:return [('先建立第一条可靠记录','同步一条公开作品的播放量，或手动录入原页面数据。'),('准备一条具体作品','封面与标题用于复盘，不会根据空数据评分。'),('为下一条建立观察点','保存精确发布时间，之后记录24小时与7天表现。')]
    best=max(good,key=lambda r:r['views']);likes=[r for r in good if r.get('likes') is not None and r.get('_ratio_allowed',{}).get('likes',True)]
    first=('先看一条代表作',f'「{best["title"][:50]}」该观测口径播放 {best["views"]:,}。先回看它的选题和开头；不据此解释原因。')
    if len(likes)>=2:
        r=max(likes,key=lambda r:r['likes']/r['views']);second=('找一条反馈好的作品',f'「{r["title"][:50]}」点赞/播放约 {100*r["likes"]/r["views"]:.1f}%。样本少时只作对照线索，不判胜负。')
    else:second=('当前最值得补的数据','补上至少一条作品的点赞、收藏或留存记录，才能同时看播放与观众反馈。')
    return [first,second,('这次只改一件事','选择开头、封面或表达中的一个改动，关联下一条作品，并在相同发布窗口复盘。')]


def freeze(db,aid,name,window,df):
    init_loop(db)
    if df.empty or not name.strip():raise ValueError('需要名称和实际参照作品')
    if not df.age_band.ne('未知').any():raise ValueError('需要至少一条有可信观测时刻的参照')
    if any(int(v)!=int(aid) for v in df.account_id):raise ValueError('不能混入其他账号')
    fields=['id','account_id','platform','age_band','analysis_window',*METRIC_FIELDS,'like_ratio','comment_ratio','favorite_ratio','share_ratio','coin_ratio','danmaku_ratio']
    payload=df[[c for c in fields if c in df]].to_json(orient='records')
    with connect(db) as con:return con.execute('INSERT INTO clab_frozen_baselines(account_id,name,window_name,created_at,rows_json) VALUES(?,?,?,?,?)',(aid,name[:100],window,utcnow(),payload)).lastrowid


def baselines(db,aid):
    init_loop(db)
    with connect(db) as con:return [dict(r) for r in con.execute('SELECT * FROM clab_frozen_baselines WHERE account_id=? ORDER BY id DESC',(aid,))]


def metric_value(found,metric):
    raw=found['metrics']
    ratios={'like_ratio':'likes','share_ratio':'shares','comment_ratio':'comments','favorite_ratio':'favorites','coin_ratio':'coins','danmaku_ratio':'danmaku'}
    if metric not in ratios:return raw.get(metric)
    key=ratios[metric];views=raw.get('views')
    from creatorlab.measurements import timestamp
    times=found['observed']
    if not views or raw.get(key) is None or key not in times or 'views' not in times:return None
    if abs((timestamp(times[key])-timestamp(times['views'])).total_seconds())>7200:return None
    return raw[key]/views


def link_experiment(db,eid,aid,baseline_ids,variant_ids,window):
    init_loop(db)
    baseline_ids=list(dict.fromkeys(baseline_ids));variant_ids=list(dict.fromkeys(variant_ids))
    if window not in ('24小时','7天','30天'):raise ValueError('请选择固定观察窗口')
    if not baseline_ids or not variant_ids or set(baseline_ids)&set(variant_ids):raise ValueError('参照与实验作品都要选择，且不能是同一条')
    with connect(db) as con:
        task=con.execute('SELECT account_id FROM clab_experiments WHERE id=?',(eid,)).fetchone()
        if not task or task['account_id']!=aid:raise ValueError('实验不属于此账号')
        ids=set(baseline_ids)|set(variant_ids)
        actual={r['id'] for r in con.execute('SELECT id FROM hub_posts WHERE account_id=?',(aid,))}
        if not ids<=actual:raise ValueError('不能关联其他账号的作品')
        from creatorlab.hub import latest_posts
        from creatorlab.learning_workflow import comparison_scope,experiment_detail
        from creatorlab.workflow_store import put
        rows=[r for r in latest_posts(db) if r['id'] in ids]
        scope=comparison_scope(db,rows)
        detail=experiment_detail(db,aid,scope['platform'],eid)
        detail.update(comparison_scope=scope,baseline_ids=baseline_ids,variant_ids=variant_ids)
        put(db,'experiment_detail',aid,scope['platform'],eid,detail)
        con.execute('UPDATE clab_experiments SET baseline_ids=?,variant_ids=?,window_name=?,baseline_value=NULL,baseline_evidence=NULL WHERE id=?',(json.dumps(baseline_ids),json.dumps(variant_ids),window,eid))


def evaluate_experiment(db,task,rows,now=None):
    init_loop(db)
    with connect(db) as con:stored=con.execute('SELECT * FROM clab_experiments WHERE id=?',(task['id'],)).fetchone()
    if stored:task=dict(stored)
    lookup={r['id']:r for r in rows}
    groups=[json.loads(task.get(k) or '[]') for k in ('baseline_ids','variant_ids')]
    if not all(groups):return dict(status='待关联参照与实验作品')
    from creatorlab.learning_workflow import comparison_scope,experiment_detail
    try:
        selected=[lookup[i] for group in groups for i in group]
        scope=comparison_scope(db,selected)
        if scope['account_id']!=task['account_id']:raise ValueError('实验作品不属于当前账号')
        detail=experiment_detail(db,task['account_id'],scope['platform'],task['id'])
        if detail.get('comparison_scope') and (detail['comparison_scope']!=scope or
            detail.get('baseline_ids')!=groups[0] or detail.get('variant_ids')!=groups[1]):
            raise ValueError('关联后赛道、体裁或作品发生变化，请重新关联并复盘')
    except (ValueError,KeyError) as exc:
        return dict(status='参照范围待核对',pending=[str(exc)])
    window=task.get('window_name') or '7天';values=[];pending=[];evidence=[]
    for gi,group in enumerate(groups):
        if gi==0 and task.get('baseline_value') is not None:
            frozen=json.loads(task.get('baseline_evidence') or '[]')
            baseline_evidence=[e for e in frozen if e['post_id'] in group]
            evidence.extend(baseline_evidence)
            values.append([e['value'] for e in baseline_evidence if e.get('value') is not None] or [task['baseline_value']])
            continue
        vals=[]
        for pid in group:
            row=lookup.get(pid)
            if not row:pending.append('作品不存在或不在当前账号');continue
            found=window_metrics(db,row,window,now);value=metric_value(found,task['metric'])
            evidence.append({'post_id':pid,'window':window,'observed':found['observed'],'value':value})
            if value is None:pending.append(row['title']+'：'+('目标指标未采集或分子分母时间不一致' if found['status']=='已有窗口观测' else found['status'])+('；目标时间 '+found['target'] if found.get('target') else ''))
            else:vals.append(value)
        values.append(vals)
    if pending:return dict(status='等待有效窗口数据',pending=pending,evidence=evidence)
    before=task.get('baseline_value')
    if before is None:
        before=median(values[0])
        with connect(db) as con:con.execute('UPDATE clab_experiments SET baseline_value=?,baseline_evidence=? WHERE id=?',(before,json.dumps(evidence,ensure_ascii=False),task['id']))
    after=median(values[1]);delta=after-before;relative=delta/before if before else None
    direction=-1 if task['metric']=='bounce_rate_2s' else 1
    return dict(status='可以复盘',baseline=before,result=after,delta=delta,relative=relative,
       direction='较参照改善' if delta*direction>0 else '较参照下降' if delta*direction<0 else '与参照相同',
       n_baseline=len(values[0]),n_variant=len(values[1]),exploratory=min(len(values[0]),len(values[1]))<5 or not scope['confirmed'],
       scope=scope,limitations=['小样本仅作探索' if min(len(values[0]),len(values[1]))<5 else '非随机对照，不能证明因果',
           '赛道已确认' if scope['confirmed'] else '赛道未确认，仅限同账号同体裁探索'],evidence=evidence)
