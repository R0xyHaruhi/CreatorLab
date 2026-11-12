"""Regressions for v1.9 screenshots: DOM-only import, missing dates and empty radar."""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.bilibili_import import run,ingest_row,normalize
from creatorlab.bilibili_page import parse_page_html,account_values,space_route
from creatorlab.discovery import parse_search,search_url

BV='BV1xx411c7mD'


def video(bvid=BV):
    return {'bvid':bvid,'title':'作品','owner':{'mid':123},'pubdate':1700000000,
      'pic':'https://i0.hdslb.com/bfs/archive/one.jpg','duration':90,
      'stat':{'view':1000,'like':100,'reply':10,'favorite':30,'share':5,'coin':40,'danmaku':8}}


def test_ssr_requires_both_video_and_author_without_executing_scripts():
    state={'newLayout':{'archive':video()},'recommend':[dict(video(),owner={'mid':456})]}
    html='<script>window.__INITIAL_STATE__ = '+json.dumps(state)+';doNotExecute()</script>'
    assert len(parse_page_html(html,BV,'123'))==1
    assert parse_page_html(html,BV,'999')==[]
    assert parse_page_html('<script>window.__INITIAL_STATE__=evil()</script>',BV,'123')==[]
    assert space_route('https://space.bilibili.com/123/video','123')
    assert not space_route('https://space.bilibili.com/456/video','123')


def test_embedded_account_values_do_not_take_other_authors_or_rounded_counts():
    state={'Card':{'card':{'mid':123,'fans':789,'friend':6},'archive_count':9,'like_num':456},
           'wrong':{'mid':456,'fans':99999}}
    assert account_values(state,'123')=={'followers':789,'following':6,'video_count':9,'total_likes':456}
    assert account_values({'mid':123,'fans':'1.2万'},'123')=={}


def test_dom_fallback_can_reach_full_detail_data_without_any_api(tmp_path,monkeypatch):
    import creatorlab.bilibili_import as importer
    class Page:
        url='https://space.bilibili.com/123/video'
        def goto(self,url,**kwargs):self.url=url
        def wait_for_timeout(self,ms):pass
        def title(self):return '作品'
        def content(self):return '<script>window.__INITIAL_STATE__='+json.dumps({'layout':video(),'Card':{'card':{'mid':123,'fans':1234}}})+';</script>'
        def evaluate(self,code,arg=None):
            if 'rows=new Map' in code:return [{'bvid':BV,'title':'作品'}]
            if 'next.click()' in code:return False
            return None
        def locator(self,*args):return SimpleNamespace(all=lambda:[])
        def close(self):pass
    space=Page()
    class Context:
        pages=[space]
        def on(self,*args):pass
        def route(self,*args):pass
        def add_init_script(self,*args):pass
        def new_page(self):return Page()
        def close(self):self.pages=[]
    context=Context()
    class Manager:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**kw:context))
        def __exit__(self,*a):pass
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=Manager))
    ticks=[0]
    def clock():ticks[0]+=1;return ticks[0]
    monkeypatch.setattr(importer.time,'monotonic',clock)
    def fetch(ctx,db,platform,bvid,url):
        from creatorlab.covers import save_cover
        data=io.BytesIO();Image.new('RGB',(80,80),'blue').save(data,format='PNG')
        save_cover(db,platform,bvid,data.getvalue(),'browser_loaded_platform_cover',url);return True
    monkeypatch.setattr('creatorlab.covers.fetch_browser_cover',fetch)
    db=tmp_path/'data.db'
    assert run(db,tmp_path,'123',details=10)==0
    row=latest_posts(db)[0]
    assert row['views']==1000 and row['likes']==100 and row['coins']==40 and row['comments']==10
    assert row['published_at'] and row['cover_url']
    from creatorlab.covers import cached_cover
    from creatorlab.bilibili_account import latest_fields
    assert cached_cover(db,'bilibili',BV)
    assert latest_fields(db,row['account_id'])['followers']['value']==1234
    status=json.loads((tmp_path/'local'/'bilibili_sync_status.json').read_text())
    assert status['radar_ready']==1 and status['with_cover']==1


