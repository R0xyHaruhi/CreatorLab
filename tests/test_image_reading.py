import json,subprocess,shutil
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.image_reading import value
from creatorlab.battlecard import history_profiles,render_card
from creatorlab.challenge import work_result
from creatorlab.content_analysis import frame
from creatorlab.hub import init_hub,add_account,latest_posts
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture
from creatorlab.work_formats import DY_VISIBLE,match_visible_metadata
from test_reach_conversion import works


def images():
    rows=works()
    for i,r in enumerate(rows):r.update(media_format='image',image_count=4,avg_image_views=1+i*.4,swipe_away_rate=.3,text_expand_rate=.01)
    return rows


def test_reading_depth_not_video_completion_and_invalid_denominators():
    r=images()[0]
    assert value(r,'image_depth')==.25
    from creatorlab.report_ui import formatted
    assert formatted(1.8,'images')=='1.8张'
    assert value(dict(r,image_count=0),'image_depth') is None
    assert value(dict(r,image_count=None),'image_depth') is None
    assert value(dict(r,avg_image_views=5),'image_depth') is None
    assert value(dict(r,media_format='video'),'image_depth') is None
    assert value(dict(r,analysis_window='7天'),'image_depth') is None
    assert value(dict(r,image_observed_at={'image_count':'2026-01-01T00:00:00Z','avg_image_views':'2026-01-02T00:00:00Z'}),'image_depth') is None


def test_true_dom_statistics_parsed_and_saved_through_capture_to_database(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('DOM regression requires Node')
    script='''const c={innerText:'平均浏览图片数\\n3\\n划走率\\n24.44%\\n文案展开率\\n0.09%',querySelector:s=>s.includes('cover')?{style:{},querySelectorAll:()=>[{innerText:'置顶'},{innerText:'3张'}],querySelector:()=>null}:s.includes('title')?{innerText:'图文测试'}:s.includes('status')?{innerText:'已发布'}:null};const document={querySelectorAll:()=>[c]};console.log(JSON.stringify(('''+DY_VISIBLE+''')()[0]));'''
    card=json.loads(subprocess.run([node,'-e',script],check=True,text=True,capture_output=True).stdout)
    assert card['image_count']==3 and card['avg_image_views']==3
    assert card['swipe_away_rate']==.2444 and card['text_expand_rate']==.0009
    row=dict(video_id='7412345678901234567',title='图文测试',cover_url='https://p3.douyinpic.com/tos/a')
    card['cover_url']=row['cover_url']
    update=match_visible_metadata([card],[row])[0]
    assert update['image_count']==3
    db=tmp_path/'image.db';init_hub(db);aid=add_account(db,'douyin','one')
    run=create_capture(db,aid)
    stage_rows(db,run,[dict(row,**{k:v for k,v in update.items() if k not in ('video_id','title')},views=2000,likes=50)])
    finish_capture(db,run);commit_capture(db,run,aid)
    saved=latest_posts(db)[0]
    assert saved['media_format']=='image' and saved['avg_image_views']==3 and value(saved,'image_depth')==1


def test_six_image_axes_and_five_mixed_composite_axes():
    rows=images();m=history_profiles(rows);rates=history_profiles(rows,efficiency=True)
    assert m[7]['scores'][-1]['metric']=='avg_image_views' and m[7]['available']==6
    assert rates[7]['scores'][-1]['metric']=='image_depth' and rates[7]['scores'][-1]['value']==pytest.approx(.95)
    assert m[7]['scores'][-1]['n']==7
    df=frame(rows)
    assert work_result(df,df.iloc[-1].to_dict(),m)['axes']==6
    mixed=rows+[dict(works()[0],id=50)]
    df=frame(mixed);models=history_profiles(mixed)
    result=work_result(df,df[df.id==7].iloc[0].to_dict(),models)
    assert result['axes']==5 and result['n']==8
    assert render_card(rows[-1],m[7]).startswith(b'\x89PNG')


def test_image_hero_has_reading_metrics_and_type_filter():
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(images())+')').run(timeout=20)
    assert not app.exception,[e.message for e in app.exception]
    assert any('阅读深度指数：95.0%' in c.value for c in app.caption)
    assert any('6/6个适用维度' in c.value for c in app.caption)
    app.radio(key='hero_media_scope').set_value('仅图文').run(timeout=20)
    assert not app.exception
