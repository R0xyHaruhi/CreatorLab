"""Account observations and creator overview are separate from per-video metrics."""
import json
import re
from urllib.parse import urlparse,parse_qs
from creatorlab.hub import connect,add_account,utcnow

ACCOUNT_PATHS={'/x/relation/stat','/x/space/upstat','/x/web-interface/card','/x/space/wbi/acc/info','/x/space/acc/info'}
ACCOUNT_LABELS={'followers':'粉丝量','following':'关注数','total_likes':'累计获赞','archive_views':'视频累计播放','article_views':'专栏累计阅读','video_count':'公开投稿数','article_count':'专栏数'}
OVERVIEW_LABELS={'views':'播放量','comments':'评论','danmaku':'弹幕','likes':'点赞','shares':'分享','favorites':'收藏','coins':'投币'}


def init_account_metrics(db):
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS hub_account_observations(
          id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES hub_accounts(id),
          dataset TEXT NOT NULL, recorded_at TEXT NOT NULL, source TEXT NOT NULL,
          scope TEXT NOT NULL, data_date TEXT, metrics_json TEXT NOT NULL)''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_account_observations ON hub_account_observations(account_id,id DESC)')


def save_observation(db,uid,dataset,metrics,source,scope,data_date=None):
    from creatorlab.bilibili_import import count
    clean={k:count(v) for k,v in metrics.items() if k in (ACCOUNT_LABELS if dataset=='account' else OVERVIEW_LABELS)}
    clean={k:v for k,v in clean.items() if v is not None}
    if not clean:return False
    init_account_metrics(db)
    with connect(db) as con:
        row=con.execute("SELECT id FROM hub_accounts WHERE platform='bilibili' AND handle=?",(uid,)).fetchone()
    aid=row['id'] if row else add_account(db,'bilibili',uid,'B站 · '+uid)
    encoded=json.dumps(clean,ensure_ascii=False,sort_keys=True)
    with connect(db) as con:
        old=con.execute('SELECT * FROM hub_account_observations WHERE account_id=? AND dataset=? AND source=? ORDER BY id DESC LIMIT 1',(aid,dataset,source)).fetchone()
        if old and old['metrics_json']==encoded and old['data_date']==data_date:return False
        con.execute('INSERT INTO hub_account_observations(account_id,dataset,recorded_at,source,scope,data_date,metrics_json) VALUES(?,?,?,?,?,?,?)',(aid,dataset,utcnow(),source,scope,data_date,encoded))
    return True


def observations(db,aid,dataset='account'):
    init_account_metrics(db)
    with connect(db) as con:rows=[dict(r) for r in con.execute('SELECT * FROM hub_account_observations WHERE account_id=? AND dataset=? ORDER BY id DESC',(aid,dataset))]
    for row in rows:row['metrics']=json.loads(row.pop('metrics_json'))
    return rows


def latest_fields(db,aid):
    result={}
    for row in observations(db,aid):
        for key,value in row['metrics'].items():
            result.setdefault(key,dict(value=value,recorded_at=row['recorded_at'],source=row['source']))
    return result


def parse_account_response(url,raw,uid):
    from creatorlab.bilibili_import import count
    p=urlparse(url);q=parse_qs(p.query)
    if p.scheme!='https' or p.hostname!='api.bilibili.com' or p.path not in ACCOUNT_PATHS:return None
    if (q.get('vmid') or q.get('mid'))!=[str(uid)]:return None
    try:obj=json.loads(raw)
    except (ValueError,TypeError):return None
    if not isinstance(obj,dict) or obj.get('code')!=0 or not isinstance(obj.get('data'),dict):return None
    d=obj['data'];metrics={}
    if p.path=='/x/relation/stat':
        if str(d.get('mid'))!=str(uid):return None
        metrics={'followers':d.get('follower'),'following':d.get('following')}
    elif p.path=='/x/space/upstat':
        metrics={'total_likes':d.get('likes'),'archive_views':(d.get('archive') or {}).get('view'),'article_views':(d.get('article') or {}).get('view')}
    elif p.path=='/x/web-interface/card':
        card=d.get('card') or {}
        if str(card.get('mid'))!=str(uid):return None
        metrics={'followers':d.get('follower',card.get('fans')),'following':card.get('friend'),'video_count':d.get('archive_count'),'article_count':d.get('article_count'),'total_likes':d.get('like_num')}
    else:
        if str(d.get('mid'))!=str(uid):return None
    return {k:count(v) for k,v in metrics.items() if count(v) is not None}


