from streamlit.testing.v1 import AppTest

from creatorlab.weekly_reference import load_dataset, select_samples, tag_facets


def test_refinement_intersects_existing_scope_and_preserves_missing():
    _, rows = load_dataset()
    base = select_samples(rows, tags=['COSPLAY'], issues=[391])
    facets = tag_facets(base)
    assert base and facets['cosplay'] == len(base)
    tag = next(t for t in facets if t != 'cosplay')
    excluded = base[0]['bvid']
    found = select_samples(rows, tags=['COSPLAY'], issues=[391],
                           required_tags=[tag], exclude_bvids=[excluded])
    assert {r['bvid'] for r in found} == {
        r['bvid'] for r in base if tag in r['normalized_tags'] and r['bvid'] != excluded}
    assert all(r['matched_tags'] == ('cosplay',) for r in found)
    assert select_samples(base, required_tags=['__missing__']) == []
    # A work contributes once to a normalized tag count, regardless of spelling.
    assert tag_facets([dict(normalized_tags=frozenset(['cosplay']), views=None)]) == {'cosplay': 1}


def test_refinement_ui_filters_and_clears_invalid_selection():
    app = AppTest.from_string('from creatorlab.weekly_ui import panel\npanel([])',
                             default_timeout=30).run()
    app.text_input(key='weekly_tags').set_value('COSPLAY').run()
    _, rows = load_dataset()
    base = select_samples(rows, tags=['COSPLAY'])
    tag = next(t for t in tag_facets(base) if t != 'cosplay')
    app.multiselect(key='weekly_refine_tags').set_value([tag]).run()
    assert not app.exception, [e.message for e in app.exception]
    assert int(app.metric[0].value.replace(',', '')) == sum(tag in r['normalized_tags'] for r in base)
    assert any('追加全部命中：' + tag in c.value for c in app.caption)
    app.text_input(key='weekly_tags').set_value('__missing__').run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.multiselect(key='weekly_refine_tags').value == []
    assert app.metric[0].value == '0'
    app.button(key='weekly_clear_filters').click().run()
    assert app.text_input(key='weekly_tags').value=='' and app.metric[0].value=='4,600'
