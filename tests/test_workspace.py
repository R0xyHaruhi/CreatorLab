import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post
from creatorlab.growth import experiments
from creatorlab.workspace import consume_route,WORK,CREATE

ROOT=Path(__file__).resolve().parents[1]


def seed(db):
    init_hub(db);aid=add_account(db,'bilibili','123','我的账号')
    for i in range(6):
        upsert_post(db,aid,'真实作品'+str(i),'work'+str(i),'2026-01-01T00:00:00Z',
            metrics=dict(views=1000+i*100,likes=10+i,comments=2+i,favorites=2+i,shares=1+i,coins=1+i),observed_at='2026-01-08T00:00:00Z')
    return aid


def test_home_is_focused_and_does_not_load_unselected_features(tmp_path,monkeypatch):
    db=tmp_path/'d.db';seed(db);monkeypatch.setenv('CREATORLAB_DB',str(db))
    monkeypatch.setitem(sys.modules,'creatorlab.weekly_ui',None)
    monkeypatch.setitem(sys.modules,'creatorlab.video_inspection_ui',None)
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    assert not app.exception,[e.message for e in app.exception]
    assert not app.tabs and len(app.get('plotly_chart'))==1
    assert not app.get('file_uploader') and not app.text_area
    assert not any(s.key=='analysis_goal' for s in app.selectbox)
    assert any(e.label=='调整参照与图表口径' and not e.proto.expanded for e in app.expander)
    assert app.button(key='hero_plan_next') and app.get('download_button')
    assert app.get('button_group')[0].key=='work_view'
    assert not any(e.label=='更多分析方式' for e in app.expander)


def test_analysis_navigation_keeps_selected_work_between_chart_and_report(tmp_path,monkeypatch):
    db=tmp_path/'d.db';seed(db);monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    app.selectbox(key='hero_work__bilibili').select_index(2).run()
    chosen=app.selectbox(key='hero_work__bilibili').value
    app.get('button_group')[0].set_value('详细数据').run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.selectbox(key='report_work__bilibili').value==chosen
    app.selectbox(key='report_work__bilibili').select_index(1).run()
    report_chosen=app.selectbox(key='report_work__bilibili').value
    app.get('button_group')[0].set_value('直观看表现').run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.selectbox(key='hero_work__bilibili').value==report_chosen


def test_guided_plan_flows_into_one_review_and_remains_idempotent(tmp_path,monkeypatch):
    db=tmp_path/'d.db';aid=seed(db);monkeypatch.setenv('CREATORLAB_DB',str(db))
    upsert_post(db,aid,'真实作品5','work5',metrics={'likes':1},observed_at='2026-01-08T00:00:00Z')
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    target=app.selectbox(key='hero_work__bilibili').value
    app.button(key='hero_plan_next').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.selectbox(key='assistant_workflow_target__bilibili').value==target
    assert app.selectbox(key='assistant_workflow_focus').value=='内容结构'
    assert app.selectbox(key='assistant_goal').value=='让观众更愿意点赞'
    change=next(w for w in app.text_area if w.label=='下一条具体改什么')
    assert '开头' in change.value
    change.set_value('先给成片，再讲步骤').run()
    headings=[m.value for m in app.markdown if m.value.startswith('#### ')]
    assert '#### 内容结构' in headings and '#### 选题' not in headings
    app.button(key='assistant_workflow_save').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.session_state['create_step']=='记录与复盘'
    eid=experiments(db,aid)[0]['id']
    assert experiments(db,aid)[0]['metric']=='like_ratio'
    assert '先给成片，再讲步骤' in experiments(db,aid)[0]['hypothesis']
    assert app.multiselect(key=f'exp_before_{eid}').value==[target]
    assert app.selectbox(key='review_task__bilibili').value==eid
    app.session_state['create_step']='准备创作';app.run()
    app.button(key='assistant_workflow_save').click().run()
    assert not app.exception and len(experiments(db,aid))==1


def test_demo_details_keep_selected_work_and_do_not_create_records(tmp_path,monkeypatch):
    from creatorlab.hub import accounts,latest_posts
    db=tmp_path/'demo.db';monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    app.button(key='demo_start').click().run()
    app.selectbox(key='hero_work__douyin').select_index(1).run()
    work=app.selectbox(key='hero_work__douyin').value
    app.get('button_group')[0].set_value('详细数据').run()
    assert not app.exception and app.selectbox(key='report_work__douyin').value==work
    assert any('示例数据' in message.value for message in app.info)
    assert not any(b.key=='report_video_check' for b in app.button)
    assert not accounts(db) and not latest_posts(db)


def test_existing_feature_routes_keep_the_selected_work():
    state={'_open_report':12}
    assert consume_route(state)==WORK and state['report_work']==12 and state['work_view']=='详细数据'
    state={'_open_video_check':{'post_id':12,'account_id':3}}
    assert consume_route(state)==CREATE and state['material_post']==12 and state['video_check_account']==3
    state={'_workspace_route':CREATE,'_workspace_updates':{'create_step':'记录与复盘','review_task':5}}
    assert consume_route(state)==CREATE and state['review_task']==5
    assert consume_route(state) is None
