"""Creator-centric, evidence-tagged Streamlit diagnostics."""
import math
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from creatorlab.hub import fmt_count,fmt_rate,fmt_seconds,snapshots
from creatorlab.insights import COUNTS,RATES,LABELS,describe,completeness,leaderboard,actions,rate_for,match_candidates

PLATFORM={'douyin':'抖音','bilibili':'B站'}
def _frame(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()
def _chart(fig,key=None):
    fig.update_layout(height=365,margin=dict(l=12,r=12,t=50,b=18),legend_title_text='',hovermode='closest')
    st.plotly_chart(fig,use_container_width=True,key=key)
def _axis_label(row):
    return (row['title'][:22]+('…' if len(row['title'])>22 else ''))+f' · {PLATFORM.get(row["platform"],row["platform"])}'
def _date(value):
    d=pd.to_datetime(value,utc=True,errors='coerce')
    return None if pd.isna(d) else d

def render(rows, db, accounts_list):
    st.subheader('📊 创作者数据驾驶舱')
    st.caption('全部基于你的实际导入记录；不生成虚构数据、不替代平台官方指标。若数据不足，会明确显示缺失情况。')
    if not rows:
        st.info('尚未发现作品。请到「添加账号与导入」同步已有的抖音采集数据，或导入 B站 CSV；同步后此页面自动生成图表。')
        return
    names=['全部平台']+[f"{PLATFORM.get(a['platform'],a['platform'])} · {a['display_name']}" for a in accounts_list]
    selected=st.selectbox('分析账号',range(len(names)),format_func=lambda i:names[i],key='insight_account')
    scope=rows if selected==0 else [r for r in rows if r['account_id']==accounts_list[selected-1]['id']]
    period=st.selectbox('作品发布时间范围',['全部时间','最近30天','最近90天','最近365天'],key='insight_period')
    if period!='全部时间':
        now=pd.Timestamp.now(tz='UTC')
        days={'最近30天':30,'最近90天':90,'最近365天':365}[period]
        known=[r for r in scope if _date(r.get('published_at')) is not None]
        scope=[r for r in known if _date(r.get('published_at'))>=now-pd.Timedelta(days=days)]
        st.caption(f'筛选的是作品**发布时间**，不是近 {days} 天新增播放；无有效发布时间的作品不计入。')
    if not scope:
        st.warning('当前筛选范围暂无作品，换个账号或时间区间试试。')
        return
    views=describe(scope,'views');complete=describe(scope,'completion_rate');seconds=describe(scope,'avg_view_second')
    metrics=st.columns(5)
    metrics[0].metric('作品数',len(scope))
    metrics[1].metric('已知播放总量',fmt_count(sum(r['views'] for r in scope if r.get('views') is not None)))
    metrics[2].metric('播放量中位数',fmt_count(views['median']))
    metrics[3].metric('完播率中位数',fmt_rate(complete['median']))
    metrics[4].metric('观看时长中位数',fmt_seconds(seconds['median']))
    st.caption('播放总量为作品最新累计播放快照之和，不是指定日期内新增播放；中位数仅统计非空记录。')
    tabs=st.tabs(['🧭 账号体检','📈 增长趋势','👀 留存诊断','❤️ 互动质量','🏆 作品排行','🔀 跨平台','✨ 行动建议'])
    with tabs[0]:
        st.markdown('#### 数据覆盖率与可靠性')
        coverage=completeness(scope)
        cov=pd.DataFrame([{'指标':LABELS[k],'有数据的作品':v['present'],'尚缺少':v['total']-v['present'],
          '覆盖率':round(100*v['present']/v['total'],1) if v['total'] else 0} for k,v in coverage.items()])
        c1,c2=st.columns([2,1])
        with c1:
            fig=go.Figure()
            fig.add_bar(y=cov['指标'],x=cov['覆盖率'],orientation='h',text=[f'{n}/{len(scope)}' for n in cov['有数据的作品']],textposition='auto')
            fig.update_layout(title='哪些指标真的采集到了？',xaxis_title='覆盖率 (%)',xaxis_range=[0,110],yaxis_autorange='reversed')
            _chart(fig,'cov')
        with c2:
            st.metric('具备播放数据',f"{coverage['views']['present']}/{len(scope)}")
            st.metric('具备留存数据',f"{coverage['completion_rate']['present']}/{len(scope)}")
            st.metric('具备分享数据',f"{coverage['shares']['present']}/{len(scope)}")
            st.info('缺失值不会当作 0，缺少的数据也不会由 AI 猜测。')
        c3,c4=st.columns(2)
        with c3:
            if views['n']:
                plot=pd.DataFrame([{'播放量':r['views'],'平台':PLATFORM.get(r['platform'],r['platform'])} for r in scope if r.get('views') is not None])
                fig=px.histogram(plot,x='播放量',color='平台',nbins=min(25,max(5,len(plot)//2)),title='累计播放量分布')
                _chart(fig,'views_hist')
        with c4:
            if views['n']:
                fig=go.Figure()
                fig.add_bar(x=['P25','中位数','P75'],y=[views['q1'],views['median'],views['q3']],text=[fmt_count(views[k]) for k in ['q1','median','q3']],textposition='outside')
                fig.update_layout(title='日常作品的典型播放区间',yaxis_title='累计播放量')
                _chart(fig,'views_q')
    with tabs[1]:
        st.markdown('#### 发布节奏与播放表现')
        dated=[r for r in scope if _date(r.get('published_at')) is not None]
        if not dated: st.info('作品缺少有效发布时间，无法生成发布节奏图。')
        else:
            d=pd.DataFrame([{'日期':_date(r['published_at']).date(),'平台':PLATFORM.get(r['platform'],r['platform']),
               '累计播放':r.get('views'),'作品':r['title']} for r in dated])
            d['周']=pd.to_datetime(d['日期']).dt.to_period('W').astype(str)
            freq=d.groupby(['周','平台']).size().reset_index(name='发布作品数')
            _chart(px.bar(freq,x='周',y='发布作品数',color='平台',barmode='group',title='每周发布数量（按作品发布时间）'),'publishing')
            known=d.dropna(subset=['累计播放'])
            if not known.empty:
                weekly=known.groupby(['周','平台'],as_index=False)['累计播放'].median()
                _chart(px.line(weekly,x='周',y='累计播放',color='平台',markers=True,title='每周发布作品的当前累计播放中位数'),'weekly_perf')
                st.caption('上图不是每周获得的播放量，而是该周发布作品截至最后同步时的累计播放；较新作品曝光时间更短。')
        history=[]
        for r in scope[:400]:
            rec=[x for x in snapshots(db,r['id']) if x.get('views') is not None]
            if len(rec)>1:
                for h in rec:
                    history.append({'时间':h['recorded_at'],'累计播放':h['views'],'作品':_axis_label(r),'作品ID':r['id']})
        if history:
            st.markdown('#### 真实历史快照')
            options={r['id']:_axis_label(r) for r in scope if any(x['作品ID']==r['id'] for x in history)}
            chosen=st.selectbox('查看单条作品',list(options),format_func=lambda i:options[i],key='history_choice')
            data=pd.DataFrame([h for h in history if h['作品ID']==chosen])
            _chart(px.line(data,x='时间',y='累计播放',markers=True,title='作品累计播放随同步时间变化'),'history')
            st.caption('仅使用确实保存的历史快照。重复同步的累计播放变化不能单独解释推荐机制。')
        else:st.info('同步同一批作品至少两次，并保留不同时间点的数据后，这里才会出现真实增长曲线。')
    with tabs[2]:
        st.markdown('#### 观众在哪里流失？')
        platforms={r['platform'] for r in scope}
        if len(platforms)>1:st.warning('不同平台的留存定义可能不同。这里仅展示抖音留存指标；请在上方选择具体账号查看完整同平台比较。')
        retention_scope=[r for r in scope if r['platform']=='douyin'] if len(platforms)>1 else scope
        retention=[('bounce_rate_2s','2秒跳出率'),('completion_rate_5s','5秒留存指标'),('completion_rate','完播率'),('avg_view_proportion','平均观看比例')]
        vals=[{'指标':label,'中位数':describe(retention_scope,key)['median']*100,'样本':describe(retention_scope,key)['n']} for key,label in retention if describe(retention_scope,key)['n']]
        if vals:
            fig=px.bar(pd.DataFrame(vals),x='指标',y='中位数',text='样本',title='留存相关指标（各指标独立样本）')
            fig.update_layout(yaxis_title='百分比 (%)')
            _chart(fig,'retention_bars')
            st.caption('这些指标并非同一人群的逐秒存活人数，不能拼成严格的留存漏斗；5秒字段名称沿用数据来源定义。')
        else:st.info('尚无留存指标。请优先从抖音创作者后台导入包含完播率与跳出率的数据。')
        options=[('bounce_rate_2s','2秒跳出率',True),('completion_rate','完播率',False),('avg_view_second','平均观看时长（秒）',False)]
        for key,label,low_good in options:
            found=leaderboard(retention_scope,key,high=low_good,limit=12)
            if found:
                data=pd.DataFrame([{'作品':_axis_label(r),'数值':r[key]*100 if key in RATES else r[key]} for r in found])
                fig=px.bar(data.sort_values('数值'),x='数值',y='作品',orientation='h',title=f'{label}重点复盘作品')
                fig.update_layout(xaxis_title='百分比 (%)' if key in RATES else '秒')
                _chart(fig,'retain_'+key)
    with tabs[3]:
        st.markdown('#### 谁真正愿意互动？')
        valid_count=[r for r in scope if r.get('views') is not None and r['views']>0]
        if not valid_count: st.info('当前缺少有效播放量，无法计算互动/播放比。')
        else:
            rec=[]
            for r in valid_count:
                item={'作品':_axis_label(r),'平台':PLATFORM.get(r['platform'],r['platform']),'播放量':r['views']}
                for field,label in [('likes','点赞/播放'),('comments','评论/播放'),('shares','分享/播放'),('favorites','收藏/播放')]:
                    ratio=rate_for(r,field)
                    item[label]=ratio*100 if ratio is not None else float('nan')
                rec.append(item)
            dd=pd.DataFrame(rec)
            available=[x for x in ['点赞/播放','评论/播放','分享/播放','收藏/播放'] if dd[x].notna().any()]
            if available:
                med=dd.groupby('平台')[available].median().reset_index().melt(id_vars='平台',var_name='指标',value_name='中位百分比')
                _chart(px.bar(med,x='指标',y='中位百分比',color='平台',barmode='group',title='互动/播放比中位数（独立指标）'),'interact')
                st.caption('互动/播放不是官方互动率，不同平台的播放定义及数据更新时间可能不同。')
                chosen_metric=st.selectbox('互动作品排行',available,key='interact_rank')
                best=dd.dropna(subset=[chosen_metric]).sort_values(chosen_metric,ascending=False).head(12)
                _chart(px.bar(best.sort_values(chosen_metric),x=chosen_metric,y='作品',orientation='h',title='互动率相对较高作品'),'interact_rank_chart')
            raw=[{'作品':_axis_label(r),'点赞':fmt_count(r.get('likes')),'评论':fmt_count(r.get('comments')),
                 '分享':fmt_count(r.get('shares')),'收藏':fmt_count(r.get('favorites'))} for r in scope]
            st.dataframe(pd.DataFrame(raw),hide_index=True,use_container_width=True)
    with tabs[4]:
        st.markdown('#### 表现最好与最需要检查的作品')
        available=[k for k in (*COUNTS,*RATES,'avg_view_second') if describe(scope,k)['n']]
        if not available:st.info('还没有任何可用于排行的指标。')
        else:
            chosen=st.selectbox('指标',available,format_func=lambda k:LABELS[k],key='rank_metric')
            high=leaderboard(scope,chosen,True,15)
            low=leaderboard(scope,chosen,False,15)
            c1,c2=st.columns(2)
            def ranking_table(items):
                return pd.DataFrame([{'作品':_axis_label(r),'数值':fmt_rate(r[chosen]) if chosen in RATES else fmt_seconds(r[chosen]) if chosen=='avg_view_second' else fmt_count(r[chosen]),'来源':r['source']} for r in items])
            with c1:
                st.markdown('**数值最高**');st.dataframe(ranking_table(high),hide_index=True,use_container_width=True)
            with c2:
                st.markdown('**数值最低**');st.dataframe(ranking_table(low),hide_index=True,use_container_width=True)
            st.caption('不同指标的“高”不一定代表更好，例如2秒跳出率越高通常越需要关注。')
    with tabs[5]:
        st.markdown('#### 同一内容的跨平台表现')
        groups={}
        for r in scope:
            if r.get('project_id'):groups.setdefault(r['project_id'],[]).append(r)
        matched=[x for x in groups.values() if len({r['platform'] for r in x})>1]
        if matched:
            compare=[]
            for group in matched:
                for r in group:
                    compare.append({'内容项目':r.get('project_name') or str(r['project_id']),
                      '平台':PLATFORM.get(r['platform'],r['platform']),'当前累计播放':r.get('views'),
                      '作品':r['title'],'点赞':r.get('likes')})
            dd=pd.DataFrame(compare)
            if dd['当前累计播放'].notna().any():
                _chart(px.bar(dd.dropna(subset=['当前累计播放']),x='内容项目',y='当前累计播放',color='平台',barmode='group',title='同一内容的不同平台发布版本'),'cross_platform')
            st.dataframe(dd,hide_index=True,use_container_width=True)
            st.caption('不同平台的发布时间、推荐机制与累计周期可能不同；不应由一次播放对比断定哪个平台更适合。')
        else:st.info('先将同一内容的抖音和B站版本关联为一个项目，才可建立可信的跨平台对比。')
        candidates=match_candidates(scope)
        if candidates:
            st.markdown('**可能是同一内容的待确认作品**')
            st.caption('仅按高度一致的作品标题寻找候选，不会自动把不同作品合并。')
            for g in candidates[:8]:st.write(' / '.join(f'{PLATFORM.get(r["platform"])} · {r["title"][:35]}' for r in g))
    with tabs[6]:
        st.markdown('#### 由数据到下一次创作')
        platform=scope[0]['platform'] if len({r['platform'] for r in scope})==1 else 'all'
        for item in actions(scope,platform):
            with st.container(border=True):
                st.markdown('**'+item['title']+'**')
                st.write(item['detail'])
                st.caption('数据依据：'+item['evidence'])
        st.markdown('#### 导出给自己看的分析摘要')
        text=['CLab 创作者诊断报告','作品数：'+str(len(scope)),
          '有播放数据：'+str(views['n']), '播放中位数：'+fmt_count(views['median']),
          '完播率中位数：'+fmt_rate(complete['median'])]
        for item in actions(scope,platform):text.extend(['','【'+item['title']+'】',item['detail'],'依据：'+item['evidence']])
        st.download_button('下载诊断报告 TXT','\n'.join(text).encode('utf-8-sig'),'CLab_创作者诊断报告.txt','text/plain')
