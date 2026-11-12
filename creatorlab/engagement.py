"""Explain exposure and like conversion separately, with an explicit baseline."""
from statistics import median
from creatorlab.reporting import metric_value
from creatorlab.own_scope import references
from creatorlab.hub import eligible


AXIS_NAMES={'触达':'播放触达','喜欢':'点赞','讨论':'评论','收藏':'收藏','传播':'分享','投币支持':'投币','留住观众':'完播','阅读深度':'图文阅读深度'}


def like_diagnosis(rows,target,min_views=1000,min_refs=3,scope='all'):
    views=metric_value(target,'views');likes=metric_value(target,'likes');rate=metric_value(target,'like_ratio')
    result=dict(views=views,likes=likes,rate=rate,n=0,min_views=min_views,median_rate=None,median_views=None,
                relative=None,state='missing',message='缺少可比的播放或点赞观测，暂不判断点赞转化。')
    if not eligible([target]) or rate is None:return result
    if views<min_views:
        result.update(state='small',message=f'当前播放不足{min_views}，点赞率波动较大，暂不判断转化强弱。');return result
    refs=[]
    for row in references(rows,target,scope):
        value=metric_value(row,'like_ratio');plays=metric_value(row,'views')
        if value is not None and plays is not None and plays>=min_views:refs.append((plays,value))
    result['n']=len(refs)
    if len(refs)<min_refs:
        result.update(state='insufficient',message=f'同组至少需要{min_refs}条播放不少于{min_views}的其他作品，暂不判断点赞转化高低。');return result
    typical=median(v for _,v in refs);typical_views=median(v for v,_ in refs)
    result.update(median_rate=typical,median_views=typical_views,relative=rate/typical if typical>0 else None)
    if rate<typical and views>=typical_views:
        result.update(state='reach_like_gap',message='播放规模高于或达到同组典型水平，但点赞转化低于同组中位数。')
    elif rate<typical:result.update(state='low_conversion',message='点赞转化低于同组中位数，播放规模与转化需要分开复盘。')
    else:result.update(state='at_or_above',message='点赞转化达到或高于同组中位数；这不等于内容质量评级。')
    return result


def attach_context(model,alternate,diagnosis):
    model=dict(model,diagnosis=diagnosis)
    if alternate and alternate['ready']:model['dual_scores']=alternate['scores']
    if diagnosis['state']=='reach_like_gap':
        model['archetype']='播放较高 · 点赞转化偏低'
        model['next_test']='下一条保留题材与时长，只调整开头对价值点的呈现，同时观察播放、点赞率和完播率。'
    return model


def axis_value(item):
    from creatorlab.hub import fmt_count
    value=item.get('value');key=item['metric']
    if item.get('status')=='not_applicable':return '不适用（图文）'
    if value is None:return '—'
    if key.endswith('_ratio') or key in ('image_depth','swipe_away_rate','text_expand_rate','completion_rate','bounce_rate_2s','completion_rate_5s'):
        return '<0.01%' if 0<value<.0001 else f'{value:.2%}'
    if key=='avg_image_views':return f'{value:g}张'
    return fmt_count(value)
