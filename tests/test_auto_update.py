import json
import sys
from types import SimpleNamespace
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture
from creatorlab import auto_update as auto

OLD='7412345678901234567'
NEW='7412345678901234568'


def seed(db):
    init_hub(db);aid=add_account(db,'douyin','me','我的抖音')
    run=create_capture(db,aid)
    stage_rows(db,run,[dict(video_id=OLD,title='已有作品',views=100)])
    finish_capture(db,run);commit_capture(db,run,aid)
    return aid


def test_configuration_is_opt_in_and_only_reviewed_unambiguous_ids_qualify(tmp_path):
    db=tmp_path/'d.db';aid=seed(db)
    assert auto.load(db)=={} and not auto.config_path(db).exists()
    upsert_post(db,aid,'尚未核对',NEW,metrics={'views':200})
    assert auto.eligible_ids(db,aid)=={OLD}
    other=add_account(db,'douyin','other')
    upsert_post(db,other,'同ID归属不明',OLD,metrics={'views':300})
    assert not auto.eligible_ids(db,aid)
    import pytest
    with pytest.raises(ValueError):auto.configure(db,aid,True)


def test_due_time_lease_pause_and_manual_collection_are_respected(tmp_path,monkeypatch):
    import creatorlab.bilibili_import as imports
    db=tmp_path/'d.db';aid=seed(db);auto.configure(db,aid,True,24,now=100)
    monkeypatch.setattr(imports,'job_running',lambda *a:False)
    calls=[]
    spawn=lambda aid,token:calls.append((aid,token))
    assert not auto.launch_due(db,tmp_path,now=129,spawn=spawn)
    assert auto.launch_due(db,tmp_path,now=131,spawn=spawn)
    assert not auto.launch_due(db,tmp_path,now=132,spawn=spawn)
    assert len(calls)==1
    auto.finish(db,aid,calls[0][1],4,'请先登录',now=140)
    assert not auto.launch_due(db,tmp_path,now=100000,spawn=spawn)
    auto.configure(db,aid,True,6,now=100000)
    monkeypatch.setattr(imports,'job_running',lambda *a:True)
    assert not auto.launch_due(db,tmp_path,now=100040,spawn=spawn)
    monkeypatch.setattr(imports,'job_running',lambda *a:False)
    assert auto.launch_due(db,tmp_path,now=100040,spawn=spawn)
    auto.finish(db,aid,'stale-token',0,'不应覆盖',now=100050)
    assert auto.load(db)[str(aid)]['message']=='正在后台更新已入库作品'
    auto.finish(db,aid,calls[-1][1],0,'已更新',now=100060)
    assert auto.load(db)[str(aid)]['last_success']==100060
    auto.configure(db,aid,False,now=100070)
    assert not auto.launch_due(db,tmp_path,now=1000000,spawn=spawn)


def test_worker_rechecks_opt_in_and_uses_existing_only_mode(tmp_path,monkeypatch):
    import creatorlab.bilibili_import as imports
    import creatorlab.sync_browser as sync
    db=tmp_path/'d.db';aid=seed(db);auto.configure(db,aid,True,now=0)
    monkeypatch.setattr(imports,'job_running',lambda *a:False)
    calls=[];auto.launch_due(db,tmp_path,now=31,spawn=lambda a,t:calls.append(t))
    attempts=[]
    def start(*a,**kw):attempts.append(kw);return 0
    monkeypatch.setattr(sync,'start',start)
    auto.worker(db,tmp_path,aid,'wrong-token');assert not attempts
    auto.worker(db,tmp_path,aid,calls[0]);assert attempts==[dict(account_id=aid,mode='existing')]
    assert auto.load(db)[str(aid)]['last_success']
    auto.configure(db,aid,False)
    auto.worker(db,tmp_path,aid,calls[0]);assert len(attempts)==1


def test_crashed_worker_lease_recovers_after_startup_grace_without_waiting_half_hour(tmp_path,monkeypatch):
    import creatorlab.bilibili_import as imports
    db=tmp_path/'d.db';aid=seed(db);auto.configure(db,aid,True,now=100)
    monkeypatch.setattr(imports,'job_running',lambda *a:False)
    tokens=[];spawn=lambda a,t:tokens.append(t)
    assert auto.launch_due(db,tmp_path,now=131,spawn=spawn)
    assert not auto.launch_due(db,tmp_path,now=180,spawn=spawn)
    assert auto.launch_due(db,tmp_path,now=192,spawn=spawn)
    assert len(set(tokens))==2
    auto.finish(db,aid,tokens[0],0,'stale worker',now=193)
    assert auto.load(db)[str(aid)]['token']==tokens[1]


