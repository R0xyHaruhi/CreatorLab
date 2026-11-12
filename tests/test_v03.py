from creatorlab.storage import init_db, add_video, list_rows, upsert_profile, add_plan, set_plan_status

def test_migration_and_plans(tmp_path):
    db = tmp_path / 'test.db'
    init_db(db)
    upsert_profile(db,'douyin','@example','cosplay','fans','growth','budget')
    assert list_rows(db,'creator_profiles')[0]['handle'] == '@example'
    add_plan(db,'tiktok','@example','2026-10-25','Character test','closeup','transition','')
    pid = list_rows(db,'content_plans')[0]['id']
    set_plan_status(db,pid,'published')
    assert list_rows(db,'content_plans')[0]['status'] == 'published'

def test_platform_video(tmp_path):
    db = tmp_path / 'test.db'; init_db(db)
    add_video(db,dict(title='test',role='character',format='transition',hook='closeup',duration_sec=12,publish_hour=12,views=20,likes=1,comments=0,shares=0,new_followers=0,published_at='',notes='',platform='douyin'))
    assert list_rows(db,'videos')[0]['platform'] == 'douyin'
