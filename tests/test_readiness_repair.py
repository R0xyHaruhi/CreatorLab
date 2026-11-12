from streamlit.testing.v1 import AppTest
from creatorlab.image_reading import readiness,public_count
from creatorlab.integrity import inventory_message
from test_image_reading import images


def test_precise_readiness_states_and_visibility_inventory_gap():
    r=images()[0]
    assert readiness(r)['state']=='ready'
    assert readiness(dict(r,image_count=None,avg_image_views=None))['state']=='not_collected'
    assert readiness(dict(r,image_count=None))['state']=='count_missing'
    assert readiness(dict(r,avg_image_views=None))['state']=='average_missing'
    assert readiness(dict(r,avg_image_views=20))['state']=='invalid'
    text=inventory_message(dict(count=204,total=293,visible_list_count=204,visible_list_ended=True,rejected_rows=0))
    assert '89条无法' in text and '已入库不等于全量采齐' in text and '不要把差额计入私密' in text


def test_public_count_only_for_exact_owned_image_page_and_matching_title():
    class Page:
        url='https://www.douyin.com/video/7412345678901234567'
        text='作品标题 #tag 1/2';n=2
        def locator(self,k):return self
        def inner_text(self):return self.text
        def evaluate(self,script):return self.n
    p=Page();r=dict(video_id='7412345678901234567',title='作品标题 #tag',media_format='image')
    assert public_count(p,r)==2
    p.url='https://www.douyin.com/note/7412345678901234567'
    assert public_count(p,r)==2
    p.url='https://www.douyin.com/note/7412345678901234568'
    assert public_count(p,r) is None
    p.url='https://www.douyin.com/video/7412345678901234567'
    assert public_count(p,dict(r,video_id='7412345678901234568')) is None
    assert public_count(p,dict(r,media_format='video')) is None
    p.text='其他作品'
    assert public_count(p,r) is None
    p.text='作品标题 #tag';p.n=None
    assert public_count(p,r) is None


def test_missing_metrics_shows_actionable_warning_instead_of_blank_alone():
    rows=images();rows[-1]['avg_image_views']=None;rows[-1]['image_count']=None
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero('+repr(rows)+')').run(timeout=20)
    assert not app.exception,[e.message for e in app.exception]
    assert any('图文新指标尚未采集' in w.value for w in app.warning)


def test_public_detail_does_not_turn_creator_confirmed_image_into_video(tmp_path):
    from creatorlab.work_formats import preserve_confirmed_formats
    from creatorlab.hub import init_hub,add_account,latest_posts
    from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture
    from creatorlab.reporting import metric_value
    vid='7412345678901234567'
    original=dict(video_id=vid,title='图文',media_format='image',visibility='public',views=2000,likes=20,image_count=2,avg_image_views=1.8)
    incoming=dict(video_id=vid,title='图文',media_format='video',completion_rate=.6885)
    corrected=preserve_confirmed_formats([incoming],{vid:original})[0]
    assert corrected['media_format']=='image'
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','own')
    run=create_capture(db,aid);stage_rows(db,run,[original]);stage_rows(db,run,[corrected]);finish_capture(db,run);commit_capture(db,run,aid)
    row=latest_posts(db)[0]
    assert row['media_format']=='image'
    assert metric_value(row,'completion_rate') is None
    assert metric_value(row,'image_depth')==.9
