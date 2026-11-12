import io
import json
from pathlib import Path
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.content_analysis import frame
from creatorlab.battlecard import profile,render_card


def seed(db,complete=True):
    init_hub(db);aid=add_account(db,'bilibili','123','测试创作者')
    for i in range(5):
        metrics={'views':100+i*100}
        if complete:metrics.update(likes=20+i*7,comments=2+i,favorites=3+i,shares=i,coins=4+i)
        upsert_post(db,aid,'校园生活'+str(i),str(i),'2026-01-01T00:00:00Z' if complete else None,metrics=metrics,observed_at='2026-02-01T00:00:00Z')


def hero_app(db):
    return AppTest.from_string('from creatorlab.hub import latest_posts\nfrom creatorlab.personal_ui import hero\nhero(latest_posts('+repr(str(db))+'))').run()


def test_export_is_real_png_in_both_themes_and_name_is_opt_in(tmp_path):
    db=tmp_path/'d.db';seed(db);df=frame(latest_posts(db));row=df.iloc[0].to_dict();model=profile(df,row)
    assert model['ready'] and model['available']==6
    dark=render_card(row,model);light=render_card(row,model,light=True)
    for data in (dark,light):
        with Image.open(io.BytesIO(data)) as im:assert im.size==(1080,1320) and im.format=='PNG'
    assert dark!=light
    renamed=dict(row,account_name='不该默认出现在图片上的昵称')
    assert render_card(renamed,model)==dark
    assert render_card(renamed,model,show_name=True)!=render_card(row,model,show_name=True)


def test_no_measured_radar_no_share_and_one_repair_action(tmp_path):
    db=tmp_path/'d.db';seed(db,complete=False);df=frame(latest_posts(db));model=profile(df,df.iloc[0].to_dict())
    with pytest.raises(ValueError):render_card(df.iloc[0].to_dict(),model)
    app=hero_app(db)
    assert not app.exception,[e.message for e in app.exception]
    assert app.button(key='hero_repair')
    assert not app.get('download_button')
    assert not app.get('imgs')


def test_home_card_share_and_single_action_persist_experiment(tmp_path):
    from creatorlab.growth import experiments
    db=tmp_path/'d.db';seed(db);app=hero_app(db)
    assert not app.exception,[e.message for e in app.exception]
    assert len(app.get('download_button'))==1
    assert not app.checkbox(key='hero_show_name').value
    assert not app.checkbox(key='hero_preview').value
    assert not app.get('imgs')  # The poster must not occupy the everyday workspace.
    figures=[json.loads(c.proto.spec) for c in app.get('plotly_chart')]
    actual=[trace for fig in figures for trace in fig['data'] if trace.get('name') in ('这条作品','数量位置')]
    assert len(actual)==1 and len(actual[0]['customdata'])==7
    assert actual[0]['customdata'][0][1]==4
    assert '原始值' in actual[0]['hovertemplate']
    app.button(key='hero_accept').click().run()
    aid=latest_posts(db)[0]['account_id']
    assert not app.exception and len(experiments(db,aid))==1
    app.button(key='hero_accept').click().run()
    assert len(experiments(db,aid))==1


def test_primary_navigation_has_visual_card_first_and_details_later(tmp_path,monkeypatch):
    db=tmp_path/'d.db';seed(db);monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    assert not app.exception,[e.message for e in app.exception]
    assert not app.tabs
    assert any(h.value=='看作品' for h in app.subheader)
    assert app.get('plotly_chart')
    assert not app.get('file_uploader')
    assert not app.text_area
    assert app.sidebar.expander[0].label=='外观'
    # Extra tasks are loaded only after navigation, not merely hidden below the card.
    assert not any(s.key=='analysis_goal' for s in app.selectbox)
    app.switch_page('app_pages/create.py').run()
    assert any(h.value=='做下一条' for h in app.subheader)
    assert not app.exception


def test_comparison_has_real_polar_and_selected_metric_bars(tmp_path):
    db=tmp_path/'d.db';seed(db)
    app=AppTest.from_string('from creatorlab.hub import latest_posts\nfrom creatorlab.personal_ui import quick_compare\nquick_compare(latest_posts('+repr(str(db))+'))').run()
    assert not app.exception
    traces=[t for c in app.get('plotly_chart') for t in json.loads(c.proto.spec).get('data',[])]
    assert sum(t.get('type')=='scatterpolar' for t in traces)==2
    assert any(t.get('type')=='bar' for t in traces)
