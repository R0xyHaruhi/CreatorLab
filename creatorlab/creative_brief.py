"""Five concrete hypotheses tied to saved observations, never invented causal facts."""
import hashlib
import json
import math
import re
import uuid
from statistics import median
from creatorlab.hub import utcnow,connect
from creatorlab.reporting import cohort,metric_value
from creatorlab.workflow_store import put,get,documents

KINDS=('选题','标题','封面','内容结构','跨平台复用')


def confirmed_track(row):
    g=row.get('genre') or {}
    return (g.get('major'),g.get('minor')) if g.get('origin') in ('manual','platform_metadata') else (None,None)


def evidence(row,kind='personal'):
    external=kind=='external'
    key='R:'+row['bvid'] if external else 'P:'+str(row['id'])
    fields=('views','likes','comments','favorites','shares','coins','danmaku','completion_rate',
            'like_ratio','favorite_ratio','share_ratio','image_count','avg_image_views','image_depth')
    values={k:metric_value(row,k) for k in fields}
    values={k:float(v) if v is not None else None for k,v in values.items()}
    return dict(id=key,type='公开精选样本' if external else '个人作品',title=row['title'],
        url=row.get('source_url') if external else row.get('url') or '',
        observed_at=row.get('observed_at') if external else row.get('metric_recorded_at'),
        values=values,tags=list(row.get('tags') or row.get('bili_tags') or []),
        precision=row.get('precision',{}),window=row.get('analysis_window') or '当前累计')


