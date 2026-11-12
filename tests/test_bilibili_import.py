import json
import sys
from types import SimpleNamespace
import pytest
from creatorlab.bilibili_import import parse_uid,parse_response,normalize,persist,job_lock,job_running,run
from creatorlab.hub import init_hub,latest_posts,snapshots,connect
from creatorlab.content_analysis import annotate

BV='BV1xx411c7mD';OTHER='BV1xx411c7mE'
URL='https://api.bilibili.com/x/space/wbi/arc/search?mid=123&pn=1'


def listing(items,total=None,pn=1):
    return json.dumps({'code':0,'data':{'list':{'vlist':items},'page':{'count':len(items) if total is None else total,'pn':pn,'ps':2}}})


def item(bv=BV,views=100):
    return {'bvid':bv,'mid':123,'title':'测试作品','play':views,'comment':4,'video_review':99,'created':1700000000,'length':'01:20','pic':'//i0.hdslb.com/example.jpg'}


def test_uid_validation():
    assert parse_uid('123')=='123'
    assert parse_uid('https://space.bilibili.com/123/upload/video?x=y')=='123'
    for bad in ['0','abc','https://space.bilibili.com.evil/123','https://x@space.bilibili.com/123','http://space.bilibili.com/123']:
        with pytest.raises(ValueError):parse_uid(bad)


def test_exact_metrics_identity_and_paging():
    result=parse_response(URL,listing([item()],total=3),'123')
    row=result['rows'][0]
    assert row['external_id']==BV and row['metrics']['views']==100
    assert row['metrics']['comments']==4  # danmaku must never become comments
    assert row['metrics']['likes'] is None and row['duration_seconds']==80
    assert row['cover_url'].startswith('https://')
    assert not result['ended']
    assert parse_response(URL,listing([item()],total=3,pn=2),'123')['ended']
    assert parse_response(URL,listing([item()]),'456') is None
    assert parse_response(URL,listing([dict(item(),mid=456)]),'123')['rows']==[]
    assert parse_response(URL.replace('api.bilibili.com','evil.example'),listing([item()]),'123') is None
    assert normalize(dict(item(),play='1.2万'))['metrics']['views'] is None
    assert normalize(dict(item(),bvid='av123')) is None
    assert parse_response(URL,'{"code":-352}','123')['error']


def test_detail_requires_correct_owner():
    payload={'code':0,'data':dict(item(),owner={'mid':123},stat={'view':200,'like':18,'favorite':9,'share':3,'reply':6})}
    raw=json.dumps(payload)
    row=parse_response('https://api.bilibili.com/x/web-interface/view?bvid='+BV,raw,'123')['rows'][0]
    assert row['metrics']=={'views':200,'likes':18,'favorites':9,'shares':3,'comments':6,'coins':None,'danmaku':99}
    assert parse_response('https://api.bilibili.com/x/web-interface/view?bvid='+BV,raw,'456') is None


def test_repeat_import_preserves_labels_and_known_metrics(tmp_path):
    db=tmp_path/'d.db';init_hub(db);row=normalize(item())
    assert persist(db,'123',row)
    current=latest_posts(db)[0];pid=current['id']
    annotate(db,pid,'COS / 动漫','剧情','角色A',30)
    assert not persist(db,'123',row)
    assert len(snapshots(db,pid))==1
    assert persist(db,'123',normalize(item(views=250)))
    assert len(latest_posts(db))==1
    current=latest_posts(db)[0]
    assert current['views']==250 and current['category']=='剧情' and current['duration_seconds']==30
    persist(db,'456',normalize(item()))
    assert len(latest_posts(db))==2


def test_job_lock_released_after_error(tmp_path):
    assert not job_running(tmp_path)
    with pytest.raises(ValueError):
        with job_lock(tmp_path):
            assert job_running(tmp_path)
            raise ValueError('test')
    assert not job_running(tmp_path)


def test_runner_two_pages_to_database_without_real_browser(tmp_path,monkeypatch):
    class Page:
        url='https://space.bilibili.com/123/upload/video'
        advanced=False
        sent=False
        def goto(self,*args,**kwargs):ctx.handler(response(listing([item()],total=3)))
        def wait_for_timeout(self,ms):
            if self.advanced and not self.sent:
                self.sent=True;ctx.handler(response(listing([item(OTHER)],total=2,pn=2)))
        def evaluate(self,code):
            if 'rows=new Map' in code:return []
            self.advanced=True;return True
        def locator(self,*args):return SimpleNamespace(all=lambda:[])
    page=Page()
    class Context:
        pages=[page]
        def on(self,event,handler):self.handler=handler
        def route(self,*args):pass
        def add_init_script(self,*args):pass
        def close(self):self.pages=[]
    ctx=Context()
    def response(raw):return SimpleNamespace(url=URL,text=lambda:raw,request=SimpleNamespace(resource_type='xhr'))
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *args,**kwargs:ctx))
        def __exit__(self,*args):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    db=tmp_path/'d.db'
    assert run(db,tmp_path,'123')==0
    assert len(latest_posts(db))==2
    status=json.loads((tmp_path/'local'/'bilibili_sync_status.json').read_text())
    assert status['state']=='partial' and status['count']==2 and status['with_views']==2
    assert status['radar_ready']==0  # a complete listing is not complete metric collection
    assert not job_running(tmp_path)


def test_import_button_validates_then_launches_only_on_click(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    import creatorlab.bilibili_ui as ui
    db=tmp_path/'d.db';init_hub(db);calls=[]
    monkeypatch.setattr(ui.subprocess,'Popen',lambda args,**kwargs:calls.append((args,kwargs)))
    app=AppTest.from_string('from creatorlab.bilibili_ui import import_panel\nimport_panel('+repr(str(db))+','+repr(str(tmp_path))+')').run()
    assert not app.exception and calls==[]
    app.text_input(key='bili_import_uid').set_value('not-a-uid')
    app.button(key='bili_start').click().run()
    assert not app.exception and calls==[] and len(app.error)>0
    app.text_input(key='bili_import_uid').set_value('https://space.bilibili.com/123')
    app.button(key='bili_start').click().run()
    assert not app.exception and len(calls)==1
    args,kwargs=calls[0]
    assert args[args.index('--uid')+1]=='123'
    assert args[args.index('--details')+1]=='10'
    assert not kwargs.get('shell')
