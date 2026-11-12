"""Four tasks, one active screen. Existing analytics remain behind explicit choices."""
from pathlib import Path
import streamlit as st

WORK='app_pages/works.py'
CREATE='app_pages/create.py'
LIBRARY='app_pages/library.py'
SETTINGS='app_pages/settings.py'


def consume_route(state):
    """Translate existing feature actions into one destination before widgets render."""
    route=state.pop('_workspace_route',None)
    state.update(state.pop('_workspace_updates',{}))
    if '_open_report' in state:
        state['report_work']=state.pop('_open_report');state['work_view']='详细数据';route=WORK
    if '_open_library_account' in state:
        state['library_account']=state.pop('_open_library_account');route=LIBRARY
    if state.pop('_open_tasks',False):state['settings_view']='同步与进度';route=SETTINGS
    if '_open_video_check' in state:
        item=state.pop('_open_video_check');state['material_post']=item['post_id']
        state['video_check_account']=item['account_id'];state['create_step']='检查视频';route=CREATE
    if '_compare_selection' in state:
        selected=state.pop('_compare_selection')
        state['quick_a'],state['quick_b']=selected[:2]
        state['quick_c']=selected[2] if len(selected)>2 else None
        state['quick_metric']='Overall · 全指标';state['work_view']='作品对比';route=WORK
    return route


def route(page,**values):
    st.session_state['_workspace_updates']=values
    st.session_state['_workspace_route']=page;st.rerun()


def context():return st.session_state['_workspace_context']


def works_page():
    ctx=context();rows=ctx['rows'];db=ctx['db'];platform=ctx['platform']
    demo = not rows and st.session_state.get('demo_platform') == platform
    if demo:
        from creatorlab.sample_data import sample_rows
        analysis_rows = sample_rows(platform)
    else:
        analysis_rows = rows
    views=['直观看表现','详细数据','作品对比','学习外部作品','账号总览']
    labels=dict(zip(views,['战力图','数据详情','作品对比','外部参照','账号总览']))
    if platform=='bilibili':
        views.insert(1,'每周必看')
        labels['每周必看']=':material/star: 每周必看'
    if st.session_state.get('work_view') not in views:st.session_state.work_view=views[0]
    def switch_analysis():
        # Keep the selected work when moving between its chart and full report.
        target=st.session_state.work_view
        source='hero_work' if target=='详细数据' else 'report_work' if target=='直观看表现' else None
        destination='report_work' if target=='详细数据' else 'hero_work'
        selected=st.session_state.get(source) if source else None
        if selected in {r['id'] for r in analysis_rows}:st.session_state[destination]=selected
    st.subheader('看作品')
    view=st.segmented_control('作品分析方式',views,format_func=labels.get,key='work_view',
                              required=True,label_visibility='collapsed',on_change=switch_analysis,wrap=True)
    if view=='直观看表现':
        from creatorlab.personal_ui import hero
        hero(rows,db,platform,compact=True)
    elif view=='每周必看':
        from creatorlab.optional_ui import weekly_panel
        weekly_panel(rows,key='weekly_compare')
    elif view=='详细数据':
        from creatorlab.report_ui import report
        report(analysis_rows,db,demo=demo)
        if st.button('返回战力图',key='work_back_from_report'):
            route(WORK,work_view='直观看表现',hero_work=st.session_state.get('report_work'))
    elif view=='作品对比':
        from creatorlab.personal_ui import quick_compare
        quick_compare(rows)
    elif view=='账号总览':
        from creatorlab.studio_ui import overview
        overview(rows,db,platform,ctx['root'])
    else:
        st.subheader('学习外部作品')
        st.caption('先选择学习对象，再核对它与你的内容是否可比；外部样本不代表全站。')
        if rows:
            from creatorlab.personal_ui import scope
            from creatorlab.challenge_ui import peer_panel
            peer_panel(scope(rows,'challenge'),db)
        else:st.info('导入自己的作品后，再核对同平台的外部参照。')


