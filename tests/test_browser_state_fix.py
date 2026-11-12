from streamlit.testing.v1 import AppTest
from creatorlab.report_ui import formatted


def test_platforms_use_distinct_browser_widget_identity_and_model_alias():
    code='''
import streamlit as st
from creatorlab.feedback import scoped_selectbox,reset_platform_state
platform=st.radio('平台',['douyin','bilibili'],key='platform')
reset_platform_state(platform)
st.session_state.active_platform=platform
if st.button('打开第二条'):st.session_state.hero_work=2
scoped_selectbox('作品',[1,2],key='hero_work',format_func=lambda i:platform+str(i))
'''
    app=AppTest.from_string(code).run()
    first=app.selectbox(key='hero_work__douyin').proto.id
    app.radio(key='platform').set_value('bilibili').run()
    second=app.selectbox(key='hero_work__bilibili').proto.id
    assert first!=second
    assert app.session_state['hero_work']==1
    assert not any(s.key=='hero_work__douyin' for s in app.selectbox)
    app.button[0].click().run()
    assert app.selectbox(key='hero_work__bilibili').value==2
    assert app.session_state['hero_work']==2
    app.selectbox(key='hero_work__bilibili').set_value(1).run()
    assert app.session_state['hero_work']==1


def test_observed_small_nonzero_ratio_is_never_shown_as_zero():
    assert formatted(278/686900,'rate')=='0.04%'
    assert formatted(1/1000000,'rate')=='<0.01%'
    assert formatted(0,'rate')=='0.00%'
    assert formatted(None,'rate')=='—'
