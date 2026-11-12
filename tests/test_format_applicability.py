import io,json,shutil,subprocess
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.work_formats import DY_VISIBLE
from creatorlab.battlecard import history_profiles,render_card
from creatorlab.personal_ui import radar_figure
from creatorlab.engagement import axis_value
from test_reach_conversion import works


def test_source_dom_handles_pinned_badge_and_missing_image_count_badge():
    node=shutil.which('node')
    if not node:pytest.skip('Node is needed for collector DOM regression')
    cases=[(['置顶','15张'],'平均浏览图片数\n3','image'),([], '平均浏览图片数\n1.8','image'),(['置顶','00:13'],'完播率\n15.86%','video'),(['置顶'],'不明体裁',None)]
    script='const cases='+json.dumps(cases,ensure_ascii=False)+''';
const document={querySelectorAll:()=>cases.map(([badges,text])=>({innerText:text,querySelector:(sel)=>sel.includes('cover')?{style:{},querySelectorAll:()=>badges.map(t=>({innerText:t})),querySelector:()=>null}:null}))};
console.log(JSON.stringify(('''+DY_VISIBLE+''')().map(x=>x.media_format)));'''
    result=subprocess.run([node,'-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)==[x[2] for x in cases]


def test_image_stale_completion_never_scored_and_not_labelled_missing():
    rows=works();rows[-1].update(media_format='image',completion_rate=.999)
    model=history_profiles(rows)[7];s=model['scores'][-1]
    assert model['applicable']==6 and model['available']==5
    assert s['score'] is None and s['value'] is None and s['n']==0 and s['status']=='missing'
    assert s['metric']=='avg_image_views' and axis_value(s)=='—'
    assert '阅读深度' in radar_figure(model).layout.polar.angularaxis.ticktext[-1]
    assert render_card(rows[-1],model).startswith(b'\x89PNG')
    video=dict(rows[-1],media_format='video',completion_rate=None)
    assert history_profiles(rows[:-1]+[video])[7]['scores'][-1]['status']=='missing'


def test_image_hero_explains_five_applicable_axes():
    rows=works();rows[-1]['media_format']='image'
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(rows)+')').run(timeout=20)
    assert not app.exception,[e.message for e in app.exception]
    assert any('图文使用独立的阅读深度轴' in x.value for x in app.info)
    assert any('5/6个适用维度' in x.value for x in app.caption)
