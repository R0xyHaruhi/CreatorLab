"""Descriptive comparisons: counts, rates and reference positions stay separate."""
import math
import pandas as pd
from creatorlab.hub import eligible, sort_posts
from creatorlab.platforms import COMMON, EXTRAS

RATIOS={'like_ratio':'likes','comment_ratio':'comments','favorite_ratio':'favorites',
        'share_ratio':'shares','coin_ratio':'coins','danmaku_ratio':'danmaku'}
RATIO_LABELS={'like_ratio':'点赞 / 播放','comment_ratio':'评论 / 播放','favorite_ratio':'收藏 / 播放',
              'share_ratio':'分享 / 播放','coin_ratio':'投币 / 播放','danmaku_ratio':'弹幕 / 播放'}


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def metric_value(row, metric):
    if metric in ('image_depth','image_count','avg_image_views','swipe_away_rate','text_expand_rate'):
        from creatorlab.image_reading import value
        return value(row,metric)
    if metric in RATIOS:
        numerator=RATIOS[metric];views=row.get('views');value=row.get(numerator)
        if not finite(views) or views<=0 or not finite(value) or not row.get('_ratio_allowed',{}).get(numerator,True):return None
        return value/views
    if row.get('media_format')=='image' and metric in ('completion_rate','completion_rate_5s','bounce_rate_2s','avg_view_second'):return None
    value=row.get(metric)
    return value if finite(value) else None


def metrics(platform):
    count=[(key,label,'count') for key,label in COMMON+EXTRAS[platform] if key not in ('completion_rate','completion_rate_5s','bounce_rate_2s','avg_view_second')]
    rates=[(key,label,'rate') for key,label in RATIO_LABELS.items() if platform=='bilibili' or key not in ('coin_ratio','danmaku_ratio')]
    extra=[(key,label,'seconds' if key=='avg_view_second' else 'rate') for key,label in EXTRAS[platform] if key in ('completion_rate','completion_rate_5s','bounce_rate_2s','avg_view_second')]
    image=[('image_count','图片总数','count'),('avg_image_views','平均浏览图片数','images'),('image_depth','阅读深度指数','rate'),('swipe_away_rate','图文划走率','rate'),('text_expand_rate','文案展开率','rate')] if platform=='douyin' else []
    return count+rates+extra+image


def comparison_table(rows):
    if not rows:return []
    if len({r['platform'] for r in rows})!=1:raise ValueError('请在同一平台内对比作品；跨平台版本请使用内容关联。')
    return [dict(metric=key,label=label,unit=unit,values=[metric_value(r,key) for r in rows]) for key,label,unit in metrics(rows[0]['platform'])]


def cohort(rows, target, published_range=None, scope='all'):
    """All valid history by default; track/date filters require an explicit choice."""
    from creatorlab.own_scope import references
    result=[]
    for row in references(rows,target,scope):
        if row.get('demo'):continue
        if published_range:
            at=pd.to_datetime(row.get('published_at'),utc=True,errors='coerce')
            if pd.isna(at) or not published_range[0]<=at.date()<=published_range[1]:continue
        result.append(row)
    return result


def positions(rows, target, published_range=None, scope='all'):
    refs=cohort(rows,target,published_range,scope)
    result=[]
    valid_target=bool(eligible([target])) and not target.get('demo')
    for key,label,unit in metrics(target['platform']):
        value=metric_value(target,key)
        values=[v for r in refs if (v:=metric_value(r,key)) is not None]
        # A lower bounce rate is desirable, but this is explicitly a numeric position.
        percent=100*sum(v<value for v in values)/len(values) if valid_target and value is not None and len(values)>=3 else None
        result.append(dict(metric=key,label=label,unit=unit,value=value,n=len(values),percent=percent))
    return result


def filter_library(rows, search='', account_id=None, state='全部', order='最新发布', days=None, now=None):
    from creatorlab.hub import quality
    result=[r for r in rows if (account_id is None or r['account_id']==account_id)
            and (state=='全部' or quality(r)==state)
            and search.casefold() in (str(r.get('title') or '')+' '+str(r.get('external_id') or '')).casefold()]
    if days:
        now=now or pd.Timestamp.now(tz='UTC');cutoff=now-pd.Timedelta(days=days)
        result=[r for r in result if pd.notna(at:=pd.to_datetime(r.get('published_at'),utc=True,errors='coerce')) and cutoff<=at<=now]
    if order in ('最新发布','最早发布'):
        dated=[(pd.to_datetime(r.get('published_at'),utc=True,errors='coerce'),r) for r in result]
        known=[(at,r) for at,r in dated if pd.notna(at)]
        return [r for _,r in sorted(known,key=lambda pair:(pair[0],pair[1]['id']),reverse=order=='最新发布')]+[r for at,r in dated if pd.isna(at)]
    return sort_posts(result,order)


def safe_csv(records):
    """Neutralize spreadsheet formulas in exported user-controlled text."""
    def cell(v):
        if isinstance(v,(dict,list,tuple)):v=str(v)
        return "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
    return pd.DataFrame([{k:cell(v) for k,v in r.items() if not k.startswith('_')} for r in records]).to_csv(index=False).encode('utf-8-sig')
