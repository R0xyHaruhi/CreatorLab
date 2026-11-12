from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post
from creatorlab.platforms import goals


def test_platform_goals_use_separate_metric_vocabularies():
    dy={v[0] for v in goals('douyin').values()};bi={v[0] for v in goals('bilibili').values()}
    assert 'completion_rate' in dy and not {'coin_ratio','danmaku_ratio'}&dy
    assert {'coin_ratio','danmaku_ratio'}<=bi and 'completion_rate' not in bi


def test_switch_spaces_separates_works_controls_and_analysis_goals(tmp_path,monkeypatch):
    db=tmp_path/'d.db';init_hub(db)
    for platform in ('douyin','bilibili'):
        aid=add_account(db,platform,'123',platform)
        for i in range(5):upsert_post(db,aid,platform+'作品'+str(i),platform+str(i),'2026-01-01T00:00:00Z',metrics={'views':100+i*100,'likes':20,'comments':2,'favorites':3,'shares':1,'coins':2,'danmaku':4,'completion_rate':.4},observed_at='2026-02-01T00:00:00Z')
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.radio(key='platform_space').options==['抖音空间','B站空间']
    assert all('douyin' in s for s in app.selectbox(key='hero_work__douyin').options)
    app.switch_page('app_pages/create.py').run()
    app.selectbox(key='workspace_creation_tool').set_value('分类与深入分析').run()
    assert '让观众多看一会儿' in app.selectbox(key='analysis_goal').options
    assert '让观众更愿意投币' not in app.selectbox(key='analysis_goal').options
    app.radio(key='platform_space').set_value('B站空间').run()
    assert not app.exception,[e.message for e in app.exception]
    app.switch_page('app_pages/works.py').run()
    assert all('bilibili' in s for s in app.selectbox(key='hero_work__bilibili').options)
    app.switch_page('app_pages/create.py').run()
    app.selectbox(key='workspace_creation_tool').set_value('分类与深入分析').run()
    assert '让观众多看一会儿' not in app.selectbox(key='analysis_goal').options
    assert '让观众更愿意发弹幕' in app.selectbox(key='analysis_goal').options
    assert not any(b.label=='打开抖音同步窗口' for b in app.button)
    app.session_state['settings_view']='账号与文件导入'
    app.switch_page('app_pages/settings.py').run()
    assert app.text_input(key='manual_coins')
    assert not any(t.key=='manual_completion_rate' for t in app.text_input)
