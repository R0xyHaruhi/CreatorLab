"""Guided first import and recoverable local settings."""
from pathlib import Path
import streamlit as st
from creatorlab.hub import accounts,add_account


def first_import(db,platform):
    own=[a for a in accounts(db) if a['platform']==platform and a['is_self']]
    st.markdown('### 导入第一批作品')
    method = st.segmented_control('选择导入方式', ['平台同步', '导入 CSV', '手动录入'],
                                  default='平台同步', required=True, key='first_import_method')
    if method != '平台同步':
        from creatorlab.workspace import route, SETTINGS
        route(SETTINGS, settings_view='账号与文件导入',
              settings_import_method='csv' if method=='导入 CSV' else 'manual')
    st.write('**添加账号 → 同步并确认 → 看作品。**')
    st.caption('还不想登录？下方“先看可视化示例”可以直接体验，示例不会写进你的作品库。')
    if not own:
        with st.form('first_account'):
            name=st.text_input('账号昵称',placeholder='方便区分本机账号')
            uid=st.text_input('B站UID或空间链接') if platform=='bilibili' else None
            if st.form_submit_button('添加账号',type='primary'):
                try:
                    if not name.strip():raise ValueError('请填写一个用于区分账号的昵称')
                    if platform=='bilibili':
                        from creatorlab.bilibili_import import parse_uid
                        handle=parse_uid(uid)
                    else:
                        import uuid
                        handle='local-'+uuid.uuid4().hex[:12]
                    add_account(db,platform,handle,name);st.rerun()
                except ValueError as exc:st.error(str(exc))
        return
    aid=st.selectbox('导入到哪个账号',[a['id'] for a in own],format_func=lambda i:next(a['display_name'] for a in own if a['id']==i),key='first_import_account')
    if platform=='douyin':
        from creatorlab.douyin_capture import pending_captures
        if pending_captures(db):
            st.info('作品已经读到，还差归属确认，不需要重新采集。')
            if st.button('去确认已采集的作品',key='first_review'):
                from creatorlab.workspace import route,SETTINGS
                route(SETTINGS,settings_view='同步与进度')
            return
        from creatorlab.douyin_ui import actions
        actions(db,key='first_dy',account_id=aid)
    else:
        from creatorlab.bilibili_ui import launch_import
        from creatorlab.bilibili_import import job_running
        root=Path(__file__).resolve().parents[1]
        if st.button('导入B站作品',key='first_bili_start',type='primary',disabled=job_running(root)):
            try:launch_import(db,root,next(a['handle'] for a in own if a['id']==aid));st.toast('请在窗口中完成必要的登录或验证')
            except (ValueError,OSError) as exc:st.error(str(exc))
        if st.button('刷新作品',key='first_bili_refresh'):st.rerun()


def maintenance_panel(db,root):
    collection_health_panel(db)
    from creatorlab.maintenance import export_backup,restore_backup,diagnostics,clear_profiles
    from creatorlab.bilibili_import import job_running
    running=job_running(root) or job_running(root,'douyin')
    st.markdown('### 环境检查')
    if st.button('检查Python、浏览器与可选组件',key='environment_check'):
        from creatorlab.maintenance import environment_report
        st.session_state['environment_check_result']=environment_report()
    if st.session_state.get('environment_check_result'):
        st.table(st.session_state['environment_check_result'])
    from creatorlab.maintenance import database_gate
    installing=False
    try:
        with database_gate(Path(root)/'local'/'browser-install',timeout=.05):pass
    except RuntimeError:installing=True
    if st.button('安装或修复导入浏览器',key='install_browser',disabled=running or installing):
        import subprocess,sys
        subprocess.Popen([sys.executable,'-m','creatorlab.browser_setup'],cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        st.info('安装已启动；安装结果可刷新下方查看。')
    import json
    try:
        status=json.loads((Path(root)/'local'/'browser_install_status.json').read_text())
        st.caption('上次安装已中断，可重试' if status.get('state')=='installing' and not installing else status.get('info',''))
    except (OSError,ValueError):pass
    if st.button('刷新环境结果',key='environment_refresh'):st.rerun()
    st.markdown('### 备份与恢复')
    st.caption('备份包含所有平台账号的作品、分类、封面和实验，不包含浏览器登录目录。每天首次打开自动备份，保留最近7份每日备份；升级和恢复前另存保护副本。')
    if st.button('生成完整数据备份',key='backup_create',disabled=running):
        try:st.session_state['database_backup_download']=export_backup(db)
        except (ValueError,RuntimeError,OSError) as exc:st.error(str(exc))
    if st.session_state.get('database_backup_download'):
        st.download_button('下载数据备份',st.session_state['database_backup_download'],'CLab-data-backup.zip','application/zip',key='backup_download')
    with st.expander('从备份恢复'):
        upload=st.file_uploader('选择CLab备份ZIP',type=['zip'],key='backup_restore_file')
        confirmed=st.checkbox('我确认恢复将替换当前作品、分类和实验，程序会先保留当前数据副本',key='backup_restore_confirm')
        if st.button('校验并恢复备份',key='backup_restore',disabled=running or upload is None or not confirmed):
            try:
                restore_backup(db,upload.getvalue());st.session_state.clear();st.rerun()
            except (ValueError,RuntimeError,OSError) as exc:st.error(str(exc))
    st.markdown('### 诊断')
    st.caption('报告只含版本、数量、字段覆盖与任务状态；不包含作品标题、账号ID、Cookie、密钥或原始日志。')
    if st.button('生成脱敏诊断报告',key='diagnostics_create'):
        try:st.session_state['diagnostics_download']=diagnostics(db,root)
        except (RuntimeError,OSError) as exc:st.error(str(exc))
    if st.session_state.get('diagnostics_download'):
        st.download_button('下载诊断报告',st.session_state['diagnostics_download'],'CLab-diagnostics.json','application/json',key='diagnostics_download_button')
    with st.expander('清除浏览器登录状态'):
        platform=st.selectbox('清除哪个平台',['douyin','bilibili'],format_func=lambda p:'抖音' if p=='douyin' else 'B站',key='clear_login_platform')
        checked=st.checkbox('我确认清除本机该平台的采集浏览器登录状态，下次需要重新登录',key='clear_login_confirm')
        if st.button('清除登录状态',key='clear_login',disabled=not checked or running):
            try:clear_profiles(root,platform);st.success('登录状态已清除，作品数据保留。')
            except (ValueError,OSError) as exc:st.error(str(exc))


def collection_health_panel(db):
    from creatorlab.collect_health import recent_drift,export_report
    from creatorlab.hub import latest_posts
    from creatorlab.collect_health import assess_rows
    with st.expander('采集结构预警'):
        items=recent_drift(db)
        if not items:st.caption('暂未记录未知响应结构。这不代表采集已验收或全部字段可用。')
        else:
            st.warning('有响应结构未能识别；未知列表未自动导入。')
            st.dataframe([{'时间':r['seen_at'],'平台':r['platform'],'来源':r['endpoint']} for r in items],hide_index=True)
            st.download_button('下载脱敏结构报告',export_report(db),'clab_structure.json','application/json')
        rows=latest_posts(db)
        groups={}
        for row in rows:groups.setdefault((row['platform'],row['account_id']),[]).append(row)
        for (platform,aid),group in groups.items():
            for issue in assess_rows(group):st.caption(f'{platform} / 账号{aid}：'+issue['message'])
