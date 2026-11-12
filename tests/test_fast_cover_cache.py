import io
from types import SimpleNamespace

from PIL import Image

from creatorlab.covers import cache_missing_covers,cached_cover,save_cover,fetch_browser_cover
from creatorlab.hub import init_hub


def png():
    out=io.BytesIO();Image.new('RGB',(80,80),'blue').save(out,format='PNG');return out.getvalue()


def test_missing_only_failure_is_retryable_and_existing_cover_is_preserved(tmp_path,monkeypatch):
    db=tmp_path/'cover.db';init_hub(db)
    save_cover(db,'douyin','old',png(),'user_upload')
    before=cached_cover(db,'douyin','old');calls=[]
    def fetch(ctx,db,platform,vid,url,**kw):
        calls.append(vid)
        if vid=='new':save_cover(db,platform,vid,png(),'test',url);return True
        return False
    monkeypatch.setattr('creatorlab.covers.fetch_browser_cover',fetch)
    rows=[dict(video_id=v,cover_url='https://p26-sign.douyinpic.com/'+v+'.jpg') for v in ('old','new','failed')]
    rows.append(dict(video_id='private',cover_url=rows[0]['cover_url'],visibility='private'))
    assert cache_missing_covers(None,db,'douyin',rows)==(2,3)
    assert calls==['new','failed'] and cached_cover(db,'douyin','old')==before
    assert cache_missing_covers(None,db,'douyin',rows)==(2,3)
    assert calls==['new','failed','failed']
    assert cache_missing_covers(None,db,'douyin',rows,stopped=lambda:True)==(2,3)
    assert calls==['new','failed','failed']


def test_deadline_prevents_request_and_bounds_redirect_timeout(tmp_path,monkeypatch):
    db=tmp_path/'cover.db';init_hub(db);calls=[];disposed=[]
    response=SimpleNamespace(status=302,headers={'location':'https://p26-sign.douyinpic.com/two.jpg'},dispose=lambda:disposed.append(True))
    def get(url,**kw):calls.append(kw['timeout']);return response
    ctx=SimpleNamespace(request=SimpleNamespace(get=get))
    monkeypatch.setattr('creatorlab.covers.cover_current',lambda *a:False)
    monkeypatch.setattr('time.monotonic',lambda:10)
    assert not fetch_browser_cover(ctx,db,'douyin','one','https://p26-sign.douyinpic.com/one.jpg',deadline=9)
    assert not calls
    ticks=iter([10,12])
    monkeypatch.setattr('time.monotonic',lambda:next(ticks))
    assert not fetch_browser_cover(ctx,db,'douyin','one','https://p26-sign.douyinpic.com/one.jpg',deadline=11)
    assert calls==[1000] and disposed==[True]
