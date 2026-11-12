import hashlib
import pytest
from creatorlab.hub import init_hub,add_account,latest_posts
from creatorlab.weekly_reference import load_dataset,DATASET
from creatorlab.reference_workflow import save_scope,selected_scope,refresh_references,reference_view
from creatorlab.workflow_store import documents,store_path


def setup(db):
    init_hub(db)
    return add_account(db,'bilibili','123','我的账号')


def public_response(url):
    bvid=url.split('bvid=')[1]
    if '/tags?' in url:return dict(code=0,data=[dict(tag_name='COSPLAY')])
    return dict(code=0,data=dict(bvid=bvid,title='公开作品',stat=dict(view=123,like=5,reply=0)))


def test_scope_refresh_keeps_personal_and_bundled_records_untouched(tmp_path):
    db=tmp_path/'personal.db';aid=setup(db);info,records=load_dataset()
    digest=hashlib.sha256(DATASET.read_bytes()).hexdigest()
    chosen=records[0]['bvid']
    key=save_scope(db,aid,'角色学习参照','动漫区','COS与角色扮演',[chosen],{'tags':['COSPLAY']},records)
    result=refresh_references(db,aid,[chosen],fetch=public_response,pause=0)
    assert result['updated']==[chosen] and not result['failures']
    scope,samples=selected_scope(db,aid,key)
    assert scope['minor']=='COS与角色扮演' and samples[0]['views']==123
    assert samples[0]['comments']==0 and samples[0]['favorites'] is None
    assert samples[0]['normalized_tags']=={'cosplay'}
    assert samples[0]['observed_at']==documents(db,'reference',aid,'bilibili')[0]['data']['observed_at']
    assert latest_posts(db)==[] and store_path(db).exists()
    assert hashlib.sha256(DATASET.read_bytes()).hexdigest()==digest
    other=add_account(db,'bilibili','456')
    assert documents(db,'scope',other,'bilibili')==[]
    with pytest.raises(ValueError):selected_scope(db,other,key)


def test_reference_failure_is_logged_and_stops_without_claiming_full_refresh(tmp_path):
    db=tmp_path/'personal.db';aid=setup(db);_,records=load_dataset()
    ids=[r['bvid'] for r in records[:3]];calls=[]
    def blocked(url):calls.append(url);return dict(code=-412,data=None)
    result=refresh_references(db,aid,ids,fetch=blocked,pause=0)
    assert len(calls)==1 and result['updated']==[] and len(result['not_attempted'])==2
    assert documents(db,'reference',aid,'bilibili')==[]
    assert len(documents(db,'refresh',aid,'bilibili'))==1
    _,merged=reference_view(db,aid)
    assert merged[0]['views']==records[0]['views']
    dy=add_account(db,'douyin','me')
    with pytest.raises(ValueError):save_scope(db,dy,'wrong','动漫区','COS与角色扮演',ids,{},records)


def test_reference_id_mismatch_and_tag_failure_do_not_mix_times(tmp_path):
    db=tmp_path/'personal.db';aid=setup(db);_,records=load_dataset();bvid=records[0]['bvid']
    def missing_tags(url):
        return dict(code=-412,data=None) if '/tags?' in url else public_response(url)
    assert refresh_references(db,aid,[bvid],fetch=missing_tags,pause=0)['updated']==[]
    assert documents(db,'reference',aid,'bilibili')==[]
    with pytest.raises(ValueError):refresh_references(db,aid,[r['bvid'] for r in records[:11]],pause=0)
