from creatorlab.hub import *
import pytest


def test_accounts_posts_snapshots(tmp_path):
    db=tmp_path/'db.sqlite';init_hub(db)
    a=add_account(db,'bilibili','123','UP主')
    assert add_account(db,'bilibili','123','UP主')==a
    post=upsert_post(db,a,'视频1','BVxx',metrics={'views':'15000','likes':33,'completion_rate':'55%'})
    assert latest_posts(db)[0]['views']==15000
    assert latest_posts(db)[0]['completion_rate']==.55
    assert upsert_post(db,a,'视频1改名','BVxx',metrics={'views':17000})==post
    assert len(latest_posts(db))==1
    assert len(snapshots(db,post))==2
    assert latest_posts(db)[0]['views']==17000
    assert latest_posts(db)[0]['likes']==33  # partial update preserves known values
    assert latest_posts(db)[0]['completion_rate']==.55


def test_projects_and_format(tmp_path):
    db=tmp_path/'db.sqlite';init_hub(db)
    a=add_account(db,'douyin','me');p=upsert_post(db,a,'角色扮演')
    project=add_project(db,'跨平台 COS')
    assign_project(db,p,project)
    assert latest_posts(db)[0]['project_name']=='跨平台 COS'
    assert fmt_count(12000)=='1.20 万'
    assert fmt_rate(.5555)=='55.5%'
    assert fmt_seconds(4.25)=='4.2 秒'
    assert fmt_count(None)=='—'


def test_csv_and_validation(tmp_path):
    db=tmp_path/'db.sqlite';init_hub(db)
    a=add_account(db,'bilibili','id')
    data='title,external_id,views,completion_rate\nA,BV1,1200,25%\nB,BV2,,\n'
    assert import_csv(db,a,data)==2
    assert len(latest_posts(db))==2
    assert latest_posts(db)[0]['views'] is None
    with pytest.raises(ValueError):
        import_csv(db,a,'title,views\nBad,-2')
    assert len(latest_posts(db))==2
    with pytest.raises(ValueError):
        upsert_post(db,a,'bad',metrics={'completion_rate':55})


def test_existing_douyin_import(tmp_path):
    from creatorlab.bridge import save_batch
    db=tmp_path/'db.sqlite';init_hub(db)
    a=add_account(db,'douyin','main')
    batch={'source':'network','rows':[{'video_id':'1234567890123456789','title':'A video','views':1234,'likes':12,
                                         'completion_rate':.4}]}
    save_batch(db,batch)
    assert import_douyin_existing(db,a,db)==1
    assert import_douyin_existing(db,a,db)==1
    assert len(latest_posts(db))==1
    assert len(snapshots(db,latest_posts(db)[0]['id']))==2


def test_publication_date_validation_and_legacy_correction(tmp_path):
    from creatorlab.measurements import timestamp
    from creatorlab.personal_ui import publication_label
    db=tmp_path/'dates.db';init_hub(db)
    aid=add_account(db,'douyin','me')
    with pytest.raises(ValueError,match='发布时间无效'):
        upsert_post(db,aid,'手填日期',published_at='2026-02-30')
    with pytest.raises(ValueError,match='第 3 行.*发布时间无效'):
        import_csv(db,aid,'title,published_at\n正确,2026-02-28\n错误,2026-02-30')
    assert not latest_posts(db)
    pid=upsert_post(db,aid,'旧作品',published_at='2026-02-28',metrics={'views':100})
    with connect(db) as con:
        con.execute('UPDATE hub_posts SET published_at=? WHERE id=?',('2026-02-30',pid))
    assert publication_label(latest_posts(db)[0]['published_at'])=='发布时间待确认'
    update_publication_date(db,aid,pid,'2026-02-28')
    row=latest_posts(db)[0]
    assert row['published_at']=='2026-02-28' and row['views']==100
    assert timestamp(row['published_at']) is None
