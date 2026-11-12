"""Account-specific experiment context and evidence-backed feedback into planning."""
import json
import uuid
from creatorlab.hub import connect,utcnow
from creatorlab.workflow_store import get,put,documents,check_owner


def comparison_scope(db,rows):
    if not rows:raise ValueError('缺少关联作品')
    owners={(r['account_id'],r['platform']) for r in rows}
    if len(owners)!=1:raise ValueError('不能跨账号或平台进行实验比较')
    if any(r.get('visibility') in ('private','deleted','unlisted') for r in rows):
        raise ValueError('私密、删除或不可公开作品不能作为本轮实验比较')
    formats={r.get('media_format') or '未知' for r in rows}
    if len(formats)!=1:raise ValueError('视频与图文不能混为一次实验；请使用相同体裁')
    with connect(db) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hub_genres'").fetchone()
        labels={r['post_id']:dict(r) for r in con.execute('SELECT * FROM hub_genres')} if exists else {}
    confirmed=[]
    for r in rows:
        g=labels.get(r['id']) or r.get('genre')
        if g and g.get('origin') in ('manual','platform_metadata'):
            confirmed.append((g['major'],g['minor']))
    pairs=set(confirmed)
    if len(pairs)>1 or (confirmed and len(confirmed)!=len(rows)):
        raise ValueError('请先将全部关联作品确认到相同细分赛道，不能混用不同或待确认分类')
    aid,platform=next(iter(owners));pair=next(iter(pairs)) if pairs else (None,None)
    return dict(account_id=aid,platform=platform,media_format=next(iter(formats)),
                major=pair[0],minor=pair[1],confirmed=bool(pairs))


def experiment_detail(db,aid,platform,eid):
    return get(db,'experiment_detail',aid,platform,eid) or {}


def owned_experiment(db,aid,platform,eid):
    check_owner(db,aid,platform)
    with connect(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clab_experiments'").fetchone():
            raise ValueError('实验记录不存在，请重新关联作品')
        task=con.execute('SELECT * FROM clab_experiments WHERE id=? AND account_id=?',(eid,aid)).fetchone()
    if not task:raise ValueError('实验不属于当前账号')
    return dict(task)


def save_review(db,aid,platform,eid,stage,note,goal,change,confounders,conclusion,next_action,
                feedback=False,kind='内容结构'):
    from creatorlab.growth import update_experiment
    from creatorlab.review_loop import evaluate_experiment
    from creatorlab.hub import latest_posts
    task=owned_experiment(db,aid,platform,eid)
    if stage not in ('计划中','制作中','已发布待复盘','已复盘'):raise ValueError('未知状态')
    if not goal.strip() or not change.strip():raise ValueError('请记录目标和实际改动')
    if kind not in ('选题','标题','封面','内容结构','跨平台复用','发布时间'):raise ValueError('未知改动类型')
    detail=experiment_detail(db,aid,platform,eid)
    detail.update(goal=goal[:1000],change=change[:1500],confounders=confounders[:1500],
                  conclusion=conclusion[:1500],next_action=next_action[:1500],kind=kind)
    lesson=None
    if feedback:
        if stage!='已复盘' or not conclusion.strip() or not next_action.strip():
            raise ValueError('纳入建议前，请选择已复盘，并记录结论和下一步')
        rows=[r for r in latest_posts(db) if r['account_id']==aid]
        result=evaluate_experiment(db,task,rows)
        if result['status']!='可以复盘':raise ValueError('尚无可比固定窗口数据，不能把该实验作为已验证反馈')
        ids=set(json.loads(task.get('baseline_ids') or '[]')+json.loads(task.get('variant_ids') or '[]'))
        scope=comparison_scope(db,[r for r in rows if r['id'] in ids])
        if not scope['confirmed']:raise ValueError('请先确认关联作品的同一细分赛道，再将经验纳入创作建议')
        lesson=dict(experiment_id=eid,metric=task['metric'],scope=scope,kind=kind,
            conclusion=conclusion[:1500],next_action=next_action[:1500],confounders=confounders[:1500],
            hypothesis=task['hypothesis'],result=result,recorded_at=utcnow(),
            baseline_ids=json.loads(task.get('baseline_ids') or '[]'),
            variant_ids=json.loads(task.get('variant_ids') or '[]'),window=task.get('window_name'),
            limitation='同账号同平台同体裁的观察比较，不能证明改动的因果效果')
    put(db,'experiment_detail',aid,platform,eid,detail)
    update_experiment(db,eid,stage,note)
    if lesson:put(db,'lesson',aid,platform,eid,lesson)
    elif get(db,'lesson',aid,platform,eid):
        # Retraction does not delete history; it removes this lesson from future briefs.
        old=get(db,'lesson',aid,platform,eid);old['inactive']=True
        put(db,'lesson',aid,platform,eid,old)


def lessons_for(db,aid,platform,target,metric):
    scope=comparison_scope(db,[target])
    if not scope['confirmed']:return []
    from creatorlab.hub import latest_posts
    current={r['id']:r for r in latest_posts(db) if r['account_id']==aid}
    found=[]
    for doc in documents(db,'lesson',aid,platform):
        lesson=doc['data']
        if lesson.get('inactive') or lesson['metric']!=metric:continue
        expected=lesson['scope']
        if any(expected.get(k)!=scope.get(k) for k in ('media_format','major','minor','confirmed')):continue
        try:task=owned_experiment(db,aid,platform,lesson['experiment_id'])
        except ValueError:continue
        if task['stage']!='已复盘':continue
        before=json.loads(task.get('baseline_ids') or '[]');after=json.loads(task.get('variant_ids') or '[]')
        if before!=lesson.get('baseline_ids') or after!=lesson.get('variant_ids') or task.get('window_name')!=lesson.get('window'):continue
        ids=set(before+after)
        if not ids<=current.keys():continue
        try:
            if comparison_scope(db,[current[i] for i in ids])!=expected:continue
        except ValueError:continue
        # If links/categories changed later, invalidate stale feedback until reviewed again.
        detail=experiment_detail(db,aid,platform,task['id'])
        if detail.get('comparison_scope')!=expected:continue
        found.append(lesson)
    return found[:12]
