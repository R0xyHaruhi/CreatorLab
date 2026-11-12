import io,json,sys
from types import SimpleNamespace
import pytest
from PIL import Image
from creatorlab.hub import init_hub,add_account
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,pending_captures


def test_metadata_only_event_does_not_blank_the_review_preview(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','one')
    run=create_capture(db,aid)
    stage_rows(db,run,[dict(video_id='7412345678901234567',title='作品',views=123,likes=5)])
    stage_rows(db,run,[dict(video_id='7412345678901234567',title='作品',media_format='video')])
    finish_capture(db,run)
    assert pending_captures(db)[0]['preview'][0]['views']==123


def test_image_has_no_video_retention_score_even_if_source_returns_zero():
    from creatorlab.content_analysis import frame
    row=dict(id=1,account_id=1,platform='douyin',title='图文',views=100,media_format='image',completion_rate=0,bounce_rate_2s=0,published_at='2026-01-01T00:00:00Z',metric_recorded_at='2026-01-08T00:00:00Z')
    result=frame([row]).iloc[0]
    assert result['completion_rate'] is None and result['bounce_rate_2s'] is None


@pytest.mark.parametrize('with_covers',[False,True])
def test_false_source_end_does_not_skip_more_ui_pages_and_complete_metrics_still_cache_covers(tmp_path,monkeypatch,with_covers):
    import creatorlab.sync_browser as sync
    from creatorlab.covers import save_cover
    def item(i):
        return dict(id=str(7412345678901234500+i),description='作品'+str(i),create_time=1720000000,
          cover='https://p3.douyinpic.com/cover'+str(i)+'.jpg' if with_covers else None,
          metrics=dict(play_count=100,like_count=5,comment_count=2,share_count=1,collect_count=3,completion_rate=.4))
    def response(items):return SimpleNamespace(url=sync.CENTER+'work_list/',status=200,text=lambda:json.dumps({'data':{'items':items,'total':3,'has_more':False}}))
    class Page:
        url=sync.CENTER
        def goto(self,url,**kw):context.handler(response([item(0),item(1)]))
        def wait_for_timeout(self,*a):pass
        def evaluate(self,script,*a):
            if script==sync.ADVANCE_UI:
                context.handler(response([item(2)]));return 'scroll'
            return []
        def locator(self,*a):return SimpleNamespace(count=lambda:0)
    page=Page()
    class Context:
        pages=[page]
        def on(self,event,handler):self.handler=handler
        def add_init_script(self,*a):pass
        def route(self,*a):pass
        def close(self):self.pages=[]
    context=Context()
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:context))
        def __exit__(self,*a):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    ticks=[0]
    def clock():ticks[0]+=1;return ticks[0]
    monkeypatch.setattr(sync.time,'monotonic',clock)
    fetched=[]
    def fetch(ctx,db,platform,vid,url):
        data=io.BytesIO();Image.new('RGB',(80,80),'blue').save(data,format='PNG')
        save_cover(db,platform,vid,data.getvalue(),'browser_loaded_platform_cover',url);fetched.append(vid);return True
    monkeypatch.setattr('creatorlab.covers.fetch_browser_cover',fetch)
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','one')
    assert sync.start(db,tmp_path,account_id=aid)==0
    status=json.loads((tmp_path/'local/sync_status.json').read_text())
    assert status['count']==3 and status['list_end_reason']=='inventory_matched'
    assert status['pages']==2 and status['details']==0
    assert len(fetched)==(3 if with_covers else 0)
    assert status['with_cover']==(3 if with_covers else 0)


def test_visible_end_needs_matching_card_count_and_no_parser_rejections():
    from creatorlab.work_formats import visible_list_exhausted
    assert visible_list_exhausted(204,0,{'count':204,'ended':True})
    assert not visible_list_exhausted(203,0,{'count':204,'ended':True})
    assert not visible_list_exhausted(204,1,{'count':204,'ended':True})
    assert not visible_list_exhausted(204,0,{'count':204,'ended':False})
