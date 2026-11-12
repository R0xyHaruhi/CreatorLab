from datetime import date
from creatorlab.benchmarks import save_account,list_accounts,match_peers
from creatorlab.workspaces import get_mode,set_mode

def test_workspace_persists(tmp_path):
    db=tmp_path/'db.sqlite';assert get_mode(db)=='creator';set_mode(db,'team');assert get_mode(db)=='team'

def test_peer_matching_and_provenance(tmp_path):
    db=tmp_path/'db.sqlite'
    save_account(db,dict(platform='douyin',handle='peerA',tags='COS,动漫',followers=1000,median_views=1500,engagement_rate=.05,posts_30d=8,source_type='manual',observed_at='2026-10-24'))
    save_account(db,dict(platform='douyin',handle='peerB',tags='科技',niche='科技',followers=200000,source_type='manual',observed_at='2025-01-01'))
    accounts=list_accounts(db)
    target=dict(platform='douyin',handle='myself',tags='COS,动漫',niche='COS/二次元',followers=1100,median_views=1600,engagement_rate=.05)
    out=match_peers(target,accounts,today=date(2026,10,24))
    assert out[0]['handle']=='peerA'
    assert out[0]['confidence']>out[1]['confidence']
    assert '近期增长' in out[0]['missing']
    assert match_peers(target,accounts,mode='similar',today=date(2026,10,24))[0]['segment']=='同量级'

def test_demo_excluded(tmp_path):
    db=tmp_path/'db.sqlite';save_account(db,dict(platform='douyin',handle='demo',source_type='demo'))
    assert list_accounts(db)==[]
    assert len(list_accounts(db,include_demo=True))==1

def test_upsert(tmp_path):
    db=tmp_path/'db.sqlite';save_account(db,dict(platform='douyin',handle='a',followers=10,source_type='manual'))
    save_account(db,dict(platform='douyin',handle='a',followers=20,source_type='manual'))
    assert len(list_accounts(db))==1 and list_accounts(db)[0]['followers']==20
