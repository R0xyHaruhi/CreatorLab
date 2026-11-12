import json

from streamlit.testing.v1 import AppTest

from test_reach_conversion import works
from creatorlab.battlecard import history_profiles


def test_line_identity_and_values_survive_primary_perspective_switch():
    rows=works()
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(rows)+')').run(timeout=20)
    for perspective,efficiency in [('数量战力',False),('互动效率',True)]:
        app.radio(key='hero_shape').set_value(perspective).run(timeout=20)
        assert not app.exception,[e.message for e in app.exception]
        selected=app.selectbox(key='hero_work').value
        chart=next(c for c in app.get('plotly_chart') if c.key=='hero_radar')
        figure=json.loads(chart.proto.spec)
        traces={t.get('name'):t for t in figure['data']}
        assert traces['数量位置']['line']['dash']=='solid'
        assert traces['互动转化位置']['line']['dash']=='dash'
        expected=history_profiles(rows,efficiency=efficiency)[selected]
        name='互动转化位置' if efficiency else '数量位置'
        values=[s['score'] for s in expected['scores']]
        assert traces[name]['r']==values+[values[0]]
        assert all(v[1]==7 for v in traces['数量位置']['customdata'])


def test_empty_type_filter_can_be_recovered_without_losing_controls():
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(works())+')').run(timeout=20)
    app.radio(key='hero_media_scope').set_value('仅图文').run(timeout=20)
    assert not app.exception
    assert any('所选类型暂无' in i.value for i in app.info)
    app.radio(key='hero_media_scope').set_value('全部类型').run(timeout=20)
    assert not app.exception and app.get('download_button')


def test_top_completion_position_never_looks_like_actual_100_percent():
    from creatorlab.personal_ui import radar_figure
    from creatorlab.engagement import attach_context,like_diagnosis
    rows=works();rows[-1]['completion_rate']=.460124
    counts=history_profiles(rows);rates=history_profiles(rows,efficiency=True)
    m=attach_context(counts[7],rates[7],like_diagnosis(rows,rows[-1]))
    axis=next(s for s in m['scores'] if s['metric']=='completion_rate')
    assert axis['score']==100 and axis['value']==.460124
    label=radar_figure(m).layout.polar.angularaxis.ticktext[-1]
    assert '实测 46.01%' in label and '高于7/7条' in label
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(rows)+')').run(timeout=20)
    app.selectbox(key='hero_work').set_value(7).run(timeout=20)
    assert not app.exception
    assert any('实际完播率 **46.01%**' in x.value for x in app.markdown)
    assert any('完播率高于 7/7 条其他有效历史作品' in x.value for x in app.caption)
