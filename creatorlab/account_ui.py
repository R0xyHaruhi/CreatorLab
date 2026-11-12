"""Existing account/import forms, shown only when the user requests them."""
import pandas as pd
import streamlit as st
from creatorlab.hub import add_account,upsert_post,import_csv,import_douyin_existing,validate_publication_date
from creatorlab.feedback import notify


def account_forms(DB,ROOT,active_platform,accs,method=None):
    if method in ('csv', 'manual'):
        st.markdown('**导入 CSV**' if method=='csv' else '**手动录入**')
        if not accs:
            st.caption('先添加一个账号，保存后即可继续当前导入。')
    if active_platform=='bilibili':
        with st.expander('查看B站账号统计'):
            from creatorlab.bilibili_account import account_dashboard
            account_dashboard(DB,accs)
    with st.expander('再添加一个账号') if accs else st.container():
        st.subheader('添加平台账号')
        with st.form('account'):
            platform=st.selectbox('平台',[active_platform] if active_platform else ['douyin','bilibili'],format_func=lambda p:'抖音' if p=='douyin' else 'B站')
            handle=st.text_input('账号标识（选填）' if active_platform=='douyin' else 'B站 UID / 空间链接',placeholder='抖音可留空，只填昵称即可' if active_platform=='douyin' else '填写自己的UID或空间链接')
            display_name=st.text_input('账号昵称（选填）')
            if st.form_submit_button('保存账号'):
                try:
                    if platform=='douyin' and not handle.strip():
                        if not display_name.strip():raise ValueError('请填写一个便于区分的账号昵称')
                        import uuid
                        handle='local-'+uuid.uuid4().hex[:12]
                    elif platform=='bilibili':
                        from creatorlab.bilibili_import import parse_uid
                        handle=parse_uid(handle)
                    aid=add_account(DB,platform,handle,display_name)
                    from creatorlab.hub import connect
                    with connect(DB) as con:con.execute('UPDATE hub_accounts SET is_self=1 WHERE id=?',(aid,))
                    st.session_state['settings_import_account'] = aid
                    if method=='sync' and '_workspace_context' in st.session_state:
                        from creatorlab.workspace import route,SETTINGS
                        values={'dy_target_account':aid} if platform=='douyin' else {'bili_import_uid':handle}
                        notify('账号已保存，可以开始同步作品。')
                        route(SETTINGS,settings_view='同步与进度',settings_import_method=None,**values)
                    notify('账号已保存，可以继续导入作品。')
                    st.rerun()
                except ValueError as e:st.error(str(e))
    if accs:
        st.divider()
        st.subheader('导入作品')
        by_id = {account['id']: account for account in accs}
        account_key = 'settings_import_account'
        if st.session_state.get(account_key) not in by_id:
            st.session_state.pop(account_key, None)
        aid = st.selectbox('导入到哪个账号',list(by_id),format_func=lambda i:by_id[i]['display_name'],key=account_key)
        acc = by_id[aid]
        recent = st.session_state.get('settings_import_recent') or {}
        if recent.get('account_id')==aid and recent.get('ids'):
            if st.button('查看刚导入的作品', key='settings_import_view', type='primary'):
                from creatorlab.workspace import route, LIBRARY
                route(LIBRARY, library_import_ids=recent['ids'], library_account=aid,
                      library_search='', library_time='全部时间', library_quality='全部', library_page=1)
        if method!='csv':
            with st.expander('手动添加一条作品',expanded=method=='manual'):
                _manual_entry(DB, acc)
        if method!='manual':
            _csv_entry(DB, acc)
        if acc['platform']=='douyin' and method is None:
            with st.expander('迁移旧版抖音采集记录'):
                st.caption('把旧版创作者中心导入表中的真实作品同步进统一作品库。再次操作按视频 ID 更新，并保存新快照。不会混入原有模拟 CSV。')
                claim=st.checkbox('我已核对旧采集记录全部属于上方所选抖音账号',key='legacy_claim')
                if st.button('导入现有抖音作品记录',disabled=not claim):
                    try:n=import_douyin_existing(DB,acc['id'],DB);notify(f'已处理 {n} 条作品。');st.rerun()
                    except Exception as e:st.error(f'同步失败：{e}')
                st.caption('继续使用现有 Chrome 扩展采集时，需要启动本地接收服务；旧版「作品管理」也仍可查看原始导入结果。')
    else:st.info('添加账号后即可导入作品。')


