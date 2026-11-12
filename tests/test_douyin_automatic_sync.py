import json
from types import SimpleNamespace
import pytest
from creatorlab.douyin_navigation import CreatorNavigator,CENTER,safe_manager_url
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture,auto_commit_capture
from creatorlab.hub import init_hub,add_account,latest_posts


class CreatorPage:
    def __init__(self):
        self.url=CENTER;self.login=True;self.verification=False;self.labels=[];self.clicks=[]
        self.href=''
    def evaluate(self,script):
        return {'login':self.login,'verification':self.verification,
                'candidates':[{'label':label,'href':self.href} for label in self.labels]}
    def get_by_text(self,label,exact):
        def click(**kwargs):
            self.clicks.append(label)
            if label=='内容管理':self.labels=['作品管理']
            else:self.url=CENTER+'example-observed-manager';self.labels=[]
        return SimpleNamespace(all=lambda:[SimpleNamespace(is_visible=lambda:True,click=click,evaluate=lambda js:self.href)])


def test_first_login_navigates_two_menu_levels_and_reuses_only_successful_path(tmp_path):
    nav=CreatorNavigator(tmp_path,1);page=CreatorPage()
    assert nav.entry_url()==CENTER
    assert nav.step(page,0)=='waiting_login' and not page.clicks
    page.login=False;page.labels=['内容管理']
    assert nav.step(page,3)=='navigating' and page.clicks==['内容管理']
    nav.step(page,12)
    assert page.clicks==['内容管理','作品管理']
    assert not nav.path.exists()  # A click alone cannot establish a working route.
    assert nav.step(page,16,has_list=True)=='collecting'
    assert CreatorNavigator(tmp_path,1).entry_url()==page.url
    assert CreatorNavigator(tmp_path,2).entry_url()==CENTER


def test_verification_pauses_even_after_collection_started_then_resumes(tmp_path):
    nav=CreatorNavigator(tmp_path,1);page=CreatorPage();page.login=False;page.labels=['作品管理']
    page.verification=True
    assert nav.step(page,0,has_list=True)=='waiting_verification'
    assert not page.clicks and not nav.path.exists()
    page.verification=False
    assert nav.step(page,4)=='navigating' and page.clicks==['作品管理']


def test_missing_menu_is_actionable_and_navigation_is_bounded(tmp_path):
    page=CreatorPage();page.login=False
    nav=CreatorNavigator(tmp_path,1)
    assert nav.step(page,0)=='navigating'
    assert nav.step(page,31)=='navigation_needed'
    page.labels=['内容管理'];page.href='https://example.com/manager'
    nav.step(page,40)
    assert not page.clicks
    for i in range(10):nav.step(page,50+i*10)
    assert not page.clicks


@pytest.mark.parametrize('url',[
    'http://creator.douyin.com/manage','https://creator.douyin.com.evil.test/manage',
    'https://creator.douyin.com/login','https://creator.douyin.com/manage?token=secret',
    'https://creator.douyin.com/manage#secret',CENTER,'javascript:alert(1)',
])
def test_cached_entry_never_accepts_external_or_auth_material(url):
    assert safe_manager_url(url) is None


def capture(db,aid,vid,owner='uid:123',views=100):
    run=create_capture(db,aid)
    stage_rows(db,run,[{'video_id':vid,'title':'作品','owner_key':owner,'views':views,'likes':10}])
    finish_capture(db,run)
    return run


