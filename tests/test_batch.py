import pytest
from creatorlab.bridge import save_batch, list_batch, clean_batch_row
from creatorlab.storage import connection

def test_batch_dedup_and_history(tmp_path):
    db=tmp_path/'creatorlab.db'
    row={'title':'长门有希变装测试','published_at':'2026-08-20 03:36','views':14000,'likes':468,'comments':32,'shares':88}
    r=save_batch(db,{'rows':[row]})
    assert (r['created'],r['updated'])==(1,0)
    newer={**row,'likes':550,'views':17000}
    r=save_batch(db,{'rows':[newer]})
    assert (r['created'],r['updated'])==(0,1)
    assert len(list_batch(db))==1 and list_batch(db)[0]['views']==17000
    with connection(db) as con:
        assert con.execute('SELECT COUNT(*) FROM creator_center_metric_history').fetchone()[0]==2

def test_missing_metric_keeps_prior(tmp_path):
    db=tmp_path/'c.db';row={'title':'COS作品','views':123,'likes':50}
    save_batch(db,{'rows':[row]});save_batch(db,{'rows':[{'title':'COS作品','views':456}]})
    assert list_batch(db)[0]['likes']==50

def test_invalid():
    with pytest.raises(ValueError):clean_batch_row({'title':'xx'})
    with pytest.raises(ValueError):clean_batch_row({'title':'xx','likes':'1.5'})
    with pytest.raises(ValueError):clean_batch_row({'title':'xx','likes':1,'url':'https://bad.test/evil'})
    with pytest.raises(ValueError):save_batch('/tmp/dummy.db',{'rows':[]})
