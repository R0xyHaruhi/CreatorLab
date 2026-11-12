"""Explicit content labels and descriptive cohort comparison; no invented benchmarks."""
from statistics import median
import pandas as pd
from creatorlab.hub import connect, eligible

TRACKS=['COS / 动漫','知识科普','游戏','生活 / Vlog','美妆 / 穿搭','美食','其他']
METRICS={'播放量':'views','点赞 / 播放':'like_ratio','评论 / 播放':'comment_ratio','分享 / 播放':'share_ratio','收藏 / 播放':'favorite_ratio','完播率':'completion_rate','2秒跳出率':'bounce_rate_2s','平均观看秒数':'avg_view_second','投币 / 播放':'coin_ratio','弹幕 / 播放':'danmaku_ratio'}
TRACK_TESTS={
 'COS / 动漫':'保留同一角色、服装和音乐，测试「成片先展示」与「变装前铺垫」两种开头；记录角色/IP与表现形式，区分角色热度和剪辑形式。',
 '知识科普':'保持同一知识主题和时长区间，测试「先给结论」与「先抛问题」；用收藏/播放判断参考价值，用完播率检查解释长度。',
 '游戏':'保持游戏、模式和时长相近，测试「高光先展示」与「过程铺垫」；区分攻略、搞笑和操作高光，用收藏或分享对应内容目标。',
 '生活 / Vlog':'保持同一生活主题，测试「冲突或结果先展示」与「按时间叙述」；比较完播和评论/播放，记录是否有明确故事线。',
 '美妆 / 穿搭':'同一产品或穿搭主题，测试「效果对比先展示」与「步骤先展示」；比较收藏/播放，记录教程与成品展示的差异。',
 '美食':'同一菜品和时长区间，测试「成品/口感先展示」与「制作过程先展示」；教程看收藏/播放，探店看分享/播放。',
 '其他':'保持主题、时长和发布时间段相近，仅替换开头呈现方式；先用历史中位数确定参照，再按目标指标评估。'}


def init_content(db):
    with connect(db) as con:
        con.executescript('''CREATE TABLE IF NOT EXISTS hub_content(
          post_id INTEGER PRIMARY KEY REFERENCES hub_posts(id),
          track TEXT NOT NULL DEFAULT '未标注', category TEXT NOT NULL DEFAULT '未分类',
          topic TEXT NOT NULL DEFAULT '', duration_seconds REAL);
        CREATE TABLE IF NOT EXISTS hub_profiles(
          account_id INTEGER PRIMARY KEY REFERENCES hub_accounts(id), track TEXT NOT NULL);''')


def annotate(db,post_id,track,category,topic='',duration_seconds=None):
    if duration_seconds is not None and (not 0<float(duration_seconds)<=86400):raise ValueError('时长需要在 0–86400 秒之间')
    init_content(db)
    with connect(db) as con:
        con.execute('INSERT OR REPLACE INTO hub_content VALUES(?,?,?,?,?)',(post_id,str(track)[:80],str(category).strip()[:80] or '未分类',str(topic).strip()[:120],duration_seconds))


def enrich(db,rows):
    init_content(db)
    with connect(db) as con:
        annotations={r['post_id']:dict(r) for r in con.execute('SELECT * FROM hub_content')}
        profiles={r['account_id']:r['track'] for r in con.execute('SELECT * FROM hub_profiles')}
    return [dict(r,**{k:v for k,v in annotations.get(r['id'],{'track':profiles.get(r['account_id'],'未标注'),'category':'未分类','topic':'','duration_seconds':None}).items() if k!='post_id'}) for r in rows]


