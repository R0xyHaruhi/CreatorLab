"""Creator-first UX: explicit quality gates, useful summaries, searchable cover cards."""
from collections import Counter
from datetime import datetime, timezone, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from creatorlab.feedback import scoped_selectbox
from creatorlab.appearance import chart
from creatorlab.hub import quality, eligible, sort_posts, fmt_count, fmt_rate, fmt_seconds, valid_cover, snapshots

PLATFORM={'douyin':'抖音','bilibili':'B站'}

def label(row):
    return f"{PLATFORM.get(row['platform'],row['platform'])} · {row['title'][:55]}"

def cover(row,width=100,quiet=False):
    from creatorlab.covers import cached_cover
    data = cached_cover(row.get('_db'), row.get('platform'), row.get('external_id'))
    if data:
        st.image(data, width=width)
        return
    url=row.get('cover_url')
    # Platform images may reject a third-party referrer; don't display a broken remote image.
    if quiet:st.caption('暂无封面');return
    st.markdown('🎬 **暂无本地封面**')
    st.caption('同步缓存后显示；也可在详情补充原封面。')

def cards(rows, metric='views', limit=8, actions=False,compact=False):
    from creatorlab.personal_ui import publication_label
    if not rows:
        st.info('暂无符合条件的作品。')
        return
    for r in rows[:limit]:
        a,b,c=st.columns([1,5,2],vertical_alignment='center')
        with a:cover(r,88,quiet=compact)
        with b:
            st.markdown('**'+r['title'].replace('**','')+'**')
            st.caption(f"{PLATFORM.get(r['platform'],r['platform'])} · {publication_label(r.get('published_at'))} · {quality(r)}")
            if not compact and r.get('url') and str(r['url']).startswith('https://'):
                st.link_button('查看原作品',r['url'])
        with c:
            if actions and st.button('查看报告',key='library_open_'+str(r['id']),width='stretch'):
                st.session_state['_open_report']=r['id'];st.rerun()
            val=r.get(metric)
            display=fmt_rate(val) if metric in ('completion_rate','bounce_rate_2s','completion_rate_5s') else fmt_seconds(val) if metric=='avg_view_second' else fmt_count(val)
            if compact:st.caption('播放 '+display)
            else:st.metric({'views':'播放量','completion_rate':'完播率','bounce_rate_2s':'2秒跳出率','likes':'点赞量'}.get(metric,metric),display)
        st.divider()

def quality_summary(rows):
    counts=Counter(quality(r) for r in rows)
    valid=counts['可分析']
    st.caption(f"已入库 {len(rows)} 条 · {valid} 条具备可用于流量比较的正播放记录 · {len(rows)-valid} 条暂不参与流量排行")
    return counts

