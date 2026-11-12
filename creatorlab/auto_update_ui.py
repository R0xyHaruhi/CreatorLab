"""A single opt-in control; credentials remain in existing local browser profiles."""
import threading
import time
from datetime import datetime
import streamlit as st
from creatorlab.auto_update import load,configure,eligible_ids,service_loop


@st.cache_resource(show_spinner=False)
def _service(db,root):
    stop=threading.Event()
    thread=threading.Thread(target=service_loop,args=(db,root,stop),name='CreatorLab automatic update',daemon=True)
    thread.start()
    return stop


def ensure_service(db,root):
    active=any(x.get('enabled') for x in load(db).values())
    if active:_service(str(db),str(root))
    return active


@st.fragment(run_every='30s')
def watch_updates(db):
    signature=tuple(sorted((k,v['last_success']) for k,v in load(db).items() if v.get('last_success')))
    old=st.session_state.get('_auto_update_seen')
    st.session_state['_auto_update_seen']=signature
    if old is not None and signature!=old:
        st.toast('已自动刷新作品数据')
        st.rerun()


def panel(db,root):
    from creatorlab.hub import accounts
    own=[a for a in accounts(db) if a['platform']=='douyin' and a['is_self']]
    if not own:return
    with st.expander('自动更新已入库作品'):
        aid=st.selectbox('自动更新哪个账号',[a['id'] for a in own],format_func=lambda i:next(a['display_name'] for a in own if a['id']==i),key='auto_update_account')
        item=load(db).get(str(aid),{})
        st.write('启用一次，以后按间隔在后台刷新已核对的作品，无需每天点击同步。')
        st.info('**工作台启动窗口需保持运行，网页可以关闭。**\n\n退出程序或电脑关机后不再安排更新；正在执行的一轮可能完成。')
        st.markdown('**启用前须知**\n\n'
                    '- **更新频率**：默认每天一次，可选每6或12小时；首次保存后一分钟内开始。\n'
                    '- **更新范围**：只刷新已核对入库的抖音作品；新作品仍需单独同步。\n'
                    '- **暂停与恢复**：登录失效或遇到验证码时暂停。先手动同步完成登录／验证，再回这里保存设置恢复。')
        st.caption(f'当前可自动更新 {len(eligible_ids(db,aid))} 条已核对作品。账号归属不明的作品须先手动确认。')
        with st.form('automatic_update_'+str(aid)):
            enabled=st.toggle('启用自动更新',value=item.get('enabled',False))
            options=[24,12,6]
            hours=st.selectbox('更新间隔',options,index=options.index(item.get('hours',24)),format_func=lambda n:'每天一次' if n==24 else f'每{n}小时')
            if st.form_submit_button('保存自动更新设置',type='primary'):
                try:
                    configure(db,aid,enabled,hours)
                    ensure_service(db,root)
                    st.success('已保存。首次更新将在一分钟内开始。' if enabled else '已关闭自动更新。')
                except ValueError as exc:st.error(str(exc))
        current=load(db).get(str(aid),{})
        if current.get('paused'):st.warning(current.get('message','自动更新已暂停'))
        elif current.get('lease_until') and current['lease_until']<time.time():st.warning('上次后台任务未正常结束；下一周期会重试，已有数据保留。')
        elif current.get('message'):st.caption(current['message'])
        if current.get('last_success'):st.caption('上次成功：'+datetime.fromtimestamp(current['last_success']).strftime('%Y-%m-%d %H:%M'))
        if current.get('enabled') and not current.get('paused') and current.get('next_at'):st.caption('下次计划：'+datetime.fromtimestamp(current['next_at']).strftime('%Y-%m-%d %H:%M'))
        if current.get('paused'):
            st.caption('请先手动同步完成登录、验证或归属核对，再点保存设置恢复。')
        if st.button('刷新自动更新状态',key='auto_update_status'):st.rerun()