def create_page():
    ctx=context();rows=ctx['rows'];db=ctx['db']
    st.subheader('做下一条')
    st.caption('选一个当前要完成的任务。一次只处理一件事。')
    steps=['准备创作','检查视频','记录与复盘']
    if st.session_state.get('create_step') not in steps:st.session_state.create_step=steps[0]
    step=st.segmented_control('我现在要做',steps,key='create_step')
    if not rows:
        st.info('先同步几条作品，建议才能关联你的真实数据。')
        if st.button('去同步作品',type='primary'):route(SETTINGS,settings_view='同步与进度')
        return
    if step=='准备创作':
        from creatorlab.content_ui import select_scope
        from creatorlab.creative_brief_ui import planning_panel
        scoped,metric=select_scope(rows,'assistant')
        planning_panel(scoped,metric,guided=True)
    elif step=='检查视频':
        st.caption('先在本机找回看片段，再由你选择是否让AI细看。')
        from creatorlab.personal_ui import scope
        from creatorlab.materials import panel
        panel(db,scope(rows,'video_check'),'none')
    else:
        from creatorlab.personal_ui import scope
        from creatorlab.loop_ui import experiment_panel
        scoped=scope(rows,'review')
        st.caption('关联改动前后的作品，用相同观察窗口记录结果。')
        experiment_panel(db,scoped,'views',compact=True)
    with st.expander('其他创作工具'):
        tool=st.selectbox('按需要打开',['暂不打开','发布与标题规律','跨平台内容关联','分类与深入分析'],key='workspace_creation_tool')
        if tool=='发布与标题规律':
            from creatorlab.insight_ui import panel
            panel(rows)
        elif tool=='跨平台内容关联':
            from creatorlab.project_ui import project_panel
            project_panel(db,ctx['global_rows'])
        elif tool=='分类与深入分析':
            from creatorlab.content_ui import analysis_dashboard
            analysis_dashboard(rows)


def library_page():
    ctx=context()
    st.caption('查找作品、打开报告，或勾选两三条进行对比。')
    from creatorlab.creator_ui import library
    library(ctx['rows'],ctx['db'],compact=True)


def settings_page():
    ctx=context();db=ctx['db'];root=ctx['root'];platform=ctx['platform']
    st.subheader('同步与设置')
    view=st.selectbox('需要处理什么',['同步与进度','账号与文件导入','备份与诊断','使用帮助'],key='settings_view')
    if view=='同步与进度':
        st.write('同步后的作品会出现在“作品库”，随后到“看作品”复盘。')
        from creatorlab.task_feedback import panel as task_feedback_panel
        task_feedback_panel(db,root,platform)
        if platform=='douyin':
            from creatorlab.douyin_ui import sidebar_panel,review_captures
            sidebar_panel(db,root,host=st)
            from creatorlab.auto_update_ui import panel as automatic_update_panel
            automatic_update_panel(db,root)
            review_captures(db,root)
        else:
            from creatorlab.bilibili_ui import import_panel
            import_panel(db,root,host=st,show_status=False)
        from creatorlab.task_ui import task_center
        with st.expander('任务详情与缺项补采'):
            task_center(db,root,platform,show_review=platform!='douyin')
        if st.button('添加账号或导入文件',key='settings_add_account'):
            route(SETTINGS,settings_view='账号与文件导入',settings_import_method=None)
    elif view=='账号与文件导入':
        from creatorlab.hub import accounts
        from creatorlab.account_ui import account_forms
        accs=[a for a in accounts(db) if a['is_self'] and a['platform']==platform]
        account_forms(db,root,platform,accs,method=st.session_state.get('settings_import_method'))
    elif view=='备份与诊断':
        from creatorlab.usability_ui import maintenance_panel
        maintenance_panel(db,root)
        with st.expander('其他平台CSV记录（实验）'):
            from creatorlab.insight_ui import other_platforms
            other_platforms(db)
    else:
        st.markdown('### 第一次使用，只做三步')
        st.markdown('1. **同步作品**：先把抖音或B站作品放进本机作品库。\n2. **看作品**：选一条，先看战力图与右侧的直观结论。\n3. **做下一条**：只选一处改动，记录后续作品再复盘。')
        with st.expander('每个功能在哪儿？'):
            st.table([{'想做的事':'详细报告／作品对比／外部参照','入口':'看作品 → 顶部横向分析导航'},
                      {'想做的事':'本地视频检测／可选AI','入口':'做下一条 → 检查视频'},
                      {'想做的事':'创作实验／固定窗口复盘','入口':'做下一条 → 记录与复盘'},
                      {'想做的事':'发布规律／跨平台关联／深入分析','入口':'做下一条 → 其他创作工具'},
                      {'想做的事':'CSV／手动作品／旧记录导入','入口':'同步与设置 → 账号与文件导入'}])
        with st.expander('验收与详细使用边界'):
            from creatorlab.acceptance import panel
            panel(db,platform)
        st.caption('数据保存在本机。默认参照全部有效历史作品；缺失不补零，AI需要你主动选择后才使用。')
