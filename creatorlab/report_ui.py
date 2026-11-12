"""A complete work report with explicit denominators and reference scope."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from creatorlab.feedback import scoped_selectbox
from creatorlab.reporting import comparison_table, positions, metric_value, safe_csv
from creatorlab.hub import quality, eligible, fmt_count, fmt_rate, fmt_seconds
from creatorlab.appearance import chart


def formatted(value,unit):
    if unit=='images':return '—' if value is None else f'{value:g}张'
    if unit=='rate':
        if value is None:return '—'
        if 0<value<.0001:return '<0.01%'
        return f'{value:.2%}'
    return fmt_seconds(value) if unit=='seconds' else fmt_count(value)


def overall(rows,key='overall'):
    from creatorlab.personal_ui import publication_label
    data=comparison_table(rows)
    st.caption('Overall · 全部可比指标一览。各项分别展示，不把播放、比例和观看秒数相加成质量总分。')
    for unit,heading in [('count','实际规模'),('rate','互动与观看比例'),('seconds','观看时长'),('images','图文浏览张数')]:
        items=[r for r in data if r['unit']==unit]
        if items:
            st.markdown('#### '+heading)
            st.table(pd.DataFrame([{'指标':r['label'],**{chr(65+i)+' · '+row['title']:formatted(r['values'][i],unit) for i,row in enumerate(rows)}} for r in items]))
    if any((r.get('views') or 0)<1000 for r in rows):st.info('部分作品播放不足1,000：互动比例可能不稳定，请同时查看实际数量与分母。')
    st.caption('— 表示缺失、分母为0、图文不适用，或分子与播放的观测时间无法配对。零播放不能直接推断为私密。')
    st.table(pd.DataFrame([{'标识':chr(65+i),'作品':r['title'],'账号':r.get('account_name',''),
              '播放分母':fmt_count(r.get('views')),'来源':r.get('source','未知'),
              '播放观测时间':r.get('field_observed_at',{}).get('views') or r.get('metric_recorded_at') or '未知',
              '发布时间':publication_label(r.get('published_at'),show_time=True)} for i,r in enumerate(rows)]))
    st.download_button('导出完整对比 CSV',safe_csv([{'指标':r['label'],'单位':r['unit'],**{chr(65+i):v for i,v in enumerate(r['values'])}} for r in data]),'clab_overall.csv','text/csv',key=key+'_csv')


def report(rows,db,demo=False):
    from creatorlab.creator_ui import cover
    from creatorlab.personal_ui import dated_label
    from creatorlab.reporting import filter_library
    st.subheader('作品报告')
    if demo:
        st.info('示例数据 · 此报告用于体验分析流程。')
    if not rows:
        st.info('导入作品后，这里展示一份包含数据、比较依据和缺项说明的完整报告。');return
    ordered=filter_library(rows);ids=[r['id'] for r in ordered]
    if st.session_state.get('report_work') not in (None,*ids):st.session_state.pop('report_work',None)
    chosen=scoped_selectbox('查看作品报告',ids,format_func=lambda i:dated_label(next(r for r in ordered if r['id']==i)),key='report_work')
    row=next(r for r in rows if r['id']==chosen)
    private=row.get('visibility')=='private'
    left,right=st.columns([1,4])
    with left:cover(row,160)
    with right:
        st.markdown('### '+row['title']);st.caption(row.get('account_name','')+' · '+quality(row))
        if str(row.get('url') or '').startswith('https://'):st.link_button('打开原作品',row['url'])
        st.caption('来源：'+('示例数据' if demo else str(row.get('source') or '未知'))+' · 播放观测于：'+str(row.get('metric_recorded_at') or '未知'))
    a,b,c=st.columns(3)
    prefix='历史' if private else ''
    a.metric(prefix+'累计播放',fmt_count(row.get('views')));b.metric(prefix+'累计点赞',fmt_count(row.get('likes')));c.metric(prefix+'累计收藏',fmt_count(row.get('favorites')))
    if private:
        from creatorlab.integrity import privacy_notice
        st.info(privacy_notice(1,row.get('platform')))
        st.caption('以下已有数值仅作历史记录参考，不代表当前能获取私密作品数据；不参与公开表现评分。')
    elif not eligible([row]):st.warning('这条作品的可见性或播放数据待核实，不参与公开表现排序；已有原始值仍可查看。')
    with st.expander('完整指标与导出'):
        overall([row],key='report')
    with st.expander('逐字段数据时间与缺项',expanded=False):
        st.table([{'指标':item['label'],'值':formatted(item['values'][0],item['unit']),
                   '实际观测时间':row.get('field_observed_at',{}).get(item['metric'],'比例见对应原始字段' if '_ratio' in item['metric'] else '未知')}
                  for item in comparison_table([row])])
    if private:return
    if not demo and row.get('media_format')!='image' and st.button('检查这条视频的可疑片段',key='report_video_check'):
        st.session_state['_open_video_check']={'post_id':row['id'],'account_id':row['account_id']};st.rerun()
    st.markdown('### 与自己的历史作品比较')
    st.caption('默认当前账号、当前平台的全部历史有效作品，不按年龄、赛道或体裁自动分组。各指标分别统计有效值；累计与固定窗口分开，当前作品不计入参照。')
    reference_scope='全部历史有效作品' if demo else st.radio('历史参照范围',['全部历史有效作品','同赛道（按已确认分类）'],horizontal=True,key='report_own_scope')
    own_scope='all' if reference_scope=='全部历史有效作品' else 'track'
    if own_scope=='track':
        with st.expander('自选作品并标注分类'):
            from creatorlab.classification_ui import editor
            editor(db,[r for r in rows if r['account_id']==row['account_id']],'report_classify')
        from creatorlab.own_scope import scope_label
        st.caption(scope_label(row,'track')+'；只在你主动选择此范围后使用分类。')
    dates=None
    if st.checkbox('自行筛选参照作品的发布时间',key='report_date_filter'):
        date_values=[pd.to_datetime(r.get('published_at'),utc=True,errors='coerce') for r in rows]
        valid=[d.date() for d in date_values if pd.notna(d)]
        if valid:
            selected=st.date_input('参照发布时间范围',value=(min(valid),max(valid)),key='report_dates')
            if len(selected)==2:dates=selected
            else:st.info('请选择开始和结束日期。');return
        else:st.info('没有可筛选的已知发布时间。');return
    values=positions(rows,row,dates,own_scope);counts=[v for v in values if v['unit']=='count']
    usable=[v for v in counts if v['percent'] is not None]
    if len(usable)>=3:
        labels=[v['label'] for v in counts];r=[v['percent'] for v in counts]
        from creatorlab.appearance import PALETTES
        palette=PALETTES[st.session_state.get('clab_appearance','柔和深色')]
        fig=go.Figure(go.Scatterpolar(r=r+[r[0]],theta=labels+[labels[0]],mode='lines+markers',connectgaps=False,
                      fill='toself' if all(v is not None for v in r) else 'none',fillcolor='rgba(57,124,98,.12)',
                      line=dict(color=palette['accent'],width=3),marker=dict(size=6),name='数量位置',
                      hovertemplate='%{theta}<br>数量位置 %{r:.1f}%<extra></extra>'))
        fig.update_layout(height=400,margin=dict(l=64,r=64,t=40,b=40),polar=dict(radialaxis=dict(range=[0,100],ticksuffix='%')))
        chart(fig,key='report_counts_radar')
    else:st.info('至少3个数量维度各有3条其他有效作品，才绘制数量位置图；已有数值继续显示。')
    st.caption('图形只表示各项实际数量的位置，不是综合质量评分。100%表示该项数值严格高于全部当前参照，并列不算超过。')
    st.table([{'指标':v['label'],'实际值':formatted(v['value'],v['unit']),'有效参照':v['n'],
               '数值更低的参照占比':'样本不足 / 无有效值' if v['percent'] is None else f"{v['percent']:.1f}%"} for v in values])
    if row.get('views') and row['views']<1000:st.caption('小播放量下比例波动大，2播放1点赞不会因50%点赞率自动获得综合第一。')
    if demo:
        return
    st.markdown('### 历史观测与下一步')
    from creatorlab.measurements import view_history
    history=view_history(db,row['id'])
    if len({h['observed_at'] for h in history})>=2:
        chart(px.line(pd.DataFrame(history),x='observed_at',y='value',markers=True,labels={'value':'观测到的累计播放','observed_at':'实际观测时间'}),key='report_history')
        st.caption('仅连接真实观测点，不还原未采集日期；计数回退也如实保留。')
    else:st.info('尚无多个可信时间点，暂不绘制增长曲线。后续同步会积累观测记录。')
    missing=[v['label'] for v in values if v['value'] is None]
    if missing:st.write('优先核对缺项：'+'、'.join(missing)+'。可在采集任务中补采，平台未提供的指标保持缺失。')
    st.write('比较数量和互动效率后，再决定下一次只改变哪一处内容。观察差异不能证明选题或剪辑造成了结果。')
    if row.get('bili_tags'):st.caption('公开标签：'+'、'.join(row['bili_tags']))
    if row['platform']=='bilibili':
        st.caption('点击顶部「每周必看」，可选择作品与 B 站精选样本对比。')
