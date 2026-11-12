"""An incomplete optional feature must not stop the main workspace."""
import streamlit as st


def weekly_panel(rows, key):
    try:
        from creatorlab.weekly_ui import panel
    except ModuleNotFoundError as exc:
        if exc.name not in ('creatorlab.weekly_ui','creatorlab.weekly_reference'):raise
        st.error('精选参照模块安装不完整。请关闭CLab，将2.6.1修复覆盖包全部解压到app.py所在目录。个人数据不用删除。')
        return
    panel(rows,key=key)
