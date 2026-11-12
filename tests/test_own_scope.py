import pandas as pd
from streamlit.testing.v1 import AppTest
from creatorlab.battlecard import history_profiles
from creatorlab.engagement import like_diagnosis
from creatorlab.challenge import work_result
from creatorlab.own_scope import references
from creatorlab.content_analysis import frame
from test_reach_conversion import works


def classified():
    rows=works()
    for i,r in enumerate(rows):
        r['media_format']='image' if i%2==0 else 'video'
        r['genre']=dict(major='游戏',minor='攻略教学' if i<4 else '操作高光',origin='manual')
    return rows


def test_default_uses_all_formats_and_tracks_but_preserves_identity_window_privacy():
    rows=classified();target=rows[-1]
    extras=[dict(rows[0],id=100+i,**v) for i,v in enumerate([
        dict(account_id=2),dict(platform='bilibili'),dict(visibility='private'),dict(analysis_window='发布7天')])]
    assert len(references(rows+extras,target))==7
    models=history_profiles(rows+extras)
    assert models[7]['scores'][0]['n']==7
    assert models[7]['scores'][-1]['n']==3  # images never supply video completion
    assert like_diagnosis(rows+extras,target)['n']==7
    df=frame(rows+extras);df['_baseline_scope']='当前累计'
    result=work_result(df,target,models)
    assert result['n']==7 and result['axes']==5  # mixed formats use only their common five axes


def test_track_is_optional_confirmed_and_shared_by_axes_composite_and_diagnosis():
    rows=classified();target=rows[-1]
    assert len(references(rows,target,'track'))==3
    # Bili counts keep all six axes valid across formats, avoiding completion-only exclusion.
    for r in rows:r.update(platform='bilibili',coins=10)
    models=history_profiles(rows,scope='track')
    assert models[7]['scores'][0]['n']==3
    assert like_diagnosis(rows,target,scope='track')['n']==3
    df=frame(rows);df['_baseline_scope']='当前累计'
    assert work_result(df,target,models)['n']==3
    rows[-1]['genre']=dict(major='游戏',minor='操作高光',origin='title_rule')
    assert references(rows,rows[-1],'track')==[]
    assert not history_profiles(rows,scope='track')[7]['ready']
    assert history_profiles(rows)[7]['ready']


def test_ui_switch_does_not_silently_fall_back_when_track_is_unclassified():
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(works())+')').run(timeout=20)
    assert not app.exception
    assert app.radio(key='hero_own_scope').value=='全部作品'
    app.radio(key='hero_own_scope').set_value('同赛道').run(timeout=20)
    assert not app.exception,[e.message for e in app.exception]
    assert any('当前作品未分类' in c.value for c in app.caption)
    assert app.button(key='battle_next_ready').disabled


def test_report_and_creative_brief_share_all_history_default_with_optional_track():
    from creatorlab.reporting import cohort,positions
    from creatorlab.creative_brief import build_brief
    rows=classified();target=rows[-1]
    assert len(cohort(rows,target))==7
    assert len(cohort(rows,target,scope='track'))==3
    by_metric={v['metric']:v for v in positions(rows,target)}
    assert by_metric['views']['n']==7
    assert by_metric['completion_rate']['n']==3  # missing/inapplicable values cannot be fabricated
    assert build_brief(rows,target,'views')['observations']['personal_n']==7
    selected=build_brief(rows,target,'views',personal_scope='track')
    assert selected['observations']['personal_n']==3
    # Marking a different category must never shrink the default reference group.
    rows[0]['genre']=dict(major='其他',minor='完全不同',origin='manual')
    assert len(cohort(rows,target))==7
    assert build_brief(rows,target,'views')['observations']['personal_n']==7
