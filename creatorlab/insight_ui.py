"""Optional decision views; core navigation and platform collectors stay independent."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from creatorlab.decision import summarize,CAVEAT


@st.cache_data(show_spinner=False,max_entries=12,ttl=3600)
def _summary(rows):
    return summarize(rows)


def _chart(entries,key):
    data=[r for r in entries if r.get('lift') is not None]
    if not data:return
    fig=go.Figure(go.Scatter(x=[r['lift'] for r in data],y=[r['label'] for r in data],mode='markers',
      error_x=dict(type='data',symmetric=False,array=[r['lift_hi']-r['lift'] for r in data],arrayminus=[r['lift']-r['lift_lo'] for r in data]),
      marker=dict(size=10),customdata=[[r['n'],r['n_rest']] for r in data],hovertemplate='%{y}<br>相对播放中位数 %{x:.2f}倍<br>本组 %{customdata[0]}条 / 其余 %{customdata[1]}条<extra></extra>'))
    fig.add_vline(x=1,line_dash='dot');fig.update_layout(height=max(280,42*len(data)),margin=dict(l=10,r=10,t=15,b=30),xaxis_title='本组 / 其余作品的播放中位数（90%探索区间）',yaxis=dict(autorange='reversed'))
    st.plotly_chart(fig,use_container_width=True,key=key)


def panel(rows,key='insight'):
    from creatorlab.content_analysis import frame
    from creatorlab.measurements import window_rows
    if not rows:st.info('导入作品后查看发布时间与标题对比。');return
    accounts={}
    for r in rows:accounts.setdefault((r['platform'],r.get('account_id',r.get('account_name') or r.get('account'))),r.get('account_name') or r.get('account') or '未命名账号')
    account=st.selectbox('分析账号',list(accounts),format_func=lambda a:accounts[a]+' · '+a[0],key=key+'_account')
    selected=[r for r in rows if (r['platform'],r.get('account_id',r.get('account_name') or r.get('account')))==account]
    formats=sorted({r.get('media_format') or 'unknown' for r in selected})
    media=st.selectbox('作品体裁',formats,format_func=lambda f:{'video':'视频','image':'图文','unknown':'体裁待确认'}.get(f,f),key=key+'_format')
    selected=[r for r in selected if (r.get('media_format') or 'unknown')==media]
    db=next((r.get('_db') for r in selected if r.get('_db')),None)
    if db:
        window=st.selectbox('数据观察范围',['当前累计','24小时','7天','30天'],key=key+'_window')
        if window!='当前累计':selected,_=window_rows(db,selected,window)
    else:window='当前累计'
    df=frame(selected)
    if df.empty:st.info('这个范围没有可比较的正播放作品。私密、缺失和零播放记录不会硬凑结论。');return
    if window=='当前累计':
        ages=[a for a in df.age_band.unique() if a!='未知']
        if not ages:st.info('缺少真实观测时间，尚不能按作品积累时长比较。其他平台CSV目前仅提供独立记录查看。');return
        age=st.selectbox('发布至观测的时间区间',ages,key=key+'_age');df=df[df.age_band==age]
        st.caption('累计数据按作品年龄区间比较，仍会受长期增长和发布年代影响；已发布满7天不代表积累时间相同。')
    st.caption('同账号、同平台、同体裁、同观察范围；发布时间按北京时间。图上1倍表示与其余作品相同。')
    result=_summary(df.to_dict('records'));stats=result['stats']
    if not result['ready']:st.info(result.get('reason','这个范围样本不足；至少12条可用作品，且每组和参照组各至少6条。'));return
    top=result['findings'][:3]
    if top:
        with st.expander('值得记录为实验的线索',expanded=True):
            for text in top:st.write(text)
            st.caption('先固定题材、时长和观察窗口，只改一处条件，再回到“分析与实验”记录新作品结果。')
    else:st.info('现有样本还不能区分这些分组，不能据此认定发布时间或标题没有影响。')
    times,titles,cadence=st.tabs(['发布时间','标题写法','发布节奏'])
    with times:
        _chart(result['timing']['hours'],key+'_hours')
        with st.expander('星期与周末对比'):_chart(result['timing']['weekdays']+[result['timing']['weekend']],key+'_days')
    with titles:_chart(result['titles'],key+'_titles')
    with cadence:
        st.caption('间隔按本次参与比较的作品计算；漏采或筛选会让间隔变长，不代表真实完整发布频率。')
        _chart(list(result['cadence'].values()),key+'_cadence')
    with st.expander('样本、原始结果与比较限制'):
        st.caption(f"使用 {stats['used']} 条作品。每项比较是本组与其余作品，不是不同条件下的因果效果。")
        st.write(CAVEAT)
        st.dataframe(pd.DataFrame([{'标题特征':r['label'],'本组作品':r['n'],'其余作品':r['n_rest'],'中位数比值':r.get('lift'),'判断':{'better':'探索线索：偏高','worse':'探索线索：偏低','unclear':'无法区分','few':'样本不足'}[r['verdict']]} for r in result['titles']]),hide_index=True,width='stretch')


def other_platforms(db):
    from creatorlab.ext_platforms import LABELS,FIELD_LABELS,detect_mapping,preview_csv,import_csv,ext_posts,delete_account
    import csv,io
    st.caption('仅CSV记录导入，不提供自动采集；曝光不映射为播放。“1.2万”等缩略数明确标注为近似值，不进入精确洞察。')
    platform=st.selectbox('表格所属平台',list(LABELS),format_func=LABELS.get,key='ext_platform')
    account=st.text_input('账号名称',key='ext_account')
    upload=st.file_uploader('其他平台CSV',type=['csv'],key='ext_upload')
    if upload is not None:
        try:
            raw=upload.getvalue()
            if len(raw)>10_000_000:raise ValueError('CSV不能超过10MB')
            try:text=raw.decode('utf-8-sig')
            except UnicodeDecodeError:text=raw.decode('gb18030')
            headers=csv.DictReader(io.StringIO(text)).fieldnames or [];auto=detect_mapping(headers);mapping={}
            with st.expander('核对列对应',expanded=True):
                for field,label in FIELD_LABELS.items():
                    options=['（无）']+headers;chosen=st.selectbox(label,options,index=options.index(auto[field]) if field in auto else 0,key='ext_map_'+field)
                    if chosen!='（无）':mapping[field]=chosen
            plan=preview_csv(platform,account,text,mapping)
            st.caption(f"可导入 {len(plan['rows'])} 条；跳过 {plan['skipped']} 条。无作品ID时不按标题推断同一作品，不同文件可能形成重复记录。")
            st.dataframe(pd.DataFrame(plan['rows'][:5]).drop(columns=['key'],errors='ignore'),hide_index=True)
            for error in plan['errors']:st.warning(error)
            if st.button('确认导入以上有效记录',key='ext_go',disabled=not plan['rows']):
                result=import_csv(db,platform,account,text,mapping);st.toast(f"新增{result['inserted']}条、更新{result['updated']}条");st.rerun()
        except (ValueError,UnicodeError,csv.Error) as exc:st.error(str(exc))
    rows=ext_posts(db)
    if not rows:return
    options=sorted({(r['platform'],r['account']) for r in rows});chosen=st.selectbox('查看已导入账号',options,format_func=lambda a:LABELS[a[0]]+' · '+a[1],key='ext_view')
    mine=[r for r in rows if (r['platform'],r['account'])==chosen]
    st.dataframe(pd.DataFrame([{'标题':r['title'],'发布时间':r['published_at'],'播放/阅读':r['views'],'点赞':r['likes'],'评论':r['comments'],'近似值字段':'、'.join(r['approx_fields'])} for r in mine]),hide_index=True,use_container_width=True)
    with st.expander('删除该账号的CSV记录'):
        checked=st.checkbox('确认删除；删除前会自动备份',key='ext_delete_confirm')
        if st.button('删除记录',key='ext_delete',disabled=not checked):delete_account(db,*chosen);st.rerun()
