"""User-visible 2.6 workflows, plus source-grounded collection regressions."""
import io
import json
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts,connect
from creatorlab.reporting import positions,metric_value,filter_library,comparison_table,safe_csv
from creatorlab.battlecard import history_profiles


def seed(db):
    init_hub(db)
    for platform in ('bilibili','douyin'):
        aid=add_account(db,platform,'123',platform)
        for i in range(5):
            upsert_post(db,aid,platform+'真实作品'+str(i),platform+str(i),
                '2026-01-01T00:00:00Z' if i%2 else '2026-10-01T00:00:00Z',
                metrics=dict(views=1000+i*100,likes=10+i,comments=i,favorites=i,shares=i,coins=i,danmaku=i,completion_rate=.3),
                observed_at='2026-11-01T00:00:00Z')


def test_age_is_not_forced_and_counts_do_not_promote_two_views_one_like():
    rows=[dict(id=i,account_id=1,platform='bilibili',media_format='video',views=v,likes=l,
              comments=l,favorites=l,shares=l,coins=l,published_at=d) for i,(v,l,d) in enumerate([
                  (2,1,None),(10000,200,'2026-01-01'),(20000,300,'2026-10-01'),(30000,400,'2026-11-01')])]
    values=positions(rows,rows[0]);assert values[0]['n']==3 and values[0]['percent']==0
    models=history_profiles(rows)
    assert models[0]['ready'] and all(s['score']==0 for s in models[0]['scores'])
    assert models[0].get('overall') is None
    assert positions(rows,rows[0],(date(2026,10,1),date(2026,11,1)))[0]['n']==2
    assert metric_value(rows[0],'like_ratio')==.5
    assert metric_value(dict(rows[0],_ratio_allowed={'likes':False}),'like_ratio') is None
    assert metric_value(dict(rows[0],views=0),'like_ratio') is None


def test_ties_missing_private_accounts_and_fixed_windows_stay_separate():
    base=dict(account_id=1,platform='bilibili',media_format='video',views=100,likes=0)
    rows=[dict(base,id=i) for i in range(4)]
    rows += [dict(base,id=4,visibility='private'),dict(base,id=5,account_id=2),dict(base,id=6,platform='douyin'),dict(base,id=7,analysis_window='7天')]
    item=positions(rows,rows[0])[0];assert item['n']==3 and item['percent']==0
    models=history_profiles(rows);assert models[0]['scores'][0]['n']==3 and models[0]['scores'][0]['score']==0
    assert next(v for v in positions(rows,rows[0]) if v['metric']=='comments')['value'] is None
    assert 4 not in models
    with pytest.raises(ValueError):comparison_table([rows[0],rows[6]])


def test_filters_chronological_dates_missing_last_and_export_safety():
    rows=[dict(id=1,account_id=1,title='=危险',published_at='2026-01-01T00:00:00+08:00',views=0),
          dict(id=2,account_id=1,title='正常',published_at='2025-12-31T20:00:00Z',views=10),
          dict(id=3,account_id=2,title='未知',published_at=None,views=None)]
    assert [r['id'] for r in filter_library(rows)]==[2,1,3]
    assert len(filter_library(rows,account_id=1))==2
    assert filter_library(rows,search='不存在')==[]
    assert b"'=\xe5" in safe_csv(rows)


def test_silent_cover_never_opens_a_tab_and_validates_every_redirect(tmp_path):
    from creatorlab.covers import fetch_browser_cover,cached_cover
    db=tmp_path/'d.db';init_hub(db)
    raw=io.BytesIO();Image.new('RGB',(80,80),'blue').save(raw,format='PNG')
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return SimpleNamespace(status=302 if len(calls)==1 else 200,
          headers={'location':'https://i1.hdslb.com/two.png'} if len(calls)==1 else {'content-type':'image/png'},
          body=lambda:raw.getvalue(),dispose=lambda:None)
    context=SimpleNamespace(request=SimpleNamespace(get=get),new_page=lambda:pytest.fail('must not open tabs'))
    assert fetch_browser_cover(context,db,'bilibili','one','https://i0.hdslb.com/one.png')
    assert len(calls)==2 and cached_cover(db,'bilibili','one')
    context.request.get=lambda *a,**k:SimpleNamespace(status=302,headers={'location':'http://127.0.0.1/private'},dispose=lambda:None)
    assert not fetch_browser_cover(context,db,'bilibili','two','https://i0.hdslb.com/one.png')
    assert not cached_cover(db,'bilibili','two')


