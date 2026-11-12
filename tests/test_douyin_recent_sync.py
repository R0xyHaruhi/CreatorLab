import json
import sys
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,latest_posts,connect,upsert_post
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture,pending_captures

OLD='7412345678901234567'
NEW='7412345678901234568'


def captured(db,aid,rows,at=None):
    run=create_capture(db,aid);stage_rows(db,run,rows,observed_at=at);finish_capture(db,run)
    return run


def row(vid=OLD,views=100,owner='uid:123'):
    return dict(video_id=vid,title='真实作品'+vid,views=views,owner_key=owner)


def test_repeated_work_sets_share_review_but_keep_both_observations(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    first=captured(db,aid,[row(views=100)],'2026-01-01T00:00:00Z')
    second=captured(db,aid,[row(views=200)],'2026-01-02T00:00:00Z')
    runs=pending_captures(db)
    assert len(runs)==1 and len(runs[0]['duplicate_ids'])==1
    assert commit_capture(db,runs[0]['id'],aid)==1
    assert latest_posts(db)[0]['views']==200 and pending_captures(db)==[]
    with connect(db) as con:
        assert [r[0] for r in con.execute('SELECT views FROM hub_snapshots ORDER BY recorded_at')]==[100,200]
        assert con.execute('SELECT count(*) FROM clab_dy_events').fetchone()[0]==2
        assert {r[0] for r in con.execute('SELECT state FROM clab_dy_runs')}=={'committed','superseded'}
    assert commit_capture(db,runs[0]['id'],aid)==0


def test_grouping_never_uses_only_preview_or_combines_accounts_or_authors(tmp_path):
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me');b=add_account(db,'douyin','other')
    rows=[row(str(int(OLD)+i)) for i in range(6)]
    captured(db,a,rows);captured(db,a,[*rows[:5],row(str(int(OLD)+99))])
    captured(db,b,rows);captured(db,a,[dict(r,owner_key='uid:999') for r in rows])
    assert len(pending_captures(db))==4


def test_review_ui_shows_one_confirmation_for_repeated_measurements(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    captured(db,aid,[row()]);captured(db,aid,[row(views=200)])
    app=AppTest.from_string('from creatorlab.douyin_ui import review_captures\nreview_captures('+repr(str(db))+','+repr(str(tmp_path))+')').run()
    assert not app.exception
    assert len(app.checkbox)==1
    assert any('另有 1 次采集' in c.value for c in app.caption)
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label=='确认归属并入库').click().run()
    assert not app.exception and pending_captures(db)==[] and len(latest_posts(db))==1


@pytest.mark.parametrize('bound',[True,False])
def test_recent_page_does_not_paginate_or_visit_details_and_new_work_is_ready(tmp_path,monkeypatch,bound):
    import creatorlab.sync_browser as sync
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    old=captured(db,aid,[row(owner='uid:123' if bound else None)]);commit_capture(db,old,aid)
    raw=json.dumps({'data':{'items':[
        {'id':NEW,'description':'昨天新发的作品','create_time':1720000000,
         'cover':'https://p26-sign.douyinpic.com/new.jpg',
         **({'author':{'uid':'123'}} if bound else {}),'metrics':{'play_count':120}},
        {'id':OLD,'description':'旧作品',**({'author':{'uid':'123'}} if bound else {}),'metrics':{'play_count':250}}
    ],'total':300,'has_more':1}})
    calls=[]
    fetched=[]
    def fetch(ctx,db,platform,vid,url,**kw):
        from creatorlab.covers import save_cover
        import io
        from PIL import Image
        data=io.BytesIO();Image.new('RGB',(80,80),'blue').save(data,format='PNG')
        save_cover(db,platform,vid,data.getvalue(),'browser_request_platform_cover',url)
        fetched.append(vid);return True
    monkeypatch.setattr('creatorlab.covers.fetch_browser_cover',fetch)
    class Page:
        url=sync.CENTER
        def goto(self,url,**kw):
            calls.append(url);ctx.handler(SimpleNamespace(url=sync.CENTER+'work_list/',status=200,text=lambda:raw))
        def wait_for_timeout(self,ms):pass
        def evaluate(self,script):
            from creatorlab.douyin_navigation import NAV_EVIDENCE
            if script==NAV_EVIDENCE:return {'login':False,'verification':False,'candidates':[]}
            raise AssertionError('Recent sync must not advance the list or inspect public details')
    class Context:
        def __init__(self):self.pages=[Page()]
        def on(self,event,handler):self.handler=handler
        def remove_listener(self,event,handler):self.handler=None
        def route(self,*a):pass
        def add_init_script(self,*a):pass
        def new_page(self):raise AssertionError('Recent sync must not open detail pages')
        def close(self):self.pages=[]
    ctx=Context()
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**kw:ctx))
        def __exit__(self,*a):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    def wait_for_review(context,db,run_id,stop_file):
        assert context.pages and pending_captures(db)
        assert context.handler is None
        return 'closed'
    monkeypatch.setattr(sync,'wait_for_capture_review',wait_for_review)
    assert sync.start(db,tmp_path,account_id=aid,mode='recent')==0
    assert calls==[sync.CENTER]
    assert fetched==[NEW]
    from creatorlab.covers import cached_cover
    assert cached_cover(db,'douyin',NEW)
    status=json.loads((tmp_path/'local'/'sync_status.json').read_text())
    assert status['new_count']==1 and status['count']==2 and status['pages']==1 and status['details']==0
    assert status['list_end_reason']=='first_page_saved' and not status['inventory_complete']
    posts=latest_posts(db)
    if bound:
        assert status['state']=='imported' and {p['external_id'] for p in posts}=={OLD,NEW}
        assert next(p for p in posts if p['external_id']==NEW)['completion_rate'] is None
    else:
        assert status['state']=='review' and {p['external_id'] for p in posts}=={OLD}
        assert pending_captures(db)[0]['count']==2


