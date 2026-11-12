"""CreatorLab: four focused tasks, rendered on demand."""
import os
from pathlib import Path
import streamlit as st
from creatorlab.hub import init_hub,accounts,latest_posts
from creatorlab.feedback import reset_platform_state,show_notices
from creatorlab.workspace import consume_route

st.set_page_config(page_title='CreatorLab',page_icon='🎬',layout='wide')
ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('CREATORLAB_DB',str(ROOT/'local'/'creatorlab.db')))
try:
    init_hub(DB)
    from creatorlab.maintenance import daily_backup
    daily_backup(DB)
except Exception as exc:
    st.error('数据初始化未完成，已停止继续写入。请关闭采集窗口后重试，或从保护副本恢复。')
    st.caption(str(exc));st.stop()

available={a['platform'] for a in accounts(DB) if a['is_self']}
from creatorlab.auto_update_ui import ensure_service,watch_updates
if ensure_service(DB,ROOT):watch_updates(DB)
platform_space=st.sidebar.radio('当前平台',['抖音空间','B站空间'],index=1 if available=={'bilibili'} else 0,key='platform_space',horizontal=True)
active_platform={'抖音空间':'douyin','B站空间':'bilibili'}[platform_space]
reset_platform_state(active_platform)
st.session_state['active_platform']=active_platform
from creatorlab.appearance import setup,platform_header
with st.sidebar.expander('外观'):
    setup(active_platform,host=st)
page=st.navigation([
    st.Page('app_pages/works.py',title='看作品',icon=':material/insights:',default=True),
    st.Page('app_pages/create.py',title='做下一条',icon=':material/edit_note:'),
    st.Page('app_pages/library.py',title='作品库',icon=':material/video_library:'),
    st.Page('app_pages/settings.py',title='同步与设置',icon=':material/sync:'),
])
st.sidebar.caption('看作品 → 选一处改动 → 用下一条验证')
st.sidebar.caption('个人空间 · 数据保存在本机')
platform_header(active_platform)
show_notices()
global_rows=latest_posts(DB)
rows=[r for r in global_rows if r['platform']==active_platform]
st.session_state['_workspace_context']={'db':DB,'root':ROOT,'platform':active_platform,'rows':rows,'global_rows':global_rows}
destination=consume_route(st.session_state)
if destination:st.switch_page(destination)
page.run()
