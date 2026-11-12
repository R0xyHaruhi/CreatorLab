from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post


def test_fixed_7d_view_and_small_sample_guide_are_usable(tmp_path,monkeypatch):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    for i in range(3):
        upsert_post(db,aid,'作品'+str(i),str(i),'2026-01-01T00:00:00Z',metrics={'views':100+i*100,'likes':10+i},observed_at='2026-01-08T00:00:00Z')
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    app.switch_page('app_pages/create.py').run()
    app.selectbox(key='workspace_creation_tool').set_value('分类与深入分析').run()
    assert not app.exception
    assert any('今天先做这三件事' in x.value for x in app.markdown)
    app.radio(key='analysis_window').set_value('7天').run()
    assert not app.exception,[e.message for e in app.exception]
    assert any('7天观测' in c.value for c in app.caption)
    assert any('scatterpolar' in c.proto.spec for c in app.get('plotly_chart'))