def build_brief(rows,target,metric,external_scope=None,external_samples=(),lessons=(),linked_rows=(),manual_peer=None,personal_scope='all'):
    if target.get('demo'):raise ValueError('演示作品不能保存为真实创作方案')
    track=confirmed_track(target)
    own=cohort(rows,target,scope=personal_scope)
    measured=[r for r in own if metric_value(r,metric) is not None]
    measured.sort(key=lambda r:metric_value(r,metric),reverse=metric!='bounce_rate_2s')
    anchor=measured[0] if measured else target
    selected=[target]+[r for r in measured[:7] if r['id']!=target['id']]
    facts=[evidence(r) for r in selected]
    limits=['累计观测受发布时间、热点、投流和受众影响；相关差异不能证明因果',
            '未分析真实封面、关键帧或完整内容，封面和结构建议均为待验证改动']
    if len(measured)<5:limits.append('同范围历史目标指标不足5条，仅提出探索假设，不判胜负')
    if not track[0]:limits.append('当前作品赛道未人工确认，不自动归为某个细分赛道')
    external=[]
    if external_scope:
        if target['platform']!='bilibili' or external_scope.get('platform','bilibili')!='bilibili' or track!=(external_scope.get('major'),external_scope.get('minor')):
            raise ValueError('外部参照必须与当前作品同平台、同已确认细分赛道')
        if target.get('analysis_window') not in (None,'','当前累计'):
            raise ValueError('精选参照为累计数据，不能与固定窗口混用')
        own_bvids={str(r.get('external_id')) for r in rows if r.get('platform')=='bilibili'}
        external=[r for r in external_samples if r['bvid'] not in own_bvids]
        facts.extend(evidence(r,'external') for r in external[:5])
        limits.append('外部参照为人工挑选的热门作品，存在入选偏差，不代表全站或普通用户')
        if len(external)<5:limits.append('外部参照不足5条，仅作具体作品学习，不生成排名')
    manual_peer_n=0
    if manual_peer:
        from creatorlab.peers import comparable
        from creatorlab.content_analysis import frame
        from urllib.parse import urlparse
        prepared=frame([target]);age=prepared.iloc[0]['age_band'] if not prepared.empty else '未知'
        window=target.get('analysis_window') or '当前累计'
        hosts={'bilibili':{'www.bilibili.com','space.bilibili.com','bilibili.com'},'douyin':{'www.douyin.com','douyin.com'}}
        source=manual_peer['data'].get('source_url','')
        if (manual_peer['platform']!=target['platform'] or track!=(manual_peer['major'],manual_peer['minor']) or
            not comparable(manual_peer,age,window=window,min_n=1) or urlparse(source).hostname not in hosts[target['platform']]):
            raise ValueError('人工参照需要同平台、同已确认赛道、可比窗口与近期官方来源')
        manual_peer_n=manual_peer['data']['sample_n']
        facts.append(dict(id='E:'+str(manual_peer['id']),type='人工核验的同平台参照（数值由用户录入）',
            title=manual_peer['name'],url=source,observed_at=manual_peer['data']['observed_at'],
            values={k:manual_peer['data'].get(k) for k in ('views','like_ratio','favorite_ratio','share_ratio','completion_rate')},
            tags=[],precision={},window=window))
        limits.append('人工参照的样本数与典型数值由用户核对录入，不代表该账号全部作品或全站')
    linked=[r for r in linked_rows if target.get('project_id') and r.get('project_id')==target['project_id']
            and r['platform']!=target['platform'] and not r.get('demo')]
    # Cross-platform evidence is context only; never pool metrics into the primary cohort.
    for r in linked[:3]:
        item=evidence(r);item['type']='已手动关联的另一平台版本';facts.append(item)
    if not linked:limits.append('没有同内容跨平台实测版本，复用建议只说明适配方式，不判断哪个平台更好')
    theme=re.split(r'[#＃]',str(anchor['title']))[0].strip()[:48] or str(target['title'])[:48]
    own_id='P:'+str(anchor['id'])
    ids=[own_id]
    if external:ids.append('R:'+external[0]['bvid'])
    if manual_peer:ids.append('E:'+str(manual_peer['id']))
    cards=[
        dict(kind='选题',change=f'围绕「{theme}」只补充一个相邻问题：最容易忽略的是哪一步？',
             hypothesis='复用已有题材，测试一个更具体的问题是否值得继续做',evidence_ids=ids),
        dict(kind='标题',change=f'保留主题，试用标题「{theme}：先看结果，再拆关键一步」；正文必须兑现标题',
             hypothesis='只调整标题信息顺序，保持题材、封面和内容结构尽量相近',evidence_ids=[own_id]),
        dict(kind='封面',change=f'从真实素材选一张能说明「{theme}」的结果画面，只保留「关键一步」一处短字；不同时更换标题',
             hypothesis='测试更明确的主题与单一视觉焦点；未提供素材时不能判断现有封面好坏',evidence_ids=[own_id]),
        dict(kind='内容结构',change=('第1张先给结果，后续图片按操作顺序，每张聚焦一个要点；保留真实总张数，不估算阅读深度'
              if target.get('media_format')=='image' else '只调整开头：先呈现结果或问题，再讲关键一步，最后回应开头；其余题材与时长尽量保持'),
             hypothesis='检验表达顺序，使用相同固定窗口；图文阅读深度与视频完播率分开复盘',evidence_ids=ids),
        dict(kind='跨平台复用',change=f'将「{theme}」保留为同一内容项目：抖音版开头直接呈现结果，B站版补足背景和步骤；分别与各账号同窗口历史比较',
             hypothesis='这是平台表达适配假设；不混合两平台指标，也不把跨平台累计播放差异解释成平台效果',
             evidence_ids=['P:'+str(target['id'])]+(['P:'+str(linked[0]['id'])] if linked else [])),
    ]
    learned=[]
    for lesson in lessons:
        if lesson.get('inactive') or lesson.get('metric')!=metric:continue
        s=lesson.get('scope',{})
        if s.get('platform')!=target['platform'] or s.get('account_id')!=target['account_id']:continue
        if (s.get('major'),s.get('minor'))!=track or s.get('media_format')!=(target.get('media_format') or '未知'):continue
        learned.append(lesson)
        facts.append(dict(id='L:'+str(lesson['experiment_id']),type='本账号已复盘实验（非因果证明）',
            title='实验 #'+str(lesson['experiment_id']),url='',observed_at=lesson['recorded_at'],
            values={k:lesson['result'][k] for k in ('baseline','result','n_baseline','n_variant')},
            tags=[],precision={},window=lesson['window']))
    for card in cards:
        applicable=[l for l in learned if l['kind']==card['kind']]
        if applicable:
            l=applicable[0]
            card['prior_experiment_id']=l['experiment_id']
            card['window']=l['window']
            card['evidence_ids']=card['evidence_ids']+['L:'+str(l['experiment_id'])]
            card['change']='按已有复盘继续验证：'+l['next_action']
            card['hypothesis']='来自本账号已复盘实验的探索经验，下一条仍需重复验证：'+l['conclusion']
    return dict(account_id=target['account_id'],platform=target['platform'],target_id=target['id'],
        title=target['title'],metric=metric,track=list(track),media_format=target.get('media_format') or '未知',
        created_at=utcnow(),observations=dict(personal_scope=personal_scope,personal_n=len(measured),target_value=metric_value(target,metric),
            personal_median=median([metric_value(r,metric) for r in measured]) if measured else None,
            external_n=len(external),external_scope=external_scope,manual_peer_sample_n=manual_peer_n,linked_versions=len(linked)),
        evidence=facts,cards=cards,lessons=learned,limits=limits,
        experiment_window='7天',origin='本地规则建议（待验证，不是因果结论）')


