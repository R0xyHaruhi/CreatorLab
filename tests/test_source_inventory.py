"""Regressions grounded in the logged-in source-page inspection."""
from creatorlab.hub import init_hub,add_account,latest_posts,eligible
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture
from creatorlab.douyin_data import pending
from creatorlab.work_formats import match_visible_metadata
from creatorlab.bilibili_import import normalize,ingest_row


def test_metricless_private_work_survives_review_and_import(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','one')
    run=create_capture(db,aid)
    assert stage_rows(db,run,[{'video_id':'7412345678901234567','title':'私密作品','visibility':'private','media_format':'video'}])==1
    finish_capture(db,run);assert commit_capture(db,run,aid)==1
    row=latest_posts(db)[0]
    assert row['views'] is None and row['visibility']=='private' and row['media_format']=='video'
    assert eligible([row])==[] and pending(row)==[]


def test_image_does_not_require_video_completion_rate():
    row=dict(media_format='image',published_at='2026-01-01T00:00:00Z',views=1,likes=0,comments=0,shares=0,favorites=0)
    assert pending(row)==[]
    assert pending(dict(row,media_format='video'))==['completion_rate']


def test_visible_metadata_binding_requires_unique_title_and_cover():
    cover='https://p3.douyinpic.com/tos-cn-i-0813c000/a~resize.webp?sign=one'
    row=dict(video_id='7412345678901234567',title='同标题',cover_url=cover)
    card=dict(title='同标题',cover_url=cover,visibility='private',media_format='image')
    assert match_visible_metadata([card],[row])[0]['visibility']=='private'
    assert match_visible_metadata([card],[row,dict(row,video_id='7412345678901234568')])==[]
    assert match_visible_metadata([dict(card,cover_url='https://example.com/a')],[row])==[]


def test_bili_private_status_survives_later_partial_network_data(tmp_path):
    db=tmp_path/'d.db';init_hub(db);rows={};seen={}
    base={'bvid':'BV1viU8Y6E25','title':'作品'}
    ingest_row(db,'123',normalize(dict(base,visibility='private')),rows,seen)
    ingest_row(db,'123',normalize(dict(base,stat={'view':5130})),rows,seen)
    row=latest_posts(db)[0]
    assert row['visibility']=='private' and row['views']==5130 and eligible([row])==[]


def test_radar_cohorts_keep_image_video_and_unknown_formats_separate():
    import pandas as pd
    from creatorlab.growth import radar_scores
    from creatorlab.battlecard import profiles
    rows=[dict(id=i,account_id=1,platform='douyin',age_band='30天以上',views=value,media_format=media) for i,(media,value) in enumerate([('video',1),('video',2),('video',3),('image',1000),('unknown',2000)])]
    df=pd.DataFrame(rows)
    model=profiles(df)
    assert radar_scores(df,rows[0],min_n=3)[0]['n']==5  # explicit default: all valid historical formats
    assert model[0]['scores'][0]['n']==3
    assert model[3]['scores'][0]['score'] is None and model[4]['scores'][0]['score'] is None