def frame(rows,tz='Asia/Shanghai'):
    data=[]
    for r in eligible(rows):
        x=dict(r,media_format=r.get('media_format') or 'unknown')
        if x['media_format']=='image':
            for field in ('completion_rate','completion_rate_5s','bounce_rate_2s','avg_view_proportion','avg_view_second'):x[field]=None
        for name,key in [('like_ratio','likes'),('comment_ratio','comments'),('share_ratio','shares'),('favorite_ratio','favorites'),('coin_ratio','coins'),('danmaku_ratio','danmaku')]:
            x[name]=None if r.get(key) is None or not r.get('_ratio_allowed',{}).get(key,True) else r[key]/r['views']
        from creatorlab.reporting import metric_value
        for key in ('avg_image_views','image_depth'):x[key]=metric_value(r,key)
        at=pd.to_datetime(r.get('published_at'),utc=True,errors='coerce')
        observed=pd.to_datetime(r.get('metric_recorded_at'),utc=True,errors='coerce')
        x['age_days']=(observed-at).total_seconds()/86400 if pd.notna(at) and pd.notna(observed) else None
        age=x['age_days']
        x['age_band']='未知' if age is None or age<0 else '0–6天' if age<7 else '7–29天' if age<30 else '30–89天' if age<90 else '90天以上'
        x['publish_hour']=str(at.tz_convert(tz).hour//4*4).zfill(2)+'–'+str(at.tz_convert(tz).hour//4*4+3).zfill(2)+'时' if pd.notna(at) else '未知'
        duration=r.get('duration_seconds')
        x['duration_band']='未知' if not duration else '≤15秒' if duration<=15 else '16–30秒' if duration<=30 else '31–60秒' if duration<=60 else '>60秒'
        x.setdefault('category','未分类');x.setdefault('track','未标注');x.setdefault('topic','')
        x['_baseline_scope']=r.get('analysis_window') if r.get('analysis_window') and r.get('analysis_window')!='当前累计' else x['age_band']
        data.append(x)
    df=pd.DataFrame(data)
    if not df.empty:
        # A transparent descriptive normalization, not a causal effect estimate.
        group=df.groupby(['account_id','platform','_baseline_scope','media_format'])['views']
        df['baseline_n']=group.transform('size')
        df['relative_views']=df['views']/group.transform('median')
    return df


def group_summary(df,dimension,metric):
    if df.empty:return pd.DataFrame()
    return df.groupby(dimension,dropna=False)[metric].agg(n='count',median='median',q1=lambda s:s.quantile(.25),q3=lambda s:s.quantile(.75)).reset_index()


def recommendations(df,track,metric,min_n=5):
    """Only compare classified groups; every suggestion includes sample counts."""
    if df.empty:return []
    known=df[(df['track']==track)&(df['category']!='未分类')]
    out=[]
    # Never pool accounts/platforms for a claim about content effectiveness.
    for (aid,platform,age,media),cohort in known.groupby(['account_id','platform','age_band','media_format']):
        if age=='未知':continue
        stats=group_summary(cohort,'category',metric).dropna(subset=['median'])
        stats=stats[stats.n>=min_n].sort_values('median',ascending=metric!='bounce_rate_2s')
        if len(stats)<2:continue
        best,worst=stats.iloc[-1],stats.iloc[0]
        # For lower-is-better metrics order above is reversed by ascending=False.
        if best['median']==worst['median']:continue
        out.append({'title':f'优先验证「{best["category"]}」的可复用性',
            'evidence':f'{platform} / 账号 {aid} / 发布至采集 {age} / 体裁 {media}；{best["category"]} n={best["n"]}、中位数={best["median"]:.4g}；{worst["category"]} n={worst["n"]}、中位数={worst["median"]:.4g}。指标：{metric}。',
            'test':TRACK_TESTS.get(track,TRACK_TESTS['其他'])+f' 先为「{best["category"]}」安排 3 条验证作品，分别记录发布后第7天同一指标；与原分类比较时同时记录主题、时长、投流和热点变化。',
            'limits':'这是同账号、同平台、同作品年龄区间的描述差异；未控制题材热度、投流和观众差异，不能推断因果。'})
    return out
