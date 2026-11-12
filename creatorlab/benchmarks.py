"""Local, auditable peer matching. No scraping, fake metrics, or invented accounts."""
import math
import sqlite3
from datetime import date, datetime, timezone
from .storage import connection

SCHEMA = '''
CREATE TABLE IF NOT EXISTS benchmark_accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 platform TEXT NOT NULL CHECK(platform IN ('douyin','tiktok')),
 handle TEXT NOT NULL,
 account_url TEXT NOT NULL DEFAULT '',
 niche TEXT NOT NULL DEFAULT 'COS/二次元',
 tags TEXT NOT NULL DEFAULT '',
 followers INTEGER CHECK(followers >= 0),
 median_views INTEGER CHECK(median_views >= 0),
 engagement_rate REAL CHECK(engagement_rate >= 0 AND engagement_rate <= 1),
 posts_30d INTEGER CHECK(posts_30d >= 0),
 growth_30d REAL,
 source_type TEXT NOT NULL CHECK(source_type IN ('manual','authorized','public_verified','demo')),
 source_note TEXT NOT NULL DEFAULT '',
 observed_at TEXT NOT NULL,
 is_demo INTEGER NOT NULL DEFAULT 0 CHECK(is_demo IN (0,1)),
 UNIQUE(platform,handle)
);
'''
VALID_SOURCES = {'manual','authorized','public_verified','demo'}

def init_benchmarks(path):
    with connection(path) as con: con.executescript(SCHEMA)

def save_account(path, data):
    init_benchmarks(path)
    platform = data.get('platform','douyin')
    if platform not in ('douyin','tiktok'): raise ValueError('不支持的平台')
    handle = str(data.get('handle','')).strip()
    if not handle: raise ValueError('请填写账号名称')
    source = data.get('source_type','manual')
    if source not in VALID_SOURCES: raise ValueError('无效数据来源')
    vals = [platform,handle,str(data.get('account_url') or ''),str(data.get('niche') or 'COS/二次元'),
            str(data.get('tags') or ''),data.get('followers'),data.get('median_views'),
            data.get('engagement_rate'),data.get('posts_30d'),data.get('growth_30d'),
            source,str(data.get('source_note') or ''),str(data.get('observed_at') or date.today().isoformat()),int(source=='demo')]
    if any(v is not None and (not isinstance(v,int) or v<0) for v in (vals[5],vals[6],vals[8])):
        raise ValueError('粉丝、播放和发布数量必须为非负整数')
    if vals[7] is not None and not 0<=vals[7]<=1: raise ValueError('互动率必须在 0% 到 100% 之间')
    with connection(path) as con:
        con.execute('''INSERT INTO benchmark_accounts
        (platform,handle,account_url,niche,tags,followers,median_views,engagement_rate,posts_30d,growth_30d,source_type,source_note,observed_at,is_demo)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(platform,handle) DO UPDATE SET
        account_url=excluded.account_url,niche=excluded.niche,tags=excluded.tags,followers=excluded.followers,
        median_views=excluded.median_views,engagement_rate=excluded.engagement_rate,posts_30d=excluded.posts_30d,
        growth_30d=excluded.growth_30d,source_type=excluded.source_type,source_note=excluded.source_note,
        observed_at=excluded.observed_at,is_demo=excluded.is_demo''',vals)

def list_accounts(path,platform='douyin',include_demo=False):
    init_benchmarks(path)
    with connection(path) as con:
        q='SELECT * FROM benchmark_accounts WHERE platform=?'
        if not include_demo:q+=' AND is_demo=0'
        return [dict(r) for r in con.execute(q+' ORDER BY handle',(platform,))]

def delete_account(path,account_id):
    init_benchmarks(path)
    with connection(path) as con:
        return con.execute('DELETE FROM benchmark_accounts WHERE id=?',(account_id,)).rowcount>0

def _similarity(a,b):
    if a is None or b is None:return None
    return math.exp(-abs(math.log1p(a)-math.log1p(b)))

def _tags(text):
    return {x.strip().lower() for x in str(text or '').replace('，',',').split(',') if x.strip()}

def match_peers(target, candidates, mode='both', limit=10, today=None):
    """Score 0..100 with missing-value-aware weighted average; missing data never becomes zero."""
    today=today or date.today()
    results=[]
    for a in candidates:
        if a.get('platform') != target.get('platform','douyin'):continue
        if a.get('handle','').strip().casefold()==str(target.get('handle','')).strip().casefold():continue
        if bool(a.get('is_demo')) != bool(target.get('is_demo')):continue
        ttags,atags=_tags(target.get('tags')),_tags(a.get('tags'))
        niche=1.0 if str(a.get('niche','')).strip().casefold()==str(target.get('niche','')).strip().casefold() else 0.0
        tag_sim=(len(ttags&atags)/len(ttags|atags)) if ttags and atags else None
        content=(0.65*niche+0.35*tag_sim) if tag_sim is not None else niche
        scale=_similarity(target.get('followers'),a.get('followers'))
        if mode=='similar' and scale is not None and scale<0.12:continue
        metrics={'内容赛道':(content,0.35),'账号规模':(scale,0.20),
                 '播放表现':(_similarity(target.get('median_views'),a.get('median_views')),0.10),
                 '互动表现':(min(a['engagement_rate']/max(target.get('engagement_rate') or 0.03,0.005),2)/2 if a.get('engagement_rate') is not None else None,0.15),
                 '更新活跃度':(min(a['posts_30d']/12,1) if a.get('posts_30d') is not None else None,0.10),
                 '近期增长':(min(max(a['growth_30d'],0)/0.15,1) if a.get('growth_30d') is not None else None,0.10)}
        available={k:(v,w) for k,(v,w) in metrics.items() if v is not None}
        score=100*sum(v*w for v,w in available.values())/sum(w for _,w in available.values())
        completeness=sum(w for _,w in available.values())
        try: age=(today-date.fromisoformat(str(a['observed_at'])[:10])).days
        except (ValueError,TypeError):age=999
        freshness=1.0 if 0<=age<=30 else 0.7 if age<=90 and age>=0 else 0.3
        source_quality={'authorized':1.0,'public_verified':0.85,'manual':0.65,'demo':0.0}.get(a.get('source_type'),0.4)
        confidence=round(100*completeness*freshness*source_quality)
        label='较高' if confidence>=70 else '一般' if confidence>=40 else '较低'
        segment='同量级' if scale is not None and scale>=0.35 else '头部参考' if (a.get('followers') or 0)> (target.get('followers') or 0)*3 and target.get('followers') is not None else '其他参考'
        if mode=='similar' and segment!='同量级':continue
        if mode=='leaders' and segment!='头部参考':continue
        results.append({**a,'match_score':round(score,1),'confidence':confidence,'confidence_label':label,
                        'segment':segment,'reasons':', '.join(f'{k} {v:.0%}' for k,(v,w) in available.items()),
                        'missing':', '.join(k for k,(v,w) in metrics.items() if v is None) or '无'})
    return sorted(results,key=lambda r:(r['match_score'],r['confidence']),reverse=True)[:limit]
