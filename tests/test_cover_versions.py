import io
from PIL import Image
from creatorlab.hub import init_hub
from creatorlab.covers import save_cover,cover_current,cached_cover


def test_changed_origin_refreshes_but_signature_and_manual_cover_do_not(tmp_path):
    db=tmp_path/'cover.db';init_hub(db)
    data=io.BytesIO();Image.new('RGB',(80,80),'blue').save(data,format='PNG')
    first='https://i0.hdslb.com/bfs/archive/one.jpg@320w?token=old'
    save_cover(db,'bilibili','BV1',data.getvalue(),'browser_loaded_platform_cover',first)
    assert cached_cover(db,'bilibili','BV1')
    assert cover_current(db,'bilibili','BV1','https://i0.hdslb.com/bfs/archive/one.jpg@640w?token=new')
    assert not cover_current(db,'bilibili','BV1','https://i0.hdslb.com/bfs/archive/two.jpg')
    save_cover(db,'bilibili','BV1',data.getvalue(),'user_upload')
    assert cover_current(db,'bilibili','BV1','https://i0.hdslb.com/bfs/archive/two.jpg')