def apply_model_draft(brief,text):
    """Model may propose hypotheses; observed facts and source IDs remain code-owned."""
    text=text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
    obj=json.loads(text)
    cards=obj.get('cards') if isinstance(obj,dict) else None
    if not isinstance(cards,list) or len(cards)!=5:raise ValueError('模型需要返回完整的五类建议')
    allowed={e['id'] for e in brief['evidence']};seen=set();clean=[]
    for c in cards:
        if not isinstance(c,dict) or c.get('kind') not in KINDS or c['kind'] in seen:raise ValueError('模型建议分类不完整或重复')
        refs=c.get('evidence_ids')
        if not isinstance(refs,list) or not refs or not all(isinstance(i,str) and i in allowed for i in refs):
            raise ValueError('模型引用了不存在的证据，未保存这次输出')
        for k in ('change','hypothesis'):
            if not isinstance(c.get(k),str) or not c[k].strip() or len(c[k])>1500:raise ValueError('模型建议字段无效')
            if re.search(r'必爆|保证.{0,8}增长|全站.{0,8}(排名|超过)|证明.{0,8}因果',c[k]):
                raise ValueError('模型包含无法支持的保证或全站结论，未采用')
        clean.append({k:c[k] for k in ('kind','change','hypothesis','evidence_ids')});seen.add(c['kind'])
    out=dict(brief,cards=sorted(clean,key=lambda c:KINDS.index(c['kind'])),origin='模型提出的待验证假设；观察事实仍来自本地证据')
    return out


def save_plan(db,brief):
    with connect(db) as con:
        owner=con.execute('SELECT account_id FROM hub_posts WHERE id=?',(brief['target_id'],)).fetchone()
    if not owner or owner['account_id']!=brief['account_id']:raise ValueError('方案作品不属于当前账号')
    payload=dict(brief)
    payload['evidence_hash']=hashlib.sha256(json.dumps(brief['evidence'],ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    key=uuid.uuid4().hex
    put(db,'plan',brief['account_id'],brief['platform'],key,payload)
    return key


def plan_experiment(db,aid,platform,plan_key,kind):
    from creatorlab.growth import save_experiment
    plan=get(db,'plan',aid,platform,plan_key)
    if not plan:raise ValueError('方案不存在或不属于当前账号')
    with connect(db) as con:
        target=con.execute('SELECT account_id FROM hub_posts WHERE id=?',(plan['target_id'],)).fetchone()
    if not target or target['account_id']!=aid:raise ValueError('方案中的作品已不存在，请重新选择作品生成方案')
    card=next((c for c in plan['cards'] if c['kind']==kind),None)
    if not card:raise ValueError('请选择方案中的一种改动')
    title='方案'+plan_key+' · '+kind
    with connect(db) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clab_experiments'").fetchone()
        old=con.execute('SELECT id FROM clab_experiments WHERE account_id=? AND title=?',(aid,title)).fetchone() if exists else None
    if old:return old['id']
    eid=save_experiment(db,aid,title,card['hypothesis']+'；实际改动：'+card['change'],plan['metric'])
    from creatorlab.learning_workflow import experiment_detail
    from creatorlab.review import NAMES
    detail=experiment_detail(db,aid,platform,eid)
    window=card.get('window') or plan['experiment_window']
    detail.update(source_plan=plan_key,kind=kind,goal=window+' '+NAMES.get(plan['metric'],plan['metric']),change=card['change'],suggested_window=window,
                  evidence_ids=card['evidence_ids'],evidence_hash=plan['evidence_hash'])
    put(db,'experiment_detail',aid,platform,eid,detail)
    return eid