def home(rows):
    st.subheader('🏠 我的创作概况')
    if not rows:
        st.info('连接账号并同步作品后，自动生成你的创作概况。')
        return
    good=eligible(rows)
    known=[r for r in rows if r.get('views') is not None]
    a,b,c,d=st.columns(4)
    a.metric('已管理作品',len(rows));b.metric('可分析作品',len(good))
    c.metric('已知作品累计播放',fmt_count(sum(r['views'] for r in known)))
    from creatorlab.integrity import summary
    d.metric('待核实数据',summary(rows)['pending'])
    st.caption('累计播放是当前已知作品的最新累计值，并非最近30天新增播放；零播放与私密状态不会被擅自认定。')
    quality_summary(rows)
    if len(good)<max(5,len(rows)//3):
        st.warning('当前有效播放数据较少，部分账号结论暂不展示。请先检查「账号与同步」的数据质量。')
    if good:
        st.markdown('#### ⭐ 表现突出的作品')
        cards(sorted(good,key=lambda r:r['views'],reverse=True),limit=3)
    st.markdown('#### 🔍 需要关注')
    suspicious=[r for r in rows if quality(r) not in ('可分析','不可公开计量')]
    if suspicious:st.info(f'有 {len(suspicious)} 条作品需要核实可见性或播放数据；这些作品不会被误判为低播放作品。')
    if any(r.get('bounce_rate_2s') is not None for r in good):
        st.markdown('#### 🎯 优先复盘开头')
        cards(sorted([r for r in good if r.get('bounce_rate_2s') is not None],key=lambda r:r['bounce_rate_2s'],reverse=True),metric='bounce_rate_2s',limit=3)
    st.caption('所有建议是待验证的观察，不代表平台算法因果关系。')

def library(rows,db,compact=False):
    st.subheader('作品库')
    from creatorlab.reporting import filter_library,safe_csv
    def reset():
        for k in list(st.session_state):
            if k.startswith('library_') and k!='library_reset':del st.session_state[k]
        # Assign defaults as new widget values, so Streamlit sends set_value
        # to the browser instead of leaving old text in the mounted input.
        st.session_state.update(library_search='',library_account=None,
            library_time='全部时间',library_quality='全部',library_order='最新发布',
            library_page=1,library_batch=[])
        ordered=filter_library(rows)
        st.session_state.library_detail=ordered[0]['id'] if ordered else None
    search=st.text_input('搜索标题 / 视频 ID',placeholder='输入角色、关键词或作品 ID',key='library_search')
    with st.expander('筛选与排序') if compact else st.container():
        st.button('重置筛选',key='library_reset',on_click=reset)
        b,c=st.columns(2)
        account_names={r['account_id']:r['account_name'] for r in rows}
        if st.session_state.get('library_account') not in (None,*account_names):st.session_state.pop('library_account',None)
        account=scoped_selectbox('账号',host=b,options=[None]+list(account_names),format_func=lambda i:'全部账号' if i is None else account_names[i],key='library_account')
        time=scoped_selectbox('发布时间',host=c,options=['全部时间','最近7天','最近30天','最近90天','最近365天'],key='library_time')
        d,e=st.columns(2)
        state=scoped_selectbox('数据状态',host=d,options=['全部','可分析','零播放待核实','播放量疑似异常','播放量缺失','不可公开计量'],key='library_quality')
        extra_orders=['完播率最高','跳出率最高','平均观看最长'] if any(r['platform']=='douyin' for r in rows) else []
        orders=['最新发布','最早发布','播放量最高','播放量最低','点赞最多','评论最多','分享最多']+extra_orders
        if st.session_state.get('library_order') not in (None,*orders):st.session_state.pop('library_order',None)
        order=scoped_selectbox('排序',host=e,options=orders,key='library_order')
    days=None if time=='全部时间' else {'最近7天':7,'最近30天':30,'最近90天':90,'最近365天':365}[time]
    imported_ids = set(st.session_state.get('library_import_ids') or ())
    if imported_ids:
        st.info('当前显示刚导入的作品。')
        st.button('查看全部作品',key='library_clear_import',on_click=reset)
    library_rows = [row for row in rows if row['id'] in imported_ids] if imported_ids else rows
    filtered=filter_library(library_rows,search,account,state,order,days)
    signature=(search,account,time,state,order)
    if st.session_state.get('library_filter_signature')!=signature:
        st.session_state.library_page=1
        st.session_state.library_filter_signature=signature
    st.caption(f'找到 {len(filtered)} / {len(library_rows)} 条作品 · 优先显示本地缓存封面 · 发布时间筛选由你选择')
    if filtered:
        page_size=6 if compact else 20
        pages=max(1,(len(filtered)+page_size-1)//page_size)
        st.session_state.library_page=min(st.session_state.get('library_page',1),pages)
        page=st.number_input('页码',min_value=1,max_value=pages,step=1,key='library_page') if pages>1 or not compact else 1
        cards(filtered[(page-1)*page_size:page*page_size],limit=page_size,actions=True,compact=compact)
        with st.expander('对比、导出或编辑作品') if compact else st.container():
            st.download_button('导出当前筛选结果 CSV',safe_csv(filtered),'clab_filtered_posts.csv','text/csv')
            ids=[r['id'] for r in filtered]
            by_id={r['id']:r for r in filtered}
            current=[i for i in st.session_state.get('library_batch',[]) if i in ids]
            if current!=st.session_state.get('library_batch',[]):st.session_state.library_batch=current
            selected=st.multiselect('勾选2—3条作品对比',ids,format_func=lambda i:label(by_id[i]),max_selections=3,key='library_batch')
            if st.button('对比所选作品',disabled=len(selected)<2,key='library_compare'):
                st.session_state['_compare_selection']=selected;st.rerun()
            if st.session_state.get('library_detail') not in (None,*ids):st.session_state.pop('library_detail',None)
            detail_id=scoped_selectbox('编辑作品与查看原始记录',ids,format_func=lambda i:label(by_id[i]),key='library_detail')
            chosen=by_id[detail_id]
            with st.expander('作品详情',expanded=False):
                cover(chosen,160)
                from creatorlab.hub import update_publication_date
                with st.form(f'publication_{detail_id}'):
                    published = st.text_input('发布时间（选填）', value=chosen.get('published_at') or '',
                                              placeholder='2026-10-26 或 2026-10-26T12:00:00+08:00')
                    if st.form_submit_button('保存发布时间'):
                        try:
                            update_publication_date(db, chosen['account_id'], detail_id, published)
                            from creatorlab.feedback import notify
                            notify('发布时间已保存。');st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                if chosen.get('bili_partition'):st.caption('B站返回的分区：'+chosen['bili_partition'])
                if chosen.get('bili_tags'):st.caption('B站返回的标签：'+'、'.join(chosen['bili_tags']))
                from creatorlab.content_ui import edit_content
                edit_content(db, chosen)
                from creatorlab.covers import save_cover
                uploaded_cover=st.file_uploader('补充这条作品的原封面', type=['png','jpg','jpeg','webp'], key=f'cover_{chosen["id"]}')
                if uploaded_cover and st.button('保存原封面',key=f'savecover_{chosen["id"]}'):
                    try:
                        if not chosen.get('external_id'): raise ValueError('先补充视频 ID 后再保存封面')
                        save_cover(db,chosen['platform'],chosen['external_id'],uploaded_cover.getvalue(),'user_upload')
                        from creatorlab.feedback import notify
                        notify('封面已保存。');st.rerun()
                    except ValueError as exc: st.error(str(exc))
                from creatorlab.platforms import COMMON,EXTRAS
                for k,name in COMMON+EXTRAS[chosen['platform']]:
                    val=chosen.get(k)
                    st.write(f'{name}：'+(fmt_rate(val) if k in ('completion_rate','completion_rate_5s','bounce_rate_2s') else fmt_seconds(val) if k=='avg_view_second' else fmt_count(val)))
                st.caption(f"来源：{chosen['source']} · 最近同步：{chosen.get('metric_recorded_at') or '未知'}")
                from creatorlab.measurements import view_history
                history=view_history(db,chosen['id'])
                if len(history)>1:
                    chart(px.line(pd.DataFrame(history),x='observed_at',y='value',markers=True,labels={'observed_at':'实际观测时间','value':'观测到的累计播放'}),use_container_width=True)
                elif not history:st.caption('旧快照没有可信的逐字段观测时刻，不绘制伪增长曲线；重新同步后开始记录。')
    else:st.info('没有匹配的作品，请调整筛选条件。')

def analytics(rows):
    from creatorlab.content_ui import analysis_dashboard
    analysis_dashboard(rows)


def assistant(rows):
    from creatorlab.content_ui import assistant_dashboard
    assistant_dashboard(rows)
