"""Comparable challenge results. Creators, works and population claims stay distinct."""
import pandas as pd
from creatorlab.growth import AXES
from creatorlab.battlecard import profile_from_scores


def work_result(df,row,models):
    """Rank equal-weight composites on one identical set of axes and one cohort."""
    model=dict(models[row['id']]);keys=[s['metric'] for s in model['scores'] if s['score'] is not None]
    result=dict(ready=False,unit='同组历史作品',n=0,percent=None,tied=0)
    if len(keys)<3:return result
    from creatorlab.own_scope import scope_key
    scope=model.get('own_scope')
    if scope:
        key=scope_key(row,scope)
        cohort=df[df.apply(lambda r:scope_key(r.to_dict(),scope)==key,axis=1)]
    else:
        cohort=df[(df.account_id==row['account_id'])&(df.platform==row['platform'])&
                  (df.media_format==row['media_format'])&(df._baseline_scope==row['_baseline_scope'])]
    if scope:
        formats=set(cohort.media_format.fillna('unknown'))
        if len(formats)>1:keys=[k for k in keys if k not in ('completion_rate','image_depth','avg_image_views')]
    if len(keys)<3:return result
    if model.get('comparison')=='efficiency':cohort=cohort[cohort.views>=1000]
    matrix=cohort.set_index('id')[keys].dropna()
    if len(matrix)<3 or row['id'] not in matrix.index:return result
    composites=matrix.rank(method='average',pct=True).mean(axis=1)
    target=composites.loc[row['id']];others=composites.drop(row['id'])
    # 'Exceeds' counts strictly lower scores, never half of ties.
    return dict(ready=True,unit=('同赛道历史作品' if scope=='track' else '账号内其他有效作品') if scope else '同组历史作品',n=len(others),percent=100*int((others<target-1e-12).sum())/len(others),
                tied=int((abs(others-target)<=1e-12).sum()),axes=len(keys),score=float(target*100))


def peer_result(own,external,platform,pair,age,media='video'):
    """Each account contributes one median; prolific accounts get no extra votes.

    Require explicitly confirmed genres, equal age/window and >=3 works/account.
    Compare exactly the same >=3 axes for every account. No full-site inference.
    """
    result=dict(ready=False,unit='对标创作者样本',n=0,percent=None,reason='',accounts=[],works=0)
    def select(df):
        if df.empty:return df
        def matches(g):return isinstance(g,dict) and g.get('origin') in ('manual','platform_metadata') and (g.get('major'),g.get('minor'))==tuple(pair)
        return df[(df.platform==platform)&(df.media_format==media)&(df.age_band==age)&
                  (df._baseline_scope==age)&df.genre.map(matches)].copy() if 'genre' in df else df.iloc[:0]
    mine=select(own);theirs=select(external)
    if media=='unknown':result['reason']='先确认作品是视频还是图文，再参与同行挑战。';return result
    if mine.empty or len(mine)<3:result['reason']='这个赛道和积累区间还需要至少3条自己的公开有效作品。';return result
    own_ids=set(mine.account_id)
    if len(own_ids)!=1:result['reason']='一次只比较一个自己的账号。';return result
    if not theirs.empty:theirs=theirs[~theirs.account_id.isin(own_ids)]
    keys=[key for _,key in AXES[platform]]
    groups=[]
    for _,g in theirs.groupby('account_id') if not theirs.empty else []:
        if len(g)>=3:groups.append(g)
    result.update(n=len(groups),works=sum(len(g) for g in groups))
    if len(groups)<5:result['reason']=f'已找到{len(groups)}位符合范围的对标创作者，至少5位才发布样本超越比例。';return result
    all_groups=[mine,*groups]
    common=[k for k in keys if all(k in g and g[k].notna().sum()>=3 for g in all_groups)]
    if len(common)<3:result['reason']='这些账号还没有至少3个共同有效维度；缺失字段不会补零。';return result
    medians=pd.DataFrame([{k:float(g[k].median()) for k in common} for g in all_groups])
    percentiles=100*(medians.rank(method='average')-.5)/len(medians)
    composite=percentiles.mean(axis=1);target=float(composite.iloc[0]);other=composite.iloc[1:]
    scores=[dict(axis=label,metric=k,value=float(medians.iloc[0][k]) if k in common else None,
                 score=float(percentiles.iloc[0][k]) if k in common else None,n=len(groups)) for label,k in AXES[platform]]
    model=profile_from_scores(scores)
    accounts=[dict(account_id=int(g.account_id.iloc[0]),name=str(g.account_name.iloc[0]),n=len(g),
                   observed=str(g.metric_recorded_at.max()),sources=sorted(set(g.source)) if 'source' in g else []) for g in groups]
    result.update(ready=True,percent=100*int((other<target-1e-12).sum())/len(other),
                  tied=int((abs(other-target)<=1e-12).sum()),axes=len(common),score=target,model=model,accounts=accounts,
                  own_n=len(mine),works=sum(len(g) for g in groups),reason='')
    model.update(comparison='peer',overall=result['percent'],comparison_n=result['n'],comparison_axes=len(common),
                 comparison_scope=f'{pair[0]} / {pair[1]} · 发布后{age}',comparison_tied=result['tied'])
    return result
