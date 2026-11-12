from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post
from creatorlab.genres import genre_rows
from creatorlab.growth import experiments


def test_growth_manual_classification_and_challenge_persist(tmp_path,monkeypatch):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    for i in range(6):upsert_post(db,aid,'Python教程'+str(i),str(i),'2026-01-01',metrics={'views':100+i*100,'likes':20,'coins':5})
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    app.switch_page('app_pages/create.py').run()
    app.selectbox(key='workspace_creation_tool').set_value('分类与深入分析').run()
    assert not app.exception
    assert any(t.label=='🎮 成长面板' for t in app.tabs)
    assert any(t.label=='作品画像' for t in app.tabs)
    assert any('scatterpolar' in p.proto.spec for p in app.get('plotly_chart'))
    app.selectbox(key='genre_major__bilibili').set_value('科技区').run()
    app.selectbox(key='genre_minor__bilibili').set_value('编程开发').run()
    multi=app.multiselect(key='genre_ids')
    multi.set_value([1,2,3,4,5])
    app.button(key='FormSubmitter:genre_canonical-确认赛道').click().run()
    assert not app.exception
    from creatorlab.hub import latest_posts
    assert sum(r['genre'] is not None for r in genre_rows(db,latest_posts(db)))==5
    next(t for t in app.text_input if t.label=='挑战名称').set_value('测试新开头')
    next(t for t in app.text_area if t.label=='这次只改什么，为什么？').set_value('把结果放在第一秒')
    next(b for b in app.button if b.label=='接受这个挑战').click().run()
    assert not app.exception
    assert experiments(db,aid)[0]['title']=='测试新开头'