def test_task_interruption_and_database_scope(tmp_path,monkeypatch):
    from creatorlab.task_ui import task_status
    from creatorlab.sync_browser import status_write
    monkeypatch.setattr('creatorlab.task_ui.job_running',lambda *args:False)
    target=tmp_path/'local'/'bilibili_sync_status.json'
    status_write(target,state='details',count=9,database=str((tmp_path/'one.db').resolve()))
    assert task_status(tmp_path,'bilibili',tmp_path/'one.db')['state']=='interrupted'
    assert task_status(tmp_path,'bilibili',tmp_path/'two.db')=={}
    assert task_status(tmp_path,'douyin')=={}


def test_overall_navigation_batch_compare_filters_reset_and_platform_switch(tmp_path,monkeypatch):
    db=tmp_path/'d.db';seed(db);monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=45).run()
    assert not app.exception,[e.message for e in app.exception]
    assert not app.tabs
    app.switch_page('app_pages/library.py').run()
    own=[r for r in latest_posts(db) if r['platform']=='douyin']
    ids=[r['id'] for r in own[:3]]
    app.multiselect(key='library_batch').set_value(ids).run()
    app.button(key='library_compare').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.selectbox(key='quick_c__douyin').value==ids[2]
    assert app.get('button_group')[0].value=='作品对比'
    app.switch_page('app_pages/library.py').run()
    app.button(key='library_open_'+str(ids[0])).click().run()
    assert app.selectbox(key='report_work__douyin').value==ids[0]
    assert app.get('button_group')[0].value=='详细数据'
    assert not app.exception,[e.message for e in app.exception]
    app.switch_page('app_pages/library.py').run()
    app.text_input(key='library_search').set_value('不存在').run()
    assert not any(m.key=='library_batch' for m in app.multiselect)
    app.button(key='library_reset').click().run()
    assert app.text_input(key='library_search').value==''
    app.session_state['work_view']='详细数据'
    app.switch_page('app_pages/works.py').run()
    assert not app.checkbox(key='report_date_filter').value
    app.radio(key='platform_space').set_value('B站空间').run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.get('button_group')[0].value=='直观看表现'
    app.get('button_group')[0].set_value('详细数据').run()
    assert all('bilibili' in s for s in app.selectbox(key='report_work__bilibili').options)
    app.get('button_group')[0].set_value('作品对比').run()
    assert app.selectbox(key='quick_c__bilibili').value is None
    assert app.selectbox(key='quick_metric__bilibili').value=='Overall · 全指标'
    with connect(db) as con:assert con.execute('select count(*) from hub_posts').fetchone()[0]==10


def test_classification_confirmation_survives_rerun(tmp_path):
    db=tmp_path/'d.db';seed(db)
    code='from creatorlab.hub import latest_posts\nfrom creatorlab.classification_ui import editor\neditor('+repr(str(db))+', [r for r in latest_posts('+repr(str(db))+') if r["platform"]=="bilibili"], "testgenre")'
    app=AppTest.from_string(code,default_timeout=20).run()
    app.selectbox(key='testgenre_major').select('动画').run() if '动画' in app.selectbox(key='testgenre_major').options else app.selectbox(key='testgenre_major').select_index(1).run()
    app.multiselect(key='testgenre_ids').set_value([next(r['id'] for r in latest_posts(db) if r['platform']=='bilibili')])
    app.button(key='FormSubmitter:testgenre_canonical-确认赛道').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert any('已保存 1 条作品' in e.value for e in app.success)
