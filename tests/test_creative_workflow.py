import json
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts,connect
from creatorlab.genres import set_genre,genre_rows
from creatorlab.creative_brief import build_brief,save_plan,plan_experiment,apply_model_draft,KINDS
from creatorlab.learning_workflow import save_review,lessons_for
from creatorlab.review_loop import link_experiment,evaluate_experiment
from creatorlab.growth import experiments
from creatorlab.workflow_store import get,documents


def seed(db):
    init_hub(db);aid=add_account(db,'bilibili','123','创作者')
    a=upsert_post(db,aid,'角色成片的关键一步','before','2026-01-01T00:00:00Z',
        metrics=dict(views=1000,likes=30,comments=2,favorites=5),observed_at='2026-01-08T00:00:00Z')
    b=upsert_post(db,aid,'角色成片的关键一步：先看结果','after','2026-01-02T00:00:00Z',
        metrics=dict(views=1500,likes=60,comments=4,favorites=8),observed_at='2026-01-09T00:00:00Z')
    for pid in (a,b):set_genre(db,pid,'动漫区','COS与角色扮演')
    return aid,a,b


def labelled(db):return genre_rows(db,latest_posts(db))


def test_plan_experiment_review_feedback_is_persistent_and_account_scoped(tmp_path):
    db=tmp_path/'d.db';aid,a,b=seed(db);rows=labelled(db);target=next(r for r in rows if r['id']==b)
    brief=build_brief(rows,target,'views')
    assert tuple(c['kind'] for c in brief['cards'])==KINDS
    assert brief['observations']['target_value']==1500 and brief['observations']['personal_median']==1000
    plan=save_plan(db,brief);eid=plan_experiment(db,aid,'bilibili',plan,'标题')
    assert plan_experiment(db,aid,'bilibili',plan,'标题')==eid
    assert len(experiments(db,aid))==1
    link_experiment(db,eid,aid,[a],[b],'7天')
    result=evaluate_experiment(db,experiments(db,aid)[0],latest_posts(db))
    assert result['baseline']==1000 and result['result']==1500 and result['exploratory']
    save_review(db,aid,'bilibili',eid,'已复盘','继续验证','7天播放','结果提前','只有各1条，未控制热点',
                '本轮新做法播放较高，不能证明标题造成','保留标题，只重复同题材验证',True,'标题')
    lessons=lessons_for(db,aid,'bilibili',target,'views')
    assert len(lessons)==1 and lessons[0]['result']['n_baseline']==1
    reviewed_detail=get(db,'experiment_detail',aid,'bilibili',eid)
    assert plan_experiment(db,aid,'bilibili',plan,'标题')==eid
    assert get(db,'experiment_detail',aid,'bilibili',eid)==reviewed_detail
    following=build_brief(rows,target,'views',lessons=lessons)
    card=next(c for c in following['cards'] if c['kind']=='标题')
    assert card['prior_experiment_id']==eid and '只重复同题材' in card['change']
    assert 'api_key' not in json.dumps(documents(db,'plan',aid,'bilibili')).lower()
    other=add_account(db,'bilibili','456')
    with pytest.raises(ValueError):plan_experiment(db,other,'bilibili',plan,'标题')
    assert documents(db,'lesson',other,'bilibili')==[]
    # Editing the links invalidates old feedback, even with unchanged track and format.
    link_experiment(db,eid,aid,[b],[a],'7天')
    assert lessons_for(db,aid,'bilibili',target,'views')==[]


def test_cross_track_and_format_are_rejected_without_fabricating_results(tmp_path):
    db=tmp_path/'d.db';aid,a,b=seed(db)
    plan=save_plan(db,build_brief(labelled(db),labelled(db)[0],'views'))
    eid=plan_experiment(db,aid,'bilibili',plan,'内容结构')
    set_genre(db,b,'游戏区','攻略教学')
    with pytest.raises(ValueError,match='细分赛道'):link_experiment(db,eid,aid,[a],[b],'7天')
    set_genre(db,b,'动漫区','COS与角色扮演')
    link_experiment(db,eid,aid,[a],[b],'7天')
    set_genre(db,b,'游戏区','攻略教学')
    assert evaluate_experiment(db,experiments(db,aid)[0],latest_posts(db))['status']=='参照范围待核对'
    with pytest.raises(ValueError,match='固定窗口'):save_review(db,aid,'bilibili',eid,'已复盘','',
        '播放','开头','未知','暂不判断','再做一条',True,'内容结构')


