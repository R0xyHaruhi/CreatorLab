from streamlit.testing.v1 import AppTest


def test_library_reset_sends_cleared_text_to_the_browser(tmp_path):
    from creatorlab.hub import init_hub,add_account,upsert_post
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    upsert_post(db,aid,'第一条','one',metrics={'views':100})
    upsert_post(db,aid,'第二条','two',metrics={'views':200})
    app=AppTest.from_string('import streamlit as st\nst.session_state.active_platform="bilibili"\nfrom creatorlab.hub import latest_posts\nfrom creatorlab.creator_ui import library\nlibrary(latest_posts('+repr(str(db))+'),'+repr(str(db))+')',default_timeout=20).run()
    app.text_input(key='library_search').set_value('第一').run()
    assert app.selectbox(key='library_detail__bilibili').value==1
    assert app.selectbox(key='library_detail__bilibili').proto.set_value is True
    app.button(key='library_reset').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.text_input(key='library_search').value==''
    # The server must explicitly update the React input, not only its own model.
    assert app.text_input(key='library_search').proto.set_value is True
    app.selectbox(key='library_order__bilibili').set_value('播放量最高').run()
    assert app.text_input(key='library_search').value==''
    assert any('找到 2 / 2' in c.value for c in app.caption)
