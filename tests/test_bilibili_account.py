import json
from creatorlab.hub import init_hub,accounts,connect,upsert_post,add_account,latest_posts
from creatorlab.bilibili_account import parse_account_response,save_observation,latest_fields,observations
from creatorlab.bilibili_import import normalize,persist


def test_follower_parsing_requires_uid_and_keeps_zero():
    raw=json.dumps({'code':0,'data':{'mid':123,'follower':0,'following':12}})
    url='https://api.bilibili.com/x/relation/stat?vmid=123'
    assert parse_account_response(url,raw,'123')=={'followers':0,'following':12}
    assert parse_account_response(url,raw,'456') is None
    assert parse_account_response(url,raw.replace('"mid": 123','"mid": 456'),'123') is None
    assert parse_account_response(url.replace('api.bilibili.com','evil.example'),raw,'123') is None


def test_account_totals_and_video_overview_are_separate(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    save_observation(db,'123','account',{'followers':1234,'following':18},'space','公开统计')
    save_observation(db,'123','account',{'total_likes':4567},'space_stats','公开统计')
    aid=accounts(db)[0]['id']
    assert latest_fields(db,aid)['followers']['value']==1234
    assert latest_fields(db,aid)['total_likes']['value']==4567
    assert not save_observation(db,'123','account',{'total_likes':4567},'space_stats','公开统计')
    save_observation(db,'123','creator_video_overview',{'views':99999,'coins':66},'creator','起始日未知','2026-10-25')
    assert 'views' not in latest_fields(db,aid)
    assert observations(db,aid,'creator_video_overview')[0]['data_date']=='2026-10-25'
    assert len(observations(db,aid))==2


def test_card_and_upstat_fields():
    card=json.dumps({'code':0,'data':{'card':{'mid':'123','fans':89,'friend':3},'archive_count':20,'like_num':500}})
    assert parse_account_response('https://api.bilibili.com/x/web-interface/card?mid=123',card,'123')['followers']==89
    stat=json.dumps({'code':0,'data':{'likes':500,'archive':{'view':12345},'article':{'view':67}}})
    d=parse_account_response('https://api.bilibili.com/x/space/upstat?mid=123',stat,'123')
    assert d=={'total_likes':500,'archive_views':12345,'article_views':67}


def test_new_post_metrics_migrate_and_partial_update(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    pid=upsert_post(db,aid,'标题','BV1xx411c7mD',metrics={'views':100,'coins':5,'danmaku':7})
    assert latest_posts(db)[0]['coins']==5
    upsert_post(db,aid,'标题','BV1xx411c7mD',metrics={'views':200})
    assert latest_posts(db)[0]['coins']==5 and latest_posts(db)[0]['danmaku']==7
    with connect(db) as con:
        con.execute('ALTER TABLE hub_snapshots DROP COLUMN coins')
        con.execute('ALTER TABLE hub_snapshots DROP COLUMN danmaku')
        con.execute('DROP TABLE clab_metric_observations')  # emulate a pre-ledger database
    init_hub(db)
    assert latest_posts(db)[0]['views']==200 and latest_posts(db)[0]['coins'] is None


def test_coin_danmaku_distinct_from_comments(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    row=normalize({'bvid':'BV1xx411c7mD','title':'标题','stat':{'view':100,'reply':2,'coin':4,'danmaku':9}})
    persist(db,'123',row)
    post=latest_posts(db)[0]
    assert (post['comments'],post['coins'],post['danmaku'])==(2,4,9)


def test_creator_capture_requires_owner_date_and_exact_values(tmp_path):
    from creatorlab.bilibili_account import capture_creator_overview
    db=tmp_path/'d.db';init_hub(db)
    good={'data_date':'2026-10-25','metrics':{'views':100,'coins':5,'danmaku':8,'shares':0}}
    assert not capture_creator_overview(db,'123','456',good)
    assert not capture_creator_overview(db,'123','123',dict(good,data_date='unknown'))
    assert not capture_creator_overview(db,'123','123',dict(good,metrics={'views':'1.2万','coins':None,'likes':False}))
    assert capture_creator_overview(db,'123','123',good)
    assert capture_creator_overview(db,'123','123',good)
    aid=accounts(db)[0]['id']
    assert len(observations(db,aid,'creator_video_overview'))==1
    assert observations(db,aid,'creator_video_overview')[0]['metrics']['shares']==0


def test_account_dashboard_shows_followers_and_creator_totals(tmp_path):
    from streamlit.testing.v1 import AppTest
    db=tmp_path/'d.db';init_hub(db)
    save_observation(db,'123','account',{'followers':100,'following':20},'space','账号')
    save_observation(db,'123','account',{'followers':120},'space','账号')
    save_observation(db,'123','creator_video_overview',{'views':10000,'likes':800,'coins':200,'danmaku':100},'creator','概览','2026-10-25')
    app=AppTest.from_string('from creatorlab.bilibili_account import account_dashboard\nfrom creatorlab.hub import accounts\naccount_dashboard('+repr(str(db))+',accounts('+repr(str(db))+'))').run()
    assert not app.exception
    metrics={m.label:m.value for m in app.metric}
    assert metrics['粉丝量']=='120'
    assert metrics['投币']=='200'
    assert len(app.get('plotly_chart'))==1
