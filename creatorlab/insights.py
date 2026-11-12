"""Evidence-first, platform-aware descriptive diagnostics; missing metrics stay missing."""
from collections import Counter
from datetime import datetime
from statistics import median

COUNTS = ('views','likes','comments','shares','favorites')
RATES = ('completion_rate','completion_rate_5s','bounce_rate_2s','avg_view_proportion')
LABELS = {'views':'播放量','likes':'点赞量','comments':'评论量','shares':'分享量',
          'favorites':'收藏量','completion_rate':'完播率','completion_rate_5s':'5秒留存指标',
          'bounce_rate_2s':'2秒跳出率','avg_view_proportion':'平均观看比例',
          'avg_view_second':'平均观看时长'}

def valid(rows, metric):
    return [r for r in rows if r.get(metric) is not None and not isinstance(r.get(metric),bool)]

def rate_for(row, metric):
    views=row.get('views')
    count=row.get(metric)
    if not views or count is None or views < 0 or count < 0: return None
    return count / views

def describe(rows, metric):
    vals=[float(r[metric]) for r in valid(rows, metric)]
    if not vals:return {'n':0,'median':None,'mean':None,'q1':None,'q3':None,'min':None,'max':None}
    vals.sort()
    def quantile(p):
        pos=p*(len(vals)-1); low=int(pos); frac=pos-low
        return vals[low]*(1-frac)+vals[min(low+1,len(vals)-1)]*frac
    return {'n':len(vals),'median':median(vals),'mean':sum(vals)/len(vals),
            'q1':quantile(.25),'q3':quantile(.75),'min':vals[0],'max':vals[-1]}

def completeness(rows):
    return {key:{'present':len(valid(rows,key)),'total':len(rows)} for key in (*COUNTS,*RATES,'avg_view_second')}

def leaderboard(rows,metric,high=True,limit=10,min_views=0):
    found=[r for r in valid(rows,metric) if min_views<= (r.get('views') or 0)]
    return sorted(found,key=lambda r:(float(r[metric]),r.get('id',0)),reverse=high)[:limit]

def outliers(rows):
    d=describe(rows,'views')
    if d['n']<8:return []
    iqr=d['q3']-d['q1']
    cutoff=d['q3']+1.5*iqr
    return [r for r in valid(rows,'views') if r['views']>cutoff]

def actions(rows, platform='all'):
    """Return only auditable observations and test ideas, never causal certainty."""
    results=[]
    count=len(rows)
    if not count:
        return [{'level':'info','title':'尚无作品数据','detail':'导入自己的作品后，才能生成基于证据的诊断。','evidence':'0 条作品'}]
    coverage=completeness(rows)
    missing=[LABELS[k] for k in ('views','completion_rate','bounce_rate_2s','avg_view_second') if coverage[k]['present']==0]
    if missing:
        results.append({'level':'info','title':'先完善关键数据来源',
          'detail':'缺少 '+ '、'.join(missing)+'，相应分析将自动隐藏；优先尝试创作者中心批量同步。',
          'evidence':f'已入库 {count} 条作品；不推算缺失值'})
    d=describe(rows,'views')
    if d['n']>=8:
        out=outliers(rows)
        if out:
            titles='；'.join(r['title'][:25] for r in sorted(out,key=lambda x:x['views'],reverse=True)[:3])
            results.append({'level':'opportunity','title':'出现显著高播放作品',
             'detail':'重点回看这些作品的选题、前3秒及发布形式，设计下一条可验证的复用实验；不能仅凭播放判断原因。',
             'evidence':f'高于 Q3 + 1.5×IQR 的作品 {len(out)} 条：{titles}'})
        results.append({'level':'insight','title':'用中位数判断日常表现',
          'detail':'均值容易被爆款拉高。选出低于第25百分位的作品，比较它们的选题与结构。',
          'evidence':f'有效播放记录 {d["n"]} 条；中位数 {d["median"]:,.0f}；Q1 {d["q1"]:,.0f}；Q3 {d["q3"]:,.0f}'})
    elif d['n']:
        results.append({'level':'info','title':'播放样本暂时偏少',
         'detail':'当前可以查看作品明细，但暂时不判断内容模式；建议积累至少 8 条有播放量的作品。',
         'evidence':f'播放量有效记录 {d["n"]} 条'})
    if platform in ('douyin','all'):
        retention=[r for r in rows if r.get('platform')=='douyin' and r.get('bounce_rate_2s') is not None]
        if len(retention)>=5:
            b=median(r['bounce_rate_2s'] for r in retention)
            high=sorted(retention,key=lambda r:r['bounce_rate_2s'],reverse=True)[:3]
            results.append({'level':'experiment','title':'优先测试开头吸引力',
             'detail':'挑出2秒跳出率相对较高的作品，制作新开头版本，并对比相近发布天数的数据。这里只能说明相对差异，不能断定流失原因。',
             'evidence':f'抖音 {len(retention)} 条记录；2秒跳出率中位数 {b*100:.1f}%；优先复盘：'+ '、'.join(r['title'][:18] for r in high)})
    interact=[r for r in rows if rate_for(r,'likes') is not None]
    if len(interact)>=5:
        high=sorted(interact,key=lambda r:rate_for(r,'likes'),reverse=True)[:3]
        results.append({'level':'experiment','title':'复盘高互动作品',
          'detail':'观察点赞/播放比最高的作品是否存在相似的表现形式，避免用不同平台之间的比值直接判断内容优劣。',
          'evidence':f'具备播放和点赞数据的作品 {len(interact)} 条；领先作品：'+ '、'.join(r['title'][:18] for r in high)})
    return results

def match_candidates(rows):
    """Conservative suggestions only: exact normalized titles across platforms; no auto-binding."""
    import re
    groups={}
    for r in rows:
        title=re.sub(r'[^\w\u4e00-\u9fff]','',str(r.get('title') or '').lower())
        if len(title)<5: continue
        groups.setdefault(title,[]).append(r)
    return [g for g in groups.values() if len({r['platform'] for r in g})>1 and any(r.get('project_id') is None for r in g)]
