from creatorlab.bridge import save_batch, list_batch
from creatorlab.storage import connection

def test_network_ids_are_dedup_and_extra_stats(tmp_path):
    db=tmp_path/'test.db'
    a={'video_id':'7676060920421874379','title':'作品 A','published_at':'2026-10-23T01:43:00Z',
       'likes':468,'comments':32,'shares':88,'completion_rate':0.159904,'avg_view_second':6.3363}
    assert save_batch(db,{'source':'network','rows':[a]})['created']==1
    b={**a,'title':'作品 A 后来改名','likes':500}
    assert save_batch(db,{'source':'network','rows':[b]})['updated']==1
    rows=list_batch(db);assert len(rows)==1 and rows[0]['video_id']==a['video_id']
    assert rows[0]['likes']==500 and rows[0]['completion_rate']==0.159904
    assert rows[0]['source']=='creator_center_network_user_confirmed'
    with connection(db) as con:
        assert con.execute('SELECT COUNT(*) FROM creator_center_metric_history').fetchone()[0]==2

def test_v08_upgrade_merge(tmp_path):
    db=tmp_path/'test.db'
    old={'title':'旧作品','published_at':'2026-10-23T01:43:00Z','likes':1}
    save_batch(db,{'rows':[old]})
    new={**old,'video_id':'7676060920421874379','likes':3}
    save_batch(db,{'source':'network','rows':[new]})
    assert len(list_batch(db))==1
    assert list_batch(db)[0]['likes']==3
