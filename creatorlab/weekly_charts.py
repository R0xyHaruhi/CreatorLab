"""Explicit selected-sample positions; never round a small positive fraction to zero."""
import plotly.graph_objects as go
from creatorlab.hub import fmt_count


def percent_label(value):
    if value is None:return '—'
    if value==0:return '0%'
    if value<.01:return '<0.01%'
    return f'{value:.2f}%'


def lower_count(row):
    return None if row['percent'] is None else round(row['percent']*row['n']/100)


def position_figure(rows):
    visible=[r for r in rows if r['percent'] is not None]
    fig=go.Figure()
    if not visible:return fig
    fig.add_trace(go.Scatter(x=[r['percent'] for r in visible],y=[r['label'] for r in visible],
        mode='markers+text',text=[percent_label(r['percent']) for r in visible],textposition='middle right',
        marker=dict(size=12),name='我的作品',cliponaxis=False,
        customdata=[[fmt_count(r['value']),fmt_count(r['median']),lower_count(r),r['n']] for r in visible],
        hovertemplate='%{y}<br>我的数量：%{customdata[0]}<br>精选中位数：%{customdata[1]}<br>严格高于 %{customdata[2]} / %{customdata[3]} 条样本<extra></extra>'))
    fig.add_vline(x=50,line_dash='dash',line_color='#A4B6B1',annotation_text='高于一半样本（50%）',annotation_position='top')
    fig.update_layout(height=100+45*len(visible),showlegend=False,
        xaxis=dict(range=[0,110],tickvals=[0,25,50,75,100],ticksuffix='%',title='当前指标数值严格更低的精选样本占比'),
        yaxis=dict(autorange='reversed',title=''))
    return fig


def median_gap_figure(rows):
    visible=[r for r in rows if r['value'] is not None and r['median'] is not None and r['median']>0]
    ratios=[100*r['value']/r['median'] for r in visible]
    fig=go.Figure(go.Bar(x=ratios,y=[r['label'] for r in visible],orientation='h',
        text=[percent_label(v) for v in ratios],textposition='outside',cliponaxis=False,
        customdata=[[fmt_count(r['value']),fmt_count(r['median'])] for r in visible],
        hovertemplate='%{y}<br>我的数量：%{customdata[0]}<br>精选中位数：%{customdata[1]}<br>我的数量相当于中位数 %{x:.2f}%<extra></extra>'))
    fig.add_vline(x=100,line_dash='dash',line_color='#A4B6B1',annotation_text='精选中位数 = 100%',annotation_position='top')
    fig.update_layout(height=100+45*max(len(visible),1),showlegend=False,
        xaxis=dict(range=[0,max([125]+[v*1.15 for v in ratios])],ticksuffix='%',title='我的数量 ÷ 当前精选样本中位数'),
        yaxis=dict(autorange='reversed',title=''))
    return fig


def playback_summary(rows):
    row=next((r for r in rows if r['metric']=='views'),None)
    if not row or row['value'] is None or row['percent'] is None:return None
    text=f"你的播放为 {fmt_count(row['value'])}，高于当前 {row['n']:,} 条有效精选样本中的 {lower_count(row):,} 条（{percent_label(row['percent'])}）。"
    if row['median'] is not None and row['median']>0:
        text+=f"当前精选播放中位数为 {fmt_count(row['median'])}；你的播放相当于它的 {percent_label(100*row['value']/row['median'])}。"
    return text