def test_launcher_defaults_to_recent_after_first_import_and_keeps_full_scan(tmp_path,monkeypatch):
    import creatorlab.douyin_ui as ui
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    calls=[];monkeypatch.setattr(ui,'job_running',lambda *a:False)
    monkeypatch.setattr(ui.subprocess,'Popen',lambda args,**kw:calls.append(args))
    def mode():return calls[-1][calls[-1].index('--mode')+1]
    ui.launch(db,tmp_path,account_id=aid);assert mode()=='full'
    upsert_post(db,aid,'已有作品',OLD,metrics={'views':100})
    ui.launch(db,tmp_path,account_id=aid);assert mode()=='recent'
    ui.launch(db,tmp_path,account_id=aid,repair=True);assert mode()=='full'
    ui.launch(db,tmp_path,account_id=aid,mode='full');assert mode()=='full'
    with pytest.raises(ValueError):ui.launch(db,tmp_path,account_id=aid,mode='invalid')


def test_wait_keeps_source_open_until_confirmation_and_closed_window_is_normal(tmp_path,monkeypatch):
    import creatorlab.sync_browser as sync
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    run=captured(db,aid,[row(NEW,owner=None)])
    waits=[]
    def confirm(ms):
        waits.append(ms)
        assert pending_captures(db) and not latest_posts(db)
        commit_capture(db,run,aid)
    context=SimpleNamespace(pages=[SimpleNamespace(wait_for_timeout=confirm)])
    assert sync.wait_for_capture_review(context,db,run,tmp_path/'stop')=='committed'
    assert waits==[500] and latest_posts(db)[0]['external_id']==NEW
    # A repeated finish during teardown must never reopen a committed capture.
    finish_capture(db,run)
    assert pending_captures(db)==[]
    second=captured(db,aid,[row(NEW,views=200,owner=None)])
    assert sync.wait_for_capture_review(SimpleNamespace(pages=[]),db,second,tmp_path/'stop')=='closed'
    assert pending_captures(db)[0]['id']==second


def test_wait_timeout_and_stop_preserve_the_staged_new_work(tmp_path,monkeypatch):
    import creatorlab.sync_browser as sync
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    run=captured(db,aid,[row(NEW,owner=None)])
    clock=[0]
    def tick():clock[0]+=1;return clock[0]
    monkeypatch.setattr(sync.time,'monotonic',tick)
    context=SimpleNamespace(pages=[SimpleNamespace(wait_for_timeout=lambda ms:None)])
    stop=tmp_path/'stop'
    assert sync.wait_for_capture_review(context,db,run,stop,timeout=3)=='timeout'
    stop.touch()
    assert sync.wait_for_capture_review(context,db,run,stop)=='stopped'
    assert pending_captures(db)[0]['new_count']==1 and latest_posts(db)==[]


def test_pending_preview_prioritizes_new_works_and_confirmation_works_with_open_browser(tmp_path,monkeypatch):
    import creatorlab.douyin_ui as ui
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    old_rows=[row(str(int(OLD)+i)) for i in range(6)]
    for r in old_rows:upsert_post(db,aid,r['title'],r['video_id'],metrics={'views':100})
    newest=str(int(OLD)+100)
    run=captured(db,aid,[*old_rows,row(newest,owner=None)])
    pending=pending_captures(db)[0]
    assert pending['new_count']==1 and pending['preview'][0]['video_id']==newest
    monkeypatch.setattr(ui,'job_running',lambda *a:True)
    app=AppTest.from_string('from creatorlab.douyin_ui import review_captures\nreview_captures('+repr(str(db))+','+repr(str(tmp_path))+')').run()
    app.checkbox[0].check().run()
    assert not app.button(key='capture_commit_'+run).disabled
    app.button(key='capture_commit_'+run).click().run()
    assert not app.exception and pending_captures(db)==[] and len(latest_posts(db))==7
