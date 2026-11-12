"""Human-readable, auditable observations from comparable historical works."""
from creatorlab.content_analysis import group_summary

GOALS={
 '找到值得继续做的内容':('views','播放量','更高通常更好'),
 '让观众多看一会儿':('completion_rate','完播率','越高越好'),
 '让观众更愿意分享':('share_ratio','分享比例','越高越好'),
 '让观众更愿意收藏':('favorite_ratio','收藏比例','越高越好'),
 '让观众更愿意投币':('coin_ratio','投币比例','越高越好'),
 '让观众更愿意点赞':('like_ratio','点赞比例','越高越好'),
}
NAMES={'views':'播放量','completion_rate':'完播率','bounce_rate_2s':'2秒离开比例','avg_view_second':'平均观看时长',
       'like_ratio':'点赞比例','share_ratio':'分享比例','favorite_ratio':'收藏比例','comment_ratio':'评论比例','coin_ratio':'投币比例','danmaku_ratio':'弹幕比例'}
RATIO={k for k in NAMES if k.endswith('_ratio') or k in ('completion_rate','bounce_rate_2s')}


def display(value,metric):
    import math
    if value is None or not math.isfinite(float(value)):return '暂无数据'
    value=float(value)
    if metric in RATIO:return f'{value*100:.1f}%'
    if metric=='avg_view_second':return f'{value:.1f}秒'
    if value>=10000:return f'{value/10000:.2f}万'
    return f'{value:,.0f}'


def comparison_cohort(df,metric):
    """Use the largest observed same-account/platform/age cohort with >=3 valid rows."""
    if df.empty or metric not in df:return df.iloc[:0]
    fixed='analysis_window' in df and df.analysis_window.nunique()==1 and df.analysis_window.iloc[0]!='当前累计'
    known=(df if fixed else df[df.age_band.isin(['7–29天','30–89天','90天以上'])]).dropna(subset=[metric])
    groups=[g for _,g in known.groupby(['account_id','platform','analysis_window' if fixed else 'age_band']) if len(g)>=3]
    return max(groups,key=len) if groups else df.iloc[:0]


def pattern_findings(df,metric,min_n=5):
    if df.empty or metric not in df:return []
    findings=[]
    classified=df[df.category.notna() & ~df.category.isin(['未分类',''])]
    fixed='analysis_window' in df and df.analysis_window.nunique()==1 and df.analysis_window.iloc[0]!='当前累计'
    for (aid,platform,age,track),cohort in classified.groupby(['account_id','platform','analysis_window' if fixed else 'age_band','track']):
        if not fixed and age not in ('7–29天','30–89天','90天以上'):continue
        stats=group_summary(cohort.dropna(subset=[metric]),'category',metric)
        if stats.empty:continue
        stats=stats[stats.n>=min_n].sort_values('median',ascending=metric!='bounce_rate_2s')
        if len(stats)<2:continue
        best,other=stats.iloc[-1],stats.iloc[0]
        if best['median']==other['median']:continue
        findings.append({'category':best['category'],'other':other['category'],'value':float(best['median']),
          'other_value':float(other['median']),'n':int(best['n']),'other_n':int(other['n']),
          'age':age,'platform':platform,'track':track,'account_id':aid,'metric':metric})
    return sorted(findings,key=lambda f:f['n']+f['other_n'],reverse=True)


def representative_pair(df,metric):
    cohort=comparison_cohort(df,metric)
    if len(cohort)<3:return None
    ordered=cohort.sort_values(metric,ascending=metric!='bounce_rate_2s')
    best=ordered.iloc[-1]
    others=ordered[ordered.id!=best.id].copy()
    others['distance']=(others[metric]-cohort[metric].median()).abs()
    other=others.sort_values('distance').iloc[0]
    if best[metric]==other[metric]:return None
    return best.to_dict(),other.to_dict(),len(cohort)


def hook_observation(df):
    if df.empty or 'bounce_rate_2s' not in df:return None
    cohort=comparison_cohort(df,'bounce_rate_2s')
    if len(cohort)<5:return None
    typical=float(cohort.bounce_rate_2s.median());candidate=cohort.loc[cohort.bounce_rate_2s.idxmax()]
    if candidate.bounce_rate_2s<=typical:return None
    return {'row':candidate.to_dict(),'typical':typical,'gap':float(candidate.bounce_rate_2s-typical),'n':len(cohort)}