def test_manual_first_review_binds_author_next_capture_updates_automatically(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    vid='7412345678901234567'
    first=capture(db,aid,vid)
    assert auto_commit_capture(db,first,aid)==0 and latest_posts(db)==[]
    assert commit_capture(db,first,aid)==1
    second=capture(db,aid,vid,views=150)
    assert auto_commit_capture(db,second,aid)==1
    assert len(latest_posts(db))==1 and latest_posts(db)[0]['views']==150
    assert auto_commit_capture(db,second,aid)==0


def test_unknown_or_changed_author_never_auto_imports_and_no_account_leak(tmp_path):
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me');b=add_account(db,'douyin','other')
    first=capture(db,a,'7412345678901234567');commit_capture(db,first,a)
    for owner in (None,'uid:999','sec:unknown'):
        run=capture(db,a,'7412345678901234568',owner=owner)
        assert auto_commit_capture(db,run,a)==0
    assert len(latest_posts(db))==1
    wrong=capture(db,a,'7412345678901234569',owner='uid:999')
    with pytest.raises(ValueError,match='作者标识'):commit_capture(db,wrong,a)
    other=capture(db,b,'7412345678901234569')
    assert auto_commit_capture(db,other,b)==0
    assert auto_commit_capture(db,other,a)==0


def test_one_identityless_work_or_later_response_keeps_whole_capture_for_review(tmp_path):
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me');vid='7412345678901234567'
    first=capture(db,a,vid);commit_capture(db,first,a)
    run=create_capture(db,a)
    stage_rows(db,run,[{'video_id':vid,'title':'作品','owner_key':'uid:123','views':200}])
    stage_rows(db,run,[{'video_id':vid,'title':'作品','views':300}])
    finish_capture(db,run)
    assert auto_commit_capture(db,run,a)==0 and latest_posts(db)[0]['views']==100


def test_auto_import_failure_preserves_pending_capture_and_original_values(tmp_path,monkeypatch):
    import creatorlab.douyin_capture as module
    db=tmp_path/'d.db';init_hub(db);a=add_account(db,'douyin','me');vid='7412345678901234567'
    first=capture(db,a,vid);commit_capture(db,first,a)
    second=capture(db,a,vid,views=200)
    def fail(*args,**kwargs):raise OSError('simulated full disk')
    monkeypatch.setattr(module,'upsert_post',fail)
    with pytest.raises(OSError):auto_commit_capture(db,second,a)
    assert latest_posts(db)[0]['views']==100
    from creatorlab.douyin_capture import pending_captures
    assert any(r['id']==second for r in pending_captures(db))


def test_browser_pipeline_auto_navigates_then_reuses_session_route_and_imports(tmp_path,monkeypatch):
    import sys
    import creatorlab.sync_browser as sync
    from creatorlab.douyin_capture import pending_captures
    manager_url=CENTER+'example-observed-manager'
    raw=json.dumps({'data':{'items':[{'id':'7412345678901234567','description':'作品','create_time':1720000000,
        'author':{'uid':'123'},'metrics':{'play_count':100,'like_count':10,'comment_count':1,
        'collect_count':2,'share_count':1,'completion_rate':.4}}],'total':1,'has_more':0}})
    navigations=[];clicks=[]
    class Page:
        url=CENTER
        def goto(self,url,**kwargs):
            self.url=url;navigations.append(url)
            if url==manager_url:self.owner.handler(SimpleNamespace(url=CENTER+'work_list/',status=200,text=lambda:raw))
        def wait_for_timeout(self,ms):pass
        def evaluate(self,script):
            from creatorlab.douyin_navigation import NAV_EVIDENCE
            if script==NAV_EVIDENCE:return {'login':False,'verification':False,'candidates':[{'label':'作品管理'}]}
            return []
        def get_by_text(self,label,exact):
            def click(**kwargs):clicks.append(label);self.goto(manager_url)
            return SimpleNamespace(all=lambda:[SimpleNamespace(is_visible=lambda:True,evaluate=lambda js:'',click=click)])
    class Context:
        def __init__(self):
            p=Page();p.owner=self;self.pages=[p]
        def on(self,event,handler):self.handler=handler
        def route(self,*args):pass
        def add_init_script(self,*args):pass
        def close(self):self.pages=[]
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**kw:Context()))
        def __exit__(self,*args):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    clock=[0]
    def tick():clock[0]+=1;return clock[0]
    monkeypatch.setattr(sync.time,'monotonic',tick)
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    assert sync.start(db,tmp_path,account_id=aid)==0
    assert clicks==['作品管理'] and not latest_posts(db)
    first=pending_captures(db)[0];commit_capture(db,first['id'],aid)
    assert sync.start(db,tmp_path,account_id=aid)==0
    assert navigations==[CENTER,manager_url,manager_url]
    assert clicks==['作品管理']  # Remembered path bypasses the menu on the next run.
    status=json.loads((tmp_path/'local'/'sync_status.json').read_text())
    assert status['state']=='imported' and status['count']==1 and status['coverage']['completion_rate']==1
    assert latest_posts(db)[0]['views']==100
