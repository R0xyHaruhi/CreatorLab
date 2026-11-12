"""Useful visual summaries even when only plays have been imported."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from creatorlab.appearance import chart,PALETTES
from creatorlab.review import display

BUCKETS=['不足100','100–999','1千–1万','1万–10万','10万以上']


def summary(df):
    values=df.views.dropna()
    return {'count':len(values),'total':float(values.sum()),'median':float(values.median()),'maximum':float(values.max())}


def distribution(df,chosen):
    buckets=pd.cut(df.views,[-1,99,999,9999,99999,float('inf')],labels=BUCKETS)
    counts=buckets.value_counts(sort=False).reindex(BUCKETS,fill_value=0)
    selected=buckets.loc[df.id==chosen].iloc[0]
    p=PALETTES[st.session_state.get('clab_appearance','柔和深色')]
    fig=go.Figure(go.Bar(x=BUCKETS,y=counts.tolist(),marker_color=[p['accent'] if b==selected else p['border'] for b in BUCKETS],text=counts.tolist(),textposition='outside',hovertemplate='%{x}次播放<br>%{y}条作品<extra></extra>'))
    fig.update_layout(height=340,yaxis_title='作品数',xaxis_title='已知累计播放',bargap=.35,yaxis=dict(rangemode='tozero'))
    return fig


def headline(rows,df):
    stats=summary(df);cols=st.columns(4)
    for col,label,value in zip(cols,['已入库作品','已知累计播放','作品播放中位数','最高单条播放'],[str(len(rows)),display(stats['total'],'views'),display(stats['median'],'views'),display(stats['maximum'],'views')]):
        col.metric(label,value)
    st.caption(f'{stats["count"]}/{len(rows)} 条作品有可展示播放记录 · 累计值为当前已保存观测，可能采于不同时刻')


def lower_panels(rows,df,chosen):
    p=PALETTES[st.session_state.get('clab_appearance','柔和深色')]
    a,b=st.columns([1.15,1],gap='large')
    with a:
        st.markdown('### 作品排行')
        top=df.nlargest(6,'views').sort_values('views')
        labels=[str(r.title)[:23]+('…' if len(str(r.title))>23 else '') for r in top.itertuples()]
        fig=go.Figure(go.Bar(x=top.views.tolist(),y=list(range(len(top))),orientation='h',customdata=[[int(r.id),str(r.title)] for r in top.itertuples()],
            marker_color=[p['accent'] if i==chosen else '#6D8F9E' for i in top.id],text=[display(v,'views') for v in top.views],textposition='auto',hovertemplate='%{customdata[1]}<br>%{x:,.0f}次累计播放<extra></extra>'))
        fig.update_layout(height=320,yaxis=dict(tickmode='array',tickvals=list(range(len(top))),ticktext=labels),xaxis_title='累计播放')
        event=chart(fig,key='overview_rank',on_select='rerun',selection_mode='points')
        selection=event.get('selection',{}).get('points',[]) if hasattr(event,'get') else []
        if selection:
            pid=selection[0].get('customdata',[chosen])[0]
            if pid!=chosen and pid in set(df.id):st.session_state.hero_next_work=pid;st.rerun()
        st.caption('点击条形切换上方作品。仅为当前累计排序，不代表同龄作品能力排名。')
    with b:
        grouped=df.copy()
        grouped['分组']=[(r.get('genre') if isinstance(r.get('genre'),dict) else {}).get('minor') or (r.get('category') if r.get('category') not in ('未分类','',None) else None) for r in df.to_dict('records')]
        known=grouped.dropna(subset=['分组'])
        if known['分组'].nunique()>=2:
            st.markdown('### 分类表现对比')
            candidates=[g for _,g in known[known.age_band!='未知'].groupby('age_band') if g['分组'].nunique()>=2]
            comparable=bool(candidates);data=max(candidates,key=len) if candidates else known
            result=data.groupby('分组').views.agg(['median','count']).sort_values('median').tail(6)
            fig=go.Figure(go.Bar(x=result['median'].tolist(),y=result.index.tolist(),orientation='h',customdata=result['count'].tolist(),marker_color=p['accent'],text=[display(v,'views') for v in result['median']],textposition='auto',hovertemplate='%{y}<br>中位数 %{x:,.0f}<br>%{customdata}条作品<extra></extra>'))
            fig.update_layout(height=320,xaxis_title='累计播放中位数')
            chart(fig,key='overview_groups')
            st.caption(('同账号、同发布时长范围。' if comparable else '积累时间未对齐，仅看分布。')+'每组样本数在悬停时显示；差异不等于内容造成的效果。')
        else:
            st.markdown('### 数据覆盖地图')
            source=rows[:12]
            fields=[('views','播放'),('likes','点赞'),('comments','评论'),('favorites','收藏'),('shares','分享')]+([('coins','投币')] if rows[0]['platform']=='bilibili' else [('completion_rate','完播')])
            z=[[int(r.get(k) is not None) for k,_ in fields] for r in source]
            hover=[[display(r.get(k),k) if r.get(k) is not None else '尚未取得' for k,_ in fields] for r in source]
            fig=go.Figure(go.Heatmap(z=z,x=[label for _,label in fields],y=list(range(len(source))),customdata=hover,zmin=0,zmax=1,colorscale=[[0,p['panel']],[1,p['accent']]],showscale=False,xgap=5,ygap=5,hovertemplate='%{x}：%{customdata}<extra></extra>'))
            fig.update_layout(height=320,yaxis=dict(tickmode='array',tickvals=list(range(len(source))),ticktext=[r['title'][:12] for r in source],autorange='reversed'))
            chart(fig,key='overview_coverage')
            st.caption('亮色表示已采到原始字段，包括真实的0；深色表示缺失。分类后这里会切换为内容对比。')
