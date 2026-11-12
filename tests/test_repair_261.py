"""Regressions from the user's incomplete-install and missing-card screenshots."""
import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts


def test_missing_weekly_does_not_crash_other_features(monkeypatch):
    monkeypatch.setitem(sys.modules,'creatorlab.weekly_ui',None)
    app=AppTest.from_string('from creatorlab.optional_ui import weekly_panel\nweekly_panel([],key="missing")').run()
    assert not app.exception
    assert any('安装不完整' in e.value for e in app.error)


def test_battle_entry_composite_export_and_efficiency_survive(tmp_path,monkeypatch):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    title='完整标题'+('不能被代码截断的长作品名称'*12)
    for i in range(5):upsert_post(db,aid,title+str(i),'video'+str(i),'2026-01-01T00:00:00Z',metrics=dict(views=1000+i*1000,likes=5+i,comments=2+i,shares=1+i,favorites=3+i,coins=2+i),observed_at='2026-11-01T00:00:00Z')
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    assert not app.exception,[e.message for e in app.exception]
    assert not app.tabs and any(h.value=='看作品' for h in app.subheader)
    assert any(b.key=='hero_share' for b in app.get('download_button'))
    assert any('数量综合位置' in h.proto.body for h in app.get('html'))
    assert title in app.selectbox(key='hero_work__bilibili').options[0]
    app.radio(key='hero_shape').set_value('互动效率').run()
    assert not app.exception,[e.message for e in app.exception]
    assert any('互动效率综合位置' in h.proto.body for h in app.get('html'))
    assert any(b.key=='hero_share' for b in app.get('download_button'))
