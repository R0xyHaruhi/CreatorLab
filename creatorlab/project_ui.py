"""Optional cross-platform project linking; never part of the default screen."""
import pandas as pd
import streamlit as st
from creatorlab.hub import projects,add_project,assign_project,fmt_count,fmt_rate
from creatorlab.appearance import table
from creatorlab.feedback import notify


def project_panel(DB,global_posts):
    st.subheader('同一内容，多平台发布')
    st.caption('例如同一条 COS 视频同时发布于抖音和B站，关联成一个内容项目。关联由你手动确认，避免同名误匹配。')
    with st.form('project'):
        name=st.text_input('内容项目名称',placeholder='例：长门有希｜变装短片')
        notes=st.text_input('备注（选填）')
        if st.form_submit_button('创建内容项目'):
            try:add_project(DB,name,notes);notify('内容项目已创建。');st.rerun()
            except ValueError as e:st.error(str(e))
    ps=projects(DB)
    if ps and global_posts:
        selected_post=st.selectbox('选择要关联的作品',global_posts,format_func=lambda r:f"{'抖音' if r['platform']=='douyin' else 'B站'} · {r['title']}",key='link_post')
        options=[None]+ps
        selected_project=st.selectbox('归属内容项目',options,format_func=lambda r: '取消关联' if r is None else r['name'])
        if st.button('保存作品关联'):
            assign_project(DB,selected_post['id'],None if selected_project is None else selected_project['id'])
            notify('作品关联已更新。');st.rerun()
        st.divider()
        st.subheader('内容项目跨平台对比')
        for project in ps:
            members=[r for r in global_posts if r['project_id']==project['id']]
            if not members:continue
            with st.expander(f"{project['name']} · {len(members)} 个发布版本",expanded=len(members)>1):
                table(pd.DataFrame([{'平台':'抖音' if r['platform']=='douyin' else 'B站',
                 '作品':r['title'],'播放':fmt_count(r['views']), '点赞':fmt_count(r['likes']),
                 '评论':fmt_count(r['comments']), '播放/点赞比（展示参考）':
                 fmt_rate(r['likes']/r['views']) if r['views'] and r['likes'] is not None else '—'} for r in members]),hide_index=True,width="stretch")
                st.caption('点赞/播放比仅为按当前数据计算的参考值；不同平台推荐流量和指标口径不完全一致。')
    else:st.info('先添加作品和创建内容项目，就能开始关联。')

