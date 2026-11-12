import pandas as pd
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post
from creatorlab.personal_ui import chronological_ids


def test_dates_sort_by_actual_time_and_unknowns_follow_backfilled_posts():
    df=pd.DataFrame([
      dict(id=100,published_at='2020-01-01'),
      dict(id=1,published_at='2026-10-31T17:00:00Z'),
      dict(id=2,published_at='2026-11-01T00:30:00+08:00'),
      dict(id=101,published_at=None),dict(id=102,published_at='invalid')])
    assert chronological_ids(df)==[1,2,100,102,101]


def test_home_and_comparison_put_latest_before_older_ready_cards(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    metrics=dict(views=100,likes=5,comments=2,favorites=3,shares=1,coins=2)
    newest=upsert_post(db,aid,'最新发布','new','2026-10-31T12:00:00+08:00',metrics=metrics,observed_at='2026-11-01T12:00:00+08:00')
    for i in range(3):upsert_post(db,aid,'补录旧作品'+str(i),'old'+str(i),'2026-01-01T12:00:00+08:00',metrics=metrics,observed_at='2026-11-01T12:00:00+08:00')
    code='from creatorlab.personal_ui import hero,quick_compare\nfrom creatorlab.hub import latest_posts\nrows=latest_posts('+repr(str(db))+')\nhero(rows)\nquick_compare(rows)'
    app=AppTest.from_string(code).run(timeout=30)
    assert not app.exception,[r.message for r in app.exception]
    assert app.selectbox(key='hero_work').value==newest
    assert app.selectbox(key='quick_a').value==newest
    assert app.selectbox(key='hero_work').options[0].startswith('2026-10-31 12:00 · 最新发布')
    assert any('不限作品年龄' in c.value for c in app.caption)
    assert not app.button(key='battle_next_ready').disabled
