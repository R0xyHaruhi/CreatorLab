from datetime import datetime,timezone,date
import json
import pytest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts,connect
from creatorlab.measurements import window_metrics,window_rows,record
from creatorlab.review_loop import link_experiment,evaluate_experiment,starter_observations,freeze,baselines
from creatorlab.growth import save_experiment,experiments
from creatorlab.content_analysis import frame
from creatorlab.discovery import parse_search,segment
from creatorlab.acceptance import reconcile


def setup(db):
    init_hub(db);return add_account(db,'bilibili','123')


def test_partial_metrics_never_acquire_fake_window_timestamps(tmp_path):
    db=tmp_path/'d.db';aid=setup(db)
    pid=upsert_post(db,aid,'标题','BV1xx411c7mD','2026-01-01T00:00:00Z',metrics={'views':100,'likes':10},observed_at='2026-01-02T00:00:00Z')
    upsert_post(db,aid,'标题','BV1xx411c7mD',metrics={'likes':50},observed_at='2026-01-08T00:00:00Z')
    row=latest_posts(db)[0]
    assert row['views']==100
    old=window_metrics(db,row,'24小时');assert old['metrics']['views']==100
    week=window_metrics(db,row,'7天');assert 'views' not in week['metrics']
    assert week['status']=='窗口已错过，不能回推'
    record(db,pid,{'views':500},'2026-01-08T03:00:00Z','manual')
    selected,_=window_rows(db,[row],'7天')
    assert len(selected)==1 and frame(selected).iloc[0]['like_ratio'] is None


def test_csv_without_observation_date_cannot_manufacture_history(tmp_path):
    db=tmp_path/'d.db';aid=setup(db)
    from creatorlab.hub import import_csv
    import_csv(db,aid,'title,external_id,published_at,views\n旧数据,x,2026-01-01T00:00:00Z,999\n')
    assert not window_metrics(db,latest_posts(db)[0],'7天')['metrics']
    with pytest.raises(ValueError):upsert_post(db,aid,'bad','bad',metrics={'views':100},observed_at='2099-01-01T00:00:00Z')
    assert len(latest_posts(db))==1


def test_experiment_links_real_windows_and_freezes_baseline(tmp_path):
    db=tmp_path/'d.db';aid=setup(db)
    a=upsert_post(db,aid,'参照','a','2026-01-01T00:00:00Z',metrics={'views':100},observed_at='2026-01-08T01:00:00Z')
    b=upsert_post(db,aid,'改动','b','2026-01-02T00:00:00Z',metrics={'views':150},observed_at='2026-01-09T00:00:00Z')
    eid=save_experiment(db,aid,'试开头','先展示结果','views')
    link_experiment(db,eid,aid,[a],[b],'7天');task=experiments(db,aid)[0]
    result=evaluate_experiment(db,task,latest_posts(db))
    assert result['baseline']==100 and result['result']==150 and result['exploratory']
    record(db,a,{'views':200},'2026-01-08T00:00:00Z','manual')
    result=evaluate_experiment(db,task,latest_posts(db))
    assert result['baseline']==100
    assert next(e['value'] for e in result['evidence'] if e['post_id']==a)==100
    other=add_account(db,'bilibili','456');wrong=upsert_post(db,other,'别人','x',metrics={'views':1})
    with pytest.raises(ValueError):link_experiment(db,eid,aid,[a],[wrong],'7天')


def test_frozen_growth_reference_does_not_change_with_later_sync(tmp_path):
    db=tmp_path/'d.db';aid=setup(db)
    upsert_post(db,aid,'初始','x','2026-01-01T00:00:00Z',metrics={'views':100})
    df=frame(latest_posts(db));df['analysis_window']='当前累计'
    freeze(db,aid,'第一组','当前累计',df)
    upsert_post(db,aid,'初始','x',metrics={'views':1000})
    assert json.loads(baselines(db,aid)[0]['rows_json'])[0]['views']==100
    assert len(starter_observations(latest_posts(db)))==3


def test_live_search_candidates_require_primary_domain_and_keyword():
    url='https://api.bilibili.com/x/web-interface/search/type?keyword=游戏攻略&search_type=bili_user'
    raw=json.dumps({'code':0,'data':{'result':[{'mid':999,'uname':'真实响应示例','fans':12345}]}})
    out=parse_search(url,raw,'游戏攻略');assert out[0]['followers']==12345
    assert parse_search(url,raw,'其他词')==[]
    assert parse_search(url.replace('api.bilibili.com','evil.example'),raw,'游戏攻略')==[]
    assert segment(200,100)=='同量级' and segment(500,100)=='稍领先'
    assert segment(2000,100)=='较大账号参考' and segment(None,100)=='规模未知'


def test_source_reconciliation_is_not_overall_online_acceptance(tmp_path):
    db=tmp_path/'d.db';aid=setup(db)
    assert reconcile(db,aid,'followers',0,0,'源页人工核对')['passed']
    assert not reconcile(db,aid,'followers',123,None,'未采集')['passed']
    with pytest.raises(ValueError):reconcile(db,aid,'followers','nan',0,'bad')


def test_importing_old_measurement_does_not_roll_back_current_value(tmp_path):
    db=tmp_path/'d.db';aid=setup(db)
    upsert_post(db,aid,'作品','x','2026-01-01T00:00:00Z',metrics={'views':1000},observed_at='2026-02-01T00:00:00Z')
    upsert_post(db,aid,'作品','x',metrics={'views':100},observed_at='2026-01-02T00:00:00Z')
    row=latest_posts(db)[0]
    assert row['views']==1000 and row['metric_recorded_at'].startswith('2026-02-01')
    assert window_metrics(db,row,'24小时')['metrics']['views']==100


def test_retry_queue_is_targeted_and_estimate_has_warmup(tmp_path):
    from creatorlab.sync_jobs import retry_rows,record_attempt,estimate
    from creatorlab.covers import save_cover
    import io
    from PIL import Image
    db=tmp_path/'d.db';aid=setup(db)
    upsert_post(db,aid,'完整','BV1xx411c7mD','2026-01-01T00:00:00Z',metrics={'views':100,'likes':1,'comments':0,'favorites':0,'shares':0,'coins':0,'danmaku':0})
    im=io.BytesIO();Image.new('RGB',(100,100),'blue').save(im,format='PNG');save_cover(db,'bilibili','BV1xx411c7mD',im.getvalue(),'test')
    assert retry_rows(db,'123')==[]
    record_attempt(db,'123','BV1xx411c7mD',['likes'],'本轮未取得新值')
    assert len(retry_rows(db,'123'))==1
    record_attempt(db,'123','BV1xx411c7mD',[],'')
    assert retry_rows(db,'123')==[]
    assert estimate(10,1,10) is None and estimate(20,2,10)==80


def test_csv_historical_timestamp_validation_is_preflight(tmp_path):
    from creatorlab.hub import import_csv
    db=tmp_path/'d.db';aid=setup(db)
    data='title,external_id,views,observed_at\n有效,a,100,2026-01-01T00:00:00Z\n未来,b,200,2099-01-01T00:00:00Z\n'
    with pytest.raises(ValueError):import_csv(db,aid,data)
    assert latest_posts(db)==[]
