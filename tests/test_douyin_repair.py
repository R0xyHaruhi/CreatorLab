import json
import sys
from types import SimpleNamespace
from urllib.parse import quote
from streamlit.testing.v1 import AppTest
from creatorlab.sync_browser import normalize_item,parse_work_list,start
from creatorlab.hub import init_hub,auto_sync_douyin,latest_posts,add_account,upsert_post
from creatorlab.bridge import save_batch,list_batch
from creatorlab.douyin_data import parse_detail,collection_state

VID='7412345678901234567'


def test_favorites_and_statistics_survive_full_storage_path(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    row=normalize_item({'aweme_id':VID,'desc':'真实作品','create_time':1720000000,'statistics':{'play_count':1000,'digg_count':60,'comment_count':6,'collect_count':20,'share_count':3},'metrics':{'completion_rate':'32%'}})
    save_batch(db,{'source':'network','rows':[row]});auto_sync_douyin(db)
    assert list_batch(db)[0]['favorites']==20
    post=latest_posts(db)[0]
    assert post['favorites']==20 and post['comments']==6 and post['completion_rate']==.32
    save_batch(db,{'rows':[{'video_id':VID,'title':'真实作品','likes':80}]});auto_sync_douyin(db)
    post=latest_posts(db)[0]
    assert post['favorites']==20 and post['published_at']==row['published_at']


def test_detail_is_bound_to_owned_video_and_never_guesses_retention():
    raw=json.dumps({'data':{'aweme_detail':{'aweme_id':VID,'desc':'作品','statistics':{'digg_count':5,'collect_count':2}},'recommend':{'aweme_id':'9999999999999999999','statistics':{'digg_count':999}}}})
    rows=parse_detail(raw,{VID})
    assert len(rows)==1 and rows[0]['favorites']==2 and rows[0]['completion_rate'] is None
    assert parse_detail(raw,{'8888888888888888888'})==[]
    assert normalize_item({'id':VID,'metrics':{'completion_rate':32}})['completion_rate'] is None


def test_203_of_292_cannot_be_reported_completed_or_collecting_forever():
    assert collection_state(203,292,False,0,10)=='partial'
    assert collection_state(203,292,True,8,100)=='stalled'
    assert collection_state(292,292,None,8,100)=='completed'
    assert parse_work_list('{"data":{"aweme_list":[],"has_more":0,"total":0}}')['total']==0


def test_dead_process_status_is_reconciled(tmp_path):
    from creatorlab.douyin_ui import read_status
    local=tmp_path/'local';local.mkdir()
    (local/'sync_status.json').write_text(json.dumps({'state':'collecting','count':203,'total':292,'updated_at':'2026-01-01T00:00:00+00:00'}))
    assert read_status(tmp_path)['state']=='interrupted'


def test_douyin_unlock_screen_has_inline_action_and_actual_values(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    for i in range(3):upsert_post(db,aid,'作品'+str(i),str(7412345678901234500+i),'2026-01-01T00:00:00Z',metrics={'views':1000,'likes':60},observed_at='2026-02-01T00:00:00Z')
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nfrom creatorlab.hub import latest_posts\nhero(latest_posts('+repr(str(db))+'))').run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.button(key='dy_hero_start').label=='补齐互动数据'
    assert len(app.metric)==6
    traces=[t for c in app.get('plotly_chart') for t in json.loads(c.proto.spec).get('data',[])]
    assert any(t['type']=='bar' for t in traces) and any(t['type']=='heatmap' for t in traces)
    assert not any(t['type']=='scatterpolar' for t in traces)


def test_browser_pipeline_exits_after_partial_list_and_enriches_owned_details(tmp_path,monkeypatch):
    import creatorlab.sync_browser as sync
    items=[{'id':str(7412345678901234500+i),'description':'作品'+str(i),'create_time':1720000000,'metrics':{'play_count':1000,'like_count':60,'completion_rate':.4}} for i in range(3)]
    raw=json.dumps({'data':{'items':items,'total':4,'has_more':0}})
    class Page:
        url='https://creator.douyin.com/'
        def goto(self,url,**kwargs):
            self.url=url
            if url==sync.CENTER:ctx.handler(SimpleNamespace(url=sync.CENTER+'web/api/media/aweme/work_list/',status=200,text=lambda:raw))
        def evaluate(self,*args):return [] if 'video-card-content' in str(args[0]) else 'stuck'
        def reload(self,**kwargs):pass
        def wait_for_timeout(self,ms):pass
        def content(self):
            vid=self.url.rstrip('/').split('/')[-1]
            value={'aweme_detail':{'aweme_id':vid,'desc':'详情作品','statistics':{'digg_count':60,'comment_count':10,'collect_count':20,'share_count':5}}}
            return '<script id="RENDER_DATA" type="application/json">'+quote(json.dumps(value))+'</script>'
        def locator(self,*a):return SimpleNamespace(count=lambda:0)
    class Context:
        pages=[Page()]
        def on(self,event,handler):self.handler=handler
        def route(self,*a):pass
        def add_init_script(self,*a):pass
        def new_page(self):return Page()
        def close(self):self.pages=[]
    ctx=Context()
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**kw:ctx))
        def __exit__(self,*a):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    ticks=[0]
    def clock():ticks[0]+=1;return ticks[0]
    monkeypatch.setattr(sync.time,'monotonic',clock)
    db=tmp_path/'d.db'
    init_hub(db);aid=add_account(db,'douyin','my-account')
    assert start(db,tmp_path,account_id=aid)==0
    assert latest_posts(db)==[]
    from creatorlab.douyin_capture import pending_captures,commit_capture
    pending=pending_captures(db)
    assert len(pending)==1 and pending[0]['account_id']==aid
    assert commit_capture(db,pending[0]['id'],aid)==3
    rows=latest_posts(db)
    assert len(rows)==3 and all(r['favorites']==20 and r['shares']==5 and r['completion_rate']==.4 for r in rows)
    assert all(r['_ratio_allowed']['favorites'] for r in rows)
    status=json.loads((tmp_path/'local'/'sync_status.json').read_text(encoding='utf-8'))
    assert status['state']=='review' and status['count']==3 and status['total']==4 and status['details']==3
