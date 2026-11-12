from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.growth import save_experiment,experiments
from creatorlab.review_loop import link_experiment


def test_real_window_experiment_evaluation_is_visible(tmp_path,monkeypatch):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    before=upsert_post(db,aid,'原做法','a','2026-01-01T00:00:00Z',metrics={'views':100},observed_at='2026-01-08T00:00:00Z')
    after=upsert_post(db,aid,'新做法','b','2026-01-02T00:00:00Z',metrics={'views':150},observed_at='2026-01-09T00:00:00Z')
    eid=save_experiment(db,aid,'实验一','只改开头','views');link_experiment(db,eid,aid,[before],[after],'7天')
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    app.switch_page('app_pages/create.py').run()
    app.selectbox(key='workspace_creation_tool').set_value('分类与深入分析').run()
    assert not app.exception,[e.message for e in app.exception]
    assert any('可以复盘' in x.value for x in app.markdown)
    assert experiments(db,aid)[0]['baseline_value']==100


def test_window_30d_boundary_is_not_split_into_different_cohorts(tmp_path):
    import pandas as pd
    from creatorlab.content_analysis import frame
    from creatorlab.measurements import window_rows
    from creatorlab.growth import radar_scores
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    for i in range(5):
        # Both -12h and +12h observations are inside the same 30-day tolerance.
        observed='2026-01-30T12:00:00Z' if i%2 else '2026-01-31T12:00:00Z'
        upsert_post(db,aid,str(i),str(i),'2026-01-01T00:00:00Z',metrics={'views':100+i*100},observed_at=observed)
    rows,_=window_rows(db,latest_posts(db),'30天');df=frame(rows)
    assert df['age_band'].nunique()==2
    assert radar_scores(df,df.iloc[0].to_dict())[0]['n']==5
    assert df.baseline_n.eq(5).all()
