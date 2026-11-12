import pytest
from creatorlab.links import parse_video_link, LinkError
from creatorlab.storage import init_db, add_link, list_links, update_link

def test_links():
    t=parse_video_link('https://www.tiktok.com/@someone/video/746123456789?lang=en')
    assert t['platform']=='tiktok' and t['video_id']=='746123456789'
    d=parse_video_link('分享给你 https://v.douyin.com/AbC123/ 复制打开抖音')
    assert d['platform']=='douyin'
    assert parse_video_link('https://www.douyin.com/video/777?foo=1')['video_id']=='777'

@pytest.mark.parametrize('bad',['http://www.tiktok.com/@x/video/123','https://evil.example/video/123','https://www.tiktok.com.evil.com/@x/video/123','no link'])
def test_reject(bad):
    with pytest.raises(LinkError): parse_video_link(bad)

def test_save_unknown_metrics(tmp_path):
    db=tmp_path/'db.sqlite'; init_db(db)
    item=parse_video_link('https://www.tiktok.com/@someone/video/746123456789')
    idx=add_link(db,item,display_name='my clip')
    assert list_links(db)[0]['views'] is None
    with pytest.raises(ValueError): add_link(db,item)
    update_link(db,idx,{'views':123,'display_name':'new name'})
    assert list_links(db)[0]['views']==123
    assert list_links(db)[0]['metrics_source']=='manual'
