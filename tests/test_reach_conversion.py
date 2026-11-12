import io
import json
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from creatorlab.engagement import like_diagnosis,attach_context
from creatorlab.battlecard import history_profiles,render_card
from creatorlab.personal_ui import radar_figure


def works():
    pairs=[(1200,48),(2000,70),(4000,100),(6000,150),(8000,200),(10000,220),(20000,400),(40000,280)]
    return [dict(id=i,account_id=1,platform='douyin',media_format='video',title=f'作品{i}',
                 published_at='2026-01-01T00:00:00Z',metric_recorded_at='2026-11-01T00:00:00Z',
                 views=v,likes=l,comments=10,favorites=10,shares=10,completion_rate=.3+i*.02,
                 account_name='测试账号',source='manual') for i,(v,l) in enumerate(pairs)]


def model(rows):
    counts=history_profiles(rows);rates=history_profiles(rows,efficiency=True);row=rows[-1]
    return attach_context(counts[row['id']],rates[row['id']],like_diagnosis(rows,row))


def test_reach_and_likes_count_can_be_strong_while_conversion_is_weak():
    rows=works();m=model(rows);d=m['diagnosis']
    assert d['state']=='reach_like_gap' and d['rate']==.007 and d['n']==7
    assert d['median_rate']==.025 and d['relative']==pytest.approx(.28)
    assert m['scores'][1]['score']>70 and m['dual_scores'][1]['score']==0
    fig=radar_figure(m)
    assert len(fig.data)==3
    assert {t.name for t in fig.data if t.showlegend}=={'数量位置','互动转化位置'}
    assert any('数量86 · 转化0' in text for text in fig.layout.polar.angularaxis.ticktext)
    assert '点赞转化偏低' in m['archetype']


def test_small_samples_and_stale_metrics_do_not_gain_a_strong_conversion_label():
    rows=works();small=dict(rows[-1],views=2,likes=1)
    assert like_diagnosis(rows,small)['state']=='small'
    efficiency=history_profiles(rows[:-1]+[small],efficiency=True)[small['id']]
    assert efficiency['scores'][1]['value']==.5 and efficiency['scores'][1]['score'] is None
    assert like_diagnosis(rows,dict(rows[-1],_ratio_allowed={'likes':False}))['state']=='missing'
    tiny=[dict(r,views=2,likes=1) for r in rows[:-1]]
    assert like_diagnosis(tiny+[rows[-1]],rows[-1])['state']=='insufficient'


def test_reference_filters_platform_account_format_visibility_window_and_target():
    rows=works();target=rows[-1]
    extras=[dict(rows[0],id=100+i,**change) for i,change in enumerate([
        {'platform':'bilibili'},{'account_id':2},
        {'visibility':'private'},{'analysis_window':'发布7天'},{'_ratio_allowed':{'likes':False}}])]
    assert like_diagnosis(rows+extras,target)==like_diagnosis(rows,target)


def test_export_contains_dual_model_and_diagnosis_without_breaking_legacy_card_size():
    rows=works();m=model(rows)
    with Image.open(io.BytesIO(render_card(rows[-1],m))) as im:assert im.size==(1080,1480)
    old=history_profiles(rows)[rows[-1]['id']]
    with Image.open(io.BytesIO(render_card(rows[-1],old))) as im:assert im.size==(1080,1320)


def test_default_hero_exposes_conversion_gap_without_switching_modes():
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(works())+')').run(timeout=20)
    assert not app.exception,[e.message for e in app.exception]
    # Latest publication is shared; select the high-reach target explicitly.
    key=next(s.key for s in app.selectbox if s.label=='作品')
    app.selectbox(key=key).set_value(7).run(timeout=20)
    assert not app.exception,[e.message for e in app.exception]
    assert any('点赞转化低于同组中位数' in w.value for w in app.caption)
    traces=[t for c in app.get('plotly_chart') for t in json.loads(c.proto.spec).get('data',[])]
    assert any(t.get('name')=='互动转化位置' for t in traces)
    assert any('0.70%' in h.proto.body and '点赞率' in h.proto.body for h in app.get('html'))