def _manual_entry(db, acc):
    with st.form('new_post'):
        title=st.text_input('作品名称 / 标题')
        external_id=st.text_input('视频 ID / BV 号（选填，便于去重）')
        published_at=st.text_input('发布时间（选填）',placeholder='2026-10-26T12:00:00+08:00')
        date_error=st.empty()
        url=st.text_input('作品链接（选填）')
        c1,c2=st.columns(2)
        view=c1.text_input('播放量（留空表示未知）')
        like=c2.text_input('点赞量（留空表示未知）')
        extras={}
        fields=[('comments','评论量'),('shares','分享量'),('favorites','收藏量')]+([('coins','投币量'),('danmaku','弹幕量')] if acc['platform']=='bilibili' else [('completion_rate','完播率，例如35%'),('bounce_rate_2s','2秒跳出率，例如20%'),('avg_view_second','平均观看时长（秒）')])
        for field,label in fields:
            extras[field]=st.text_input(label+'（可留空）',key='manual_'+field)
        manual_observed=st.text_input('指标实际采集时间（留空=当前，历史时间需含时区）',key='manual_observed_at')
        if st.form_submit_button('保存作品'):
            try:
                published_at=validate_publication_date(published_at)
            except ValueError as exc:
                date_error.error(str(exc))
                return
            try:
                pid=upsert_post(db,acc['id'],title,external_id,published_at,url,
                                {'views':view,'likes':like,**extras},source='manual',observed_at=manual_observed or None)
                st.session_state['settings_import_recent']=dict(account_id=acc['id'],ids=[pid])
                notify('作品已保存。');st.rerun()
            except ValueError as e:st.error(str(e))


def _csv_entry(db, acc):
    st.subheader('批量导入 CSV')
    st.caption('支持抖音、B站作品表格；无需提供密码。每一行一条作品，title 必填；可选 external_id、views、likes、comments、shares、favorites、published_at、url。')
    extra_fields='coins,danmaku' if acc['platform']=='bilibili' else 'completion_rate,completion_rate_5s,bounce_rate_2s,avg_view_second'
    template='title,external_id,published_at,observed_at,url,views,likes,comments,shares,favorites,'+extra_fields+',cover_url,track,category,topic,duration_seconds\n'
    st.caption('固定窗口需要published_at与observed_at包含时分和时区，例如2026-10-26T12:00:00+08:00；未填observed_at的旧CSV只作累计记录。')
    st.download_button('下载 CSV 模板',template.encode('utf-8-sig'),'clab_import_template.csv','text/csv')
    upload=st.file_uploader('选择 CSV 文件',type=['csv'])
    if upload is not None:
        try:
            from creatorlab.hub import preview_csv
            plan=preview_csv(db,acc['id'],upload.getvalue())
            st.caption(f"共{len(plan['rows'])}行 · 更新{plan['updates']}条 · 新增{len(plan['rows'])-plan['updates']}条")
            st.table(pd.DataFrame(plan['rows'][:5]).rename(columns={'title':'标题','external_id':'视频ID','views':'播放','likes':'点赞','published_at':'发布时间'}))
            if plan['missing_ids']:st.warning('有作品未填写视频ID：重复导入不同文件时不能自动判断是否为同一作品。')
            if plan['duplicate']:st.info('这个账号已导入过同一份文件，无需重复导入。')
            elif st.button('确认导入 CSV',type='primary',disabled=not plan['rows']):
                ids=import_csv(db,acc['id'],upload.getvalue(),return_ids=True)
                st.session_state['settings_import_recent']=dict(account_id=acc['id'],ids=ids)
                notify(f'成功处理 {len(ids)} 条作品。');st.rerun()
        except (ValueError,UnicodeDecodeError) as e:
            st.error(str(e))
            raw=upload.getvalue()[:4096]
            try:preview=raw.decode('utf-8-sig')
            except UnicodeDecodeError:preview=raw.decode('gb18030',errors='replace')
            with st.expander('查看原文件开头',expanded=True):
                st.text('\n'.join(preview.splitlines()[:6]))

