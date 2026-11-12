"""Overview of actual account coverage, with routes into reports and tasks."""
import streamlit as st
from creatorlab.hub import accounts, eligible, fmt_count, quality


def overview(rows,db,platform,root):
    from creatorlab.task_ui import task_status,LABELS
    from creatorlab.creator_ui import cover
    st.subheader('我的创作总览')
    st.caption('先了解当前平台，再选作品复盘。累计数不是近期新增；没有可信历史快照时不显示虚构增长。')
    own=[a for a in accounts(db) if a['is_self'] and a['platform']==platform]
    if not own:
        st.info('还没有当前平台账号。在侧栏或“设置 → 账号与同步”添加并导入作品。')
    for account in own:
        selected=[r for r in rows if r['account_id']==account['id']]
        with st.container(border=True):
            st.markdown('### '+account['display_name']+' · '+('B站' if platform=='bilibili' else '抖音'))
            a,b,c=st.columns(3)
            a.metric('已管理作品',len(selected));b.metric('可用于公开分析',len(eligible(selected)))
            known=[r for r in selected if r.get('views') is not None]
            c.metric('已知作品累计播放',fmt_count(sum(r['views'] for r in known)) if known else '—')
            dates=[r.get('metric_recorded_at') for r in selected if r.get('metric_recorded_at')]
            st.caption('播放数据最近观测：'+(max(dates) if dates else '尚无可信观测时间'))
            if st.button('浏览这个账号的作品',key='overview_account_'+str(account['id'])):
                st.session_state['_open_library_account']=account['id'];st.rerun()
    data=task_status(root,platform,db)
    with st.container(border=True):
        st.markdown('### 需要处理')
        from creatorlab.integrity import summary,inventory_audit,privacy_notice
        coverage=summary(rows)
        private_count=sum(r.get('visibility')=='private' for r in rows)
        if private_count:st.info(privacy_notice(private_count,platform))
        st.write(f"{coverage['pending']} 条作品的公开状态或播放数据待核实。")
        st.caption(f"私密及其他不可公开计量作品共 {coverage['excluded']} 条，单独保留，不计入异常或待补采。")
        if coverage['pending']:st.table([{'原因':'播放量缺失','条数':coverage['missing']},
                  {'原因':'零播放待核实','条数':coverage['zero']},
                  {'原因':'播放为0但存在互动','条数':coverage['inconsistent']}])
        audit=inventory_audit(data)
        if audit['visible_verified']:
            st.caption(f"已核对当前可见清单 {audit['count']} 条，源页面已到底。")
            if audit['external_gap']:st.warning(f"平台标称总数与可见清单相差 {audit['external_gap']} 条，原因尚未确认；不擅自认定为删除、私密或已采齐。")
        st.caption('采集：'+LABELS.get(data.get('state'),'当前平台暂无任务'))
        if st.button('查看采集进度与缺项',key='overview_tasks'):
            st.session_state['_open_tasks']=True;st.rerun()
    good=sorted(eligible(rows),key=lambda r:r['views'],reverse=True)[:3]
    if good:
        st.markdown('### 从这些作品开始复盘')
        st.caption('按已知累计播放排序，便于找到作品，不代表内容质量排名。')
        for column,row in zip(st.columns(len(good)),good):
            with column:
                cover(row,180);st.write(row['title'])
                st.metric('累计播放',fmt_count(row['views']))
                if st.button('打开作品报告',key='overview_report_'+str(row['id'])):
                    st.session_state['_open_report']=row['id'];st.rerun()
    elif own:st.info('账号已建立。导入真实作品后，可查看作品报告和overall对比。')