def test_model_unknown_sources_and_guarantees_are_not_adopted(tmp_path):
    db=tmp_path/'d.db';seed(db);rows=labelled(db);brief=build_brief(rows,rows[0],'views')
    text=json.dumps({'cards':brief['cards']},ensure_ascii=False)
    adopted=apply_model_draft(brief,text)
    assert adopted['observations']==brief['observations']
    bad=json.loads(text);bad['cards'][0]['evidence_ids']=['R:invented']
    with pytest.raises(ValueError,match='证据'):apply_model_draft(brief,json.dumps(bad))
    bad=json.loads(text);bad['cards'][0]['hypothesis']='保证播放增长'
    with pytest.raises(ValueError):apply_model_draft(brief,json.dumps(bad))
    foreign=dict(platform='douyin',major='动漫区',minor='COS与角色扮演')
    dy=dict(rows[0],platform='douyin')
    with pytest.raises(ValueError):build_brief([dy],dy,'views',foreign,[])


def test_planning_ui_saves_and_reopens_plan_then_creates_one_experiment(tmp_path):
    db=tmp_path/'d.db';aid,a,b=seed(db)
    extra=upsert_post(db,aid,'另一赛道的历史作品','other-track','2026-01-01T00:00:00Z',
        metrics=dict(views=500),observed_at='2026-01-08T00:00:00Z')
    set_genre(db,extra,'游戏区','攻略教学')
    code='from creatorlab.hub import latest_posts\nfrom creatorlab.creative_brief_ui import planning_panel\nplanning_panel(latest_posts('+repr(str(db))+'),"views")'
    app=AppTest.from_string(code,default_timeout=30).run()
    assert not app.exception,[e.message for e in app.exception]
    app.selectbox(key='assistant_workflow_target').set_value(b).run()
    assert app.radio(key='assistant_workflow_personal_scope').value=='全部历史有效作品'
    assert app.metric[0].value=='2'
    app.radio(key='assistant_workflow_personal_scope').set_value('同赛道（按已确认分类）').run()
    assert not app.exception and app.metric[0].value=='1'
    assert any(s.label=='给哪些作品确认这个赛道' for s in app.multiselect)
    app.radio(key='assistant_workflow_personal_scope').set_value('全部历史有效作品').run()
    assert app.metric[0].value=='2'
    assert app.selectbox(key='assistant_workflow_provider').value=='仅本地规则'
    app.button(key='assistant_workflow_save').click().run()
    assert not app.exception and len(documents(db,'plan',aid,'bilibili'))==1
    app.button(key='assistant_workflow_to_experiment').click().run()
    assert not app.exception and len(experiments(db,aid))==1
    app.button(key='assistant_workflow_to_experiment').click().run()
    assert len(experiments(db,aid))==1


@pytest.mark.parametrize('provider,host,model',[('deepseek','https://api.deepseek.com/chat/completions','deepseek-flash'),
    ('doubao','https://ark.cn-beijing.volces.com/api/v3/chat/completions','doubao-seed-2-1-lite-260915')])
def test_chinese_providers_use_correct_hosts_and_never_store_keys(monkeypatch,provider,host,model):
    import creatorlab.ai as ai
    requests=[]
    def fake(url,payload,headers,timeout):
        requests.append((url,payload,headers));return {'choices':[{'message':{'content':'一条待验证建议'}}]}
    monkeypatch.setattr(ai,'_post',fake)
    assert ai.generate(provider,'建议',{'sample_n':2},api_key='test-secret')=='一条待验证建议'
    assert requests[0][0]==host and requests[0][1]['model']==model
    assert requests[0][2]['Authorization']=='Bearer test-secret'
    assert 'test-secret' not in json.dumps(requests[0][1])
