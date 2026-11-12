import pytest
from creatorlab.bridge import clean_import,save_import,get_token

def test_roundtrip(tmp_path):
    db=tmp_path/'data.db'
    inp={'url':'https://www.douyin.com/video/7123456789012345678','name':'测试作品','likes':123,'views':None,'comments':0}
    x=save_import(db,inp)
    assert x['id']>0
    from creatorlab.storage import connection
    with connection(db) as con:
        item=con.execute('SELECT * FROM linked_videos').fetchone()
        assert item['likes']==123 and item['views'] is None and item['comments']==0
        assert item['metrics_source']=='browser_user_reviewed'
    save_import(db,{'url':inp['url'],'name':'新版名称','likes':None})
    with connection(db) as con:
        item=con.execute('SELECT * FROM linked_videos').fetchone()
        assert item['likes']==123 and item['display_name']=='新版名称'
        assert con.execute('SELECT COUNT(*) FROM browser_import_history').fetchone()[0]==2

def test_invalid_input():
    with pytest.raises(ValueError): clean_import({'url':'https://evil.example/video/1'})
    with pytest.raises(ValueError): clean_import({'url':'https://www.douyin.com/video/123','likes':'3.5'})
    with pytest.raises(ValueError): clean_import({'url':'https://www.tiktok.com/@a/video/123'})

def test_token(tmp_path):
    assert get_token(tmp_path)==get_token(tmp_path)
    assert len(get_token(tmp_path))>30
