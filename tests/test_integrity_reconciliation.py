import pytest
from creatorlab.integrity import summary,inventory_audit
from creatorlab.work_formats import match_visible_metadata
from creatorlab.hub import init_hub,add_account,latest_posts,upsert_post
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture,auto_commit_capture


def test_confirmed_private_is_excluded_not_pending_even_with_inconsistent_historic_counts():
    rows=[dict(visibility='private',views=0,likes=8) for _ in range(71)]
    rows += [dict(views=0,likes=1) for _ in range(96)]+[dict(views=0) for _ in range(5)]
    rows += [dict(views=100) for _ in range(32)]
    s=summary(rows)
    assert s==dict(total=204,analysable=32,excluded=71,missing=0,zero=5,inconsistent=96,pending=101)
    rows=[dict(visibility='private',views=0,likes=1) for _ in range(173)]+[dict(views=100,visibility='public') for _ in range(31)]
    assert summary(rows)['pending']==0 and summary(rows)['excluded']==173


def test_204_visible_does_not_prove_all_293_and_rejected_records_prevent_visible_claim():
    d=dict(count=204,total=293,visible_list_count=204,visible_list_ended=True,rejected_rows=0)
    s=inventory_audit(d)
    assert s['visible_verified'] and not s['platform_verified'] and s['external_gap']==89
    assert not inventory_audit(dict(d,rejected_rows=1))['visible_verified']
    assert not inventory_audit(dict(d,visible_list_count=203))['visible_verified']


def test_cover_variant_does_not_lose_privacy_when_title_and_publication_minute_are_unique():
    row=dict(video_id='7412345678901234567',title='完整标题 #标签',published_at='2026-06-22T03:18:42+00:00',cover_url='https://p3.douyinpic.com/one.jpg')
    card=dict(title='完整标题\n#标签',published_at='2026-06-21T20:18:00-07:00',cover_url='https://p5.douyinpic.com/other.jpg',visibility='private',media_format='image')
    result=match_visible_metadata([card],[row])
    assert result[0]['visibility']=='private' and result[0]['video_id']==row['video_id']
    assert not match_visible_metadata([dict(card,published_at='2026-06-21T20:19:00-07:00')],[row])
    assert not match_visible_metadata([card],[row,dict(row,video_id='7412345678901234568')])


def test_explicit_published_state_can_replace_an_old_private_observation():
    row=dict(video_id='7412345678901234567',title='作品',cover_url='https://p3.douyinpic.com/one.jpg',visibility='private')
    assert match_visible_metadata([dict(row,visibility='public')],[row])[0]['visibility']=='public'


def run(db,aid,vids):
    r=create_capture(db,aid)
    stage_rows(db,r,[dict(video_id=v,title='作品'+v,views=100,likes=2) for v in vids])
    finish_capture(db,r)
    return r


def test_known_id_refresh_needs_prior_review_and_never_adopts_new_or_ambiguous_ids(tmp_path):
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me');vid='7412345678901234567';new='7412345678901234568'
    first=run(db,a,[vid]);assert auto_commit_capture(db,first,a)==0
    commit_capture(db,first,a)
    refresh=run(db,a,[vid]);assert auto_commit_capture(db,refresh,a)==1
    mixed=run(db,a,[vid,new]);assert auto_commit_capture(db,mixed,a)==0
    assert len(latest_posts(db))==1
    upsert_post(db,a,'只存在CSV中的作品',external_id=new,source='csv',metrics={'views':5})
    assert auto_commit_capture(db,run(db,a,[new]),a)==0
    other=add_account(db,'douyin','other');upsert_post(db,other,'重复归属',external_id=vid,metrics={'views':3})
    ambiguous=run(db,a,[vid]);assert auto_commit_capture(db,ambiguous,a)==0


def test_csv_record_alone_is_not_a_reviewed_capture(tmp_path):
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me');vid='7412345678901234567'
    upsert_post(db,a,'已有CSV',external_id=vid,source='csv',metrics={'views':3})
    assert auto_commit_capture(db,run(db,a,[vid]),a)==0


def test_204_record_pipeline_reconciles_privacy_without_changing_historical_metrics(tmp_path):
    from datetime import datetime,timedelta,timezone
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me')
    base=datetime(2026,6,22,tzinfo=timezone.utc)
    rows=[dict(video_id=str(7412345678901234500+i),title=f'作品{i}',
        published_at=(base+timedelta(minutes=i)).isoformat(),
        cover_url=f'https://p3.douyinpic.com/origin-{i}.jpg',
        visibility='private' if i<71 else None,views=0 if i<172 else 100,
        likes=0 if 167<=i<172 else 1) for i in range(204)]
    first=create_capture(db,a);stage_rows(db,first,rows);finish_capture(db,first);commit_capture(db,first,a)
    assert summary(latest_posts(db))['pending']==101
    fresh=create_capture(db,a);stage_rows(db,fresh,rows)
    cards=[dict(title=r['title'],published_at=r['published_at'],cover_url=f'https://p5.douyinpic.com/variant-{i}.jpg',
                visibility='private' if i<173 else 'public') for i,r in enumerate(rows)]
    updates=match_visible_metadata(cards,rows)
    stage_rows(db,fresh,updates);finish_capture(db,fresh)
    assert auto_commit_capture(db,fresh,a)==204
    actual=latest_posts(db);s=summary(actual)
    assert s['excluded']==173 and s['analysable']==31 and s['pending']==0
    assert next(r for r in actual if r['external_id']==rows[172]['video_id'])['views']==100