def test_malformed_or_copied_configuration_never_enables_jobs(tmp_path):
    db=tmp_path/'d.db'
    auto.config_path(db).write_text(json.dumps({'database':str(db.resolve()),'accounts':{'1':None,'x':{'enabled':True}}}))
    assert auto.load(db)=={}
    auto.config_path(db).write_text(json.dumps({'database':str((tmp_path/'other.db').resolve()),'accounts':{'1':{'enabled':True,'hours':24}}}))
    assert auto.load(db)=={}


def test_settings_save_starts_service_without_running_real_collection(tmp_path,monkeypatch):
    import creatorlab.auto_update_ui as ui
    db=tmp_path/'d.db';aid=seed(db);services=[]
    monkeypatch.setattr(ui,'_service',lambda *a:services.append(a))
    ui.ensure_service(db,tmp_path);assert not services
    app=AppTest.from_string('from creatorlab.auto_update_ui import panel\npanel('+repr(str(db))+','+repr(str(tmp_path))+')').run()
    assert not app.exception and not app.toggle[0].value
    app.toggle[0].set_value(True)
    next(b for b in app.button if b.label=='保存自动更新设置').click().run()
    assert not app.exception and auto.load(db)[str(aid)]['enabled'] and services
    assert len(latest_posts(db))==1 and latest_posts(db)[0]['views']==100


def test_automatic_browser_refreshes_existing_only_and_pauses_at_login(tmp_path,monkeypatch):
    import creatorlab.sync_browser as sync
    from creatorlab.douyin_navigation import NAV_EVIDENCE
    db=tmp_path/'d.db';aid=seed(db)
    raw=json.dumps({'data':{'items':[{'id':OLD,'description':'已有作品','cover':'https://p26-sign.douyinpic.com/old.jpg','metrics':{'play_count':250}},
                                   {'id':NEW,'description':'不能自动导入的新作品','cover':'https://p26-sign.douyinpic.com/new.jpg','metrics':{'play_count':90}}],
                            'total':300,'has_more':1}})
    logged_in=[True];launch_options=[]
    class Page:
        url=sync.CENTER
        def goto(self,url,**kw):
            self.url=url
            if logged_in[0]:ctx.handler(SimpleNamespace(url=sync.CENTER+'work_list/',status=200,text=lambda:raw))
        def wait_for_timeout(self,ms):pass
        def evaluate(self,script):
            if script==NAV_EVIDENCE:return dict(login=not logged_in[0],verification=False,candidates=[])
            return []
    class Context:
        def __init__(self):self.pages=[Page()]
        def on(self,event,handler):self.handler=handler
        def remove_listener(self,*a):pass
        def route(self,*a):pass
        def add_init_script(self,*a):pass
        def close(self):self.pages=[]
    ctx=Context()
    def launch(*a,**kw):launch_options.append(kw);return ctx
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        def __exit__(self,*a):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    fetched=[]
    monkeypatch.setattr('creatorlab.covers.fetch_browser_cover',lambda ctx,db,platform,vid,url,**kw:fetched.append(vid) or True)
    assert sync.start(db,tmp_path,account_id=aid,mode='existing')==0
    assert fetched==[OLD]  # No newly discovered identity enters the cover pass.
    assert launch_options[0]['headless'] is True
    assert len(latest_posts(db))==1 and latest_posts(db)[0]['views']==250
    status=json.loads((tmp_path/'local'/'sync_status.json').read_text())
    assert status['new_count']==0 and status['refreshed_count']==1
    assert status['list_end_reason']=='existing_targets_read' and not status['inventory_complete']
    logged_in[0]=False;ctx=Context()
    assert sync.start(db,tmp_path,account_id=aid,mode='existing')==4
    assert len(latest_posts(db))==1 and latest_posts(db)[0]['views']==250
    assert json.loads((tmp_path/'local'/'sync_status.json').read_text())['state']=='waiting_login'
    from creatorlab.douyin_ui import read_status
    from creatorlab.task_ui import task_status
    assert read_status(tmp_path)['state']=='waiting_login'
    assert task_status(tmp_path,'douyin',db)['state']=='waiting_login'