def capture_creator_overview(db,uid,verified_uid,captured):
    from datetime import date
    from creatorlab.bilibili_import import count
    if str(verified_uid)!=str(uid) or not isinstance(captured,dict):return False
    try:date.fromisoformat(captured.get('data_date',''))
    except (ValueError,TypeError):return False
    raw=captured.get('metrics')
    if not isinstance(raw,dict):return False
    clean={k:count(v) for k,v in raw.items() if k in OVERVIEW_LABELS and count(v) is not None}
    if len(clean)<3:return False
    save_observation(db,uid,'creator_video_overview',clean,'创作中心可见视频数据','页面视频概览；未自动确认统计起始日',captured['data_date'])
    return True


# Only short, unambiguous label/value blocks are read; no rounded 1.2万 inference.
OVERVIEW_DOM=r'''() => {
 const labels={'播放量':'views','评论':'comments','弹幕':'danmaku','点赞':'likes','分享':'shares','收藏':'favorites','投币':'coins'};
 const body=document.body.innerText||'';
 const date=body.match(/统计截至[：:\s]*(\d{4}-\d{2}-\d{2})/);
 if(!date||!body.includes('视频数据'))return null;
 const matches={};
 for(const el of document.querySelectorAll('span,p,div')){
   const name=(el.innerText||'').trim();if(!labels[name])continue;
   let parent=el.parentElement;
   for(let depth=0;parent&&depth<3;parent=parent.parentElement,depth++){
     const text=(parent.innerText||'').trim();if(text.length>120)break;
     const lines=text.split(/\n/).map(x=>x.trim()).filter(Boolean);
     const numbers=lines.filter(x=>/^\d[\d,，]*$/.test(x));
     if(numbers.length===1){(matches[labels[name]]??=new Set()).add(numbers[0].replace(/[,，]/g,''));break;}
   }
 }
 const metrics={};for(const [key,values] of Object.entries(matches))if(values.size===1)metrics[key]=Number([...values][0]);
 return {data_date:date[1],metrics};
}'''


def account_dashboard(db,accounts):
    import pandas as pd
    import plotly.express as px
    import streamlit as st
    from creatorlab.hub import fmt_count
    from creatorlab.appearance import chart
    bili=[a for a in accounts if a['platform']=='bilibili']
    if not bili:return
    st.markdown('### 📺 B站账号数据')
    aid=st.selectbox('查看B站账号数据',[a['id'] for a in bili],format_func=lambda i:next(a['display_name'] for a in bili if a['id']==i),key='bili_account_stats')
    values=latest_fields(db,aid)
    cols=st.columns(4)
    for col,key in zip(cols,['followers','following','total_likes','archive_views']):col.metric(ACCOUNT_LABELS[key],fmt_count(values[key]['value']) if key in values else '未采集')
    if not values:st.info('重新执行B站导入可尝试采集粉丝与账号统计；尚未取得的字段不会填成0。')
    else:
        with st.expander('账号字段的来源与采集时间'):
            st.table(pd.DataFrame([{'指标':ACCOUNT_LABELS[k],'值':fmt_count(v['value']),'采集时间':v['recorded_at'],'来源':v['source']} for k,v in values.items()]))
    history=[dict(采集时间=r['recorded_at'],粉丝量=r['metrics']['followers']) for r in reversed(observations(db,aid)) if 'followers' in r['metrics']]
    if len(history)>=2:
        chart(px.line(pd.DataFrame(history),x='采集时间',y='粉丝量',markers=True),key='bili_followers_history')
        st.caption('粉丝变化只反映实际采集记录之间的差值，不补造未采集日期。')
    overview=observations(db,aid,'creator_video_overview')
    st.markdown('#### 创作中心 · 视频汇总')
    if overview:
        r=overview[0]
        st.caption(f"页面统计截至：{r['data_date'] or '未知'} · {r['scope']}")
        for start in (0,4):
            keys=list(OVERVIEW_LABELS)[start:start+4];cols=st.columns(len(keys))
            for col,key in zip(cols,keys):col.metric(OVERVIEW_LABELS[key],fmt_count(r['metrics'].get(key)))
        st.caption('来自创作中心独立汇总，不由作品库加总。页面的统计截止日和采集时间分别保存。')
    else:st.info('勾选「采集本人创作中心概览」，在导入窗口登录并打开「数据中心 → 视频数据」，才能采集截图中的汇总。')


ACCOUNT_DOM=r'''() => {
 const result={};
 for(const a of document.querySelectorAll('a[href]')){
   const text=(a.innerText||'').trim();const title=(a.title||'').trim();
   let key=null;
   if(/粉丝/.test(text+' '+title))key='followers';
   else if(/关注/.test(text+' '+title))key='following';
   if(!key)continue;
   const candidates=[title,text].map(v=>v.replace(/粉丝数|粉丝量|粉丝|关注数|关注|[：:]/g,'').trim());
   const exact=candidates.find(v=>/^\d[\d,，]*$/.test(v));
   if(exact)result[key]=Number(exact.replace(/[,，]/g,''));
 }
 return result;
}'''
