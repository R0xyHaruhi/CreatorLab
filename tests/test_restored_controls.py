import json
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.appearance import PALETTES
from creatorlab.hub import init_hub,add_account,upsert_post


def seed(db,published='2026-01-01'):
    init_hub(db)
    for platform in ['douyin','bilibili']:
        aid=add_account(db,platform,'123456' if platform=='bilibili' else 'me',platform)
        for i in range(8):
            upsert_post(db,aid,platform+f'作品{i}',str(1234567890123456780+i),published,metrics={'views':1000+i*200,'likes':20+i*7,'completion_rate':.2+i*.03})


def test_controls_platform_scope_and_unclassified_charts(tmp_path,monkeypatch):
    db=tmp_path/'d.db';seed(db);monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    assert not app.exception
    assert app.get('plotly_chart')
    app.switch_page('app_pages/create.py').run()
    app.selectbox(key='workspace_creation_tool').set_value('分类与深入分析').run()
    assert len(app.get('plotly_chart'))>=4
    app.radio(key='clab_appearance').set_value('暖灰浅色').run()
    assert not app.exception
    light_palette=PALETTES['暖灰浅色']
    assert all(json.loads(c.proto.spec)['layout']['paper_bgcolor'] in (light_palette['bg'],light_palette['panel']) for c in app.get('plotly_chart'))
    app.radio(key='platform_space').set_value('B站空间').run()
    assert not app.exception
    assert app.selectbox(key='analysis_account').options==['bilibili · B站']
    assert all('bilibili' in label for label in app.selectbox(key='assistant_workflow_target__bilibili').options)
    assert not any(x.label=='打开抖音同步窗口' for x in app.button)
    app.radio(key='clab_appearance').set_value('柔和深色').run()
    assert not app.exception
    assert all(json.loads(c.proto.spec)['layout']['paper_bgcolor'] in ('#17191B','#202326') for c in app.get('plotly_chart'))
    app.radio(key='platform_space').set_value('抖音空间').run()
    assert not app.exception
    assert app.selectbox(key='analysis_account').options==['douyin · 抖音']


@pytest.mark.parametrize('published',[None,'2099-01-01'])
def test_no_mature_records_still_show_observed_charts(tmp_path,monkeypatch,published):
    db=tmp_path/'d.db';seed(db,published);monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    assert not app.exception
    assert app.get('plotly_chart')