def test_partial_repair_does_not_retimestamp_old_views(tmp_path):
    from creatorlab.measurements import latest_observed
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    upsert_post(db,aid,'作品',BV,metrics={'views':500},observed_at='2026-01-01T00:00:00Z')
    rows={BV:dict(normalize(video()),metrics={'views':500})};seen={}
    partial=normalize({**video(),'stat':{'like':40}})
    ingest_row(db,'123',partial,rows,seen)
    row=latest_posts(db)[0]
    assert row['views']==500 and row['likes']==40
    assert row['field_observed_at']['views'].startswith('2026-01-01')
    assert seen[BV]=={'likes'}


def test_discovery_uses_video_evidence_instead_of_username_matches():
    raw=json.dumps({'code':0,'data':{'result':[{'mid':1,'uname':'日常Vlog','fans':5},
        {'mid':2,'author':'做内容的人','bvid':BV,'title':'<em class="keyword">校园</em>生活记录'},
        {'mid':2,'author':'做内容的人','bvid':'BV1xx411c7mE','title':'我的大学周末'}]}})
    url='https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=校园'
    found=parse_search(url,raw,'校园',videos_only=True)
    assert len(found)==1 and found[0]['name']=='做内容的人'
    assert found[0]['titles']==['校园生活记录','我的大学周末']
    assert '/video?' in search_url('bilibili','校园') and '/upuser' not in search_url('bilibili','校园')


def test_real_partition_and_tags_inform_classification_without_overriding_user(tmp_path):
    from creatorlab.bilibili_import import persist,parse_response
    from creatorlab.genres import set_genre
    from creatorlab.discovery import query_for
    db=tmp_path/'d.db';init_hub(db)
    raw=json.dumps({'code':0,'data':{'View':{**video(),'tname':'鬼畜调教','desc':'真实简介'},'Tags':[{'tag_name':'音MAD素材'}]}})
    result=parse_response('https://api.bilibili.com/x/web-interface/wbi/view/detail?bvid='+BV,raw,'123')
    persist(db,'123',result['rows'][0])
    row=latest_posts(db)[0]
    assert row['bili_partition']=='鬼畜调教' and row['bili_tags']==['音MAD素材']
    assert row['genre']['major']=='鬼畜区' and row['genre']['origin']=='platform_metadata'
    assert query_for('鬼畜调教',[row])=='音MAD素材 鬼畜调教'
    set_genre(db,row['id'],'生活区','校园生活')
    persist(db,'123',result['rows'][0])
    assert latest_posts(db)[0]['genre']['minor']=='校园生活'


def run_radar(db):
    return AppTest.from_string('from creatorlab.hub import latest_posts\nfrom creatorlab.content_analysis import frame\nfrom creatorlab.growth_ui import radar_panel\nrows=latest_posts('+repr(str(db))+')\nradar_panel(frame(rows),rows)').run()


def polar_traces(app):
    return [trace for chart in app.get('plotly_chart') for trace in json.loads(chart.proto.spec).get('data',[]) if trace.get('type')=='scatterpolar']


def test_views_only_records_get_repair_action_instead_of_empty_radar(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','62473140')
    for i in range(8):upsert_post(db,aid,'旧作品'+str(i),str(i),metrics={'views':100+i})
    app=run_radar(db)
    assert not app.exception,[e.message for e in app.exception]
    assert polar_traces(app)==[]
    assert app.button(key='radar_repair')
    assert any('不足' in x.value for x in app.warning)


def test_complete_observations_make_a_real_six_axis_polygon(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    for i in range(5):
        upsert_post(db,aid,'作品'+str(i),str(i),'2026-01-01T00:00:00Z',metrics={'views':100+i*100,'likes':5+i,'comments':i,'favorites':i+2,'shares':i,'coins':i+3},observed_at='2026-02-01T00:00:00Z')
    app=run_radar(db)
    assert not app.exception,[e.message for e in app.exception]
    actual=[t for t in polar_traces(app) if t.get('name')=='这条作品']
    assert len(actual)==1 and actual[0]['fill']=='toself'
    assert len(actual[0]['r'])==7 and all(v is not None for v in actual[0]['r'])
