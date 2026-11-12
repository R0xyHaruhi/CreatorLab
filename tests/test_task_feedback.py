from pathlib import Path
from types import SimpleNamespace
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,commit_capture
from creatorlab.task_feedback import summarize

OLD='7412345678901234567'
NEW='7412345678901234568'


def seed(db):
    init_hub(db);aid=add_account(db,'douyin','me','验收账号')
    upsert_post(db,aid,'已入库作品',OLD,metrics={'views':100})
    return aid


def capture(db,aid,ids):
    run=create_capture(db,aid)
    stage_rows(db,run,[dict(video_id=vid,title='采集作品',views=200) for vid in ids]);finish_capture(db,run)
    return run


def test_pending_new_counts_unique_ids_and_import_changes_summary(tmp_path):
    db=tmp_path/'d.db';aid=seed(db)
    first=capture(db,aid,[OLD,NEW]);capture(db,aid,[OLD,NEW])
    before=summarize(db,'douyin',aid,{'state':'review'})
    assert before['stored']==1 and before['pending_new']==1 and before['pending_groups']==1
    assert '归属确认' in before['title'] and '不用重新扫描' in before['action']
    commit_capture(db,first,aid)
    after=summarize(db,'douyin',aid,{'state':'imported'})
    assert after['stored']==2 and after['pending_new']==0 and after['last_saved']
    assert '已入库' in after['title']


def test_account_and_platform_isolation_and_login_pause(tmp_path):
    db=tmp_path/'d.db';a=seed(db);b=add_account(db,'douyin','other')
    capture(db,b,[NEW])
    other=summarize(db,'douyin',a,{'account_id':b,'state':'error'})
    assert other['stored']==1 and other['pending_new']==0 and '未完成' not in other['title']
    paused=summarize(db,'douyin',a,{'account_id':a,'state':'waiting_login','sync_mode':'existing'})
    assert paused['title']=='自动更新已暂停' and '手动同步' in paused['action']
    bili=add_account(db,'bilibili','123')
    assert summarize(db,'bilibili',bili)['stored']==0


@pytest.mark.parametrize('state',['error','interrupted','stalled','stopped'])
def test_failure_does_not_claim_saved_data_is_lost(tmp_path,state):
    db=tmp_path/'d.db';aid=seed(db)
    result=summarize(db,'douyin',aid,{'state':state})
    assert result['stored']==1 and '保留' in result['title']


def test_top_card_and_task_details_do_not_duplicate_confirmation_ui(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1];db=tmp_path/'d.db';aid=seed(db);capture(db,aid,[NEW])
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(root/'app.py'),default_timeout=30).run().switch_page('app_pages/settings.py').run()
    assert not app.exception,[e.message for e in app.exception]
    assert any(h.value=='新作品已读到，还差归属确认' for h in app.subheader)
    assert len([b for b in app.button if b.label=='确认归属并入库'])==1
    assert any(e.label=='任务详情与缺项补采' and not e.proto.expanded for e in app.expander)


def test_busy_database_shows_saving_state_instead_of_page_error(tmp_path,monkeypatch):
    import creatorlab.task_feedback as feedback
    def busy(*a,**kw):raise RuntimeError('temporary database lock')
    monkeypatch.setattr(feedback,'summarize',busy)
    app=AppTest.from_string('from creatorlab.task_feedback import panel\npanel('+repr(str(tmp_path/'d.db'))+','+repr(str(tmp_path))+',"douyin")').run()
    assert not app.exception and any('正在保存本轮数据' in i.value for i in app.info)


def test_new_user_can_add_douyin_account_by_nickname_and_continue_to_sync(tmp_path,monkeypatch):
    from creatorlab.hub import accounts
    root=Path(__file__).resolve().parents[1];db=tmp_path/'new.db'
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(root/'app.py'),default_timeout=30).run().switch_page('app_pages/settings.py').run()
    assert app.button(key='task_first_account')
    assert not any(b.label=='首次导入抖音作品' for b in app.button)
    app.button(key='task_first_account').click().run()
    next(t for t in app.text_input if t.label=='账号昵称（选填）').set_value('新手账号')
    next(b for b in app.button if b.label=='保存账号').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert accounts(db)[0]['display_name']=='新手账号'
    assert app.session_state['settings_view']=='同步与进度'
    assert any(h.value=='账号已添加，下一步导入作品' for h in app.subheader)


def test_first_csv_path_keeps_account_setup_then_opens_imported_works(tmp_path,monkeypatch):
    from creatorlab.hub import add_account,latest_posts,upsert_post
    root=Path(__file__).resolve().parents[1];db=tmp_path/'csv.db'
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(root/'app.py'),default_timeout=30).run()
    next(w for w in app.get('button_group') if w.key=='first_import_method').set_value('导入 CSV').run()
    next(w for w in app.text_input if w.label=='账号昵称（选填）').set_value('CSV账号')
    next(b for b in app.button if b.label=='保存账号').click().run()
    assert app.session_state['settings_view']=='账号与文件导入' and not app.exception
    old=add_account(db,'douyin','other','其他账号')
    upsert_post(db,old,'已有作品',metrics={'views':100})
    app.file_uploader[0].upload('works.csv',b'title,views\nImported,1000\n','text/csv').run()
    next(b for b in app.button if b.label=='确认导入 CSV').click().run()
    app.button(key='settings_import_view').click().run()
    assert not app.exception and len(latest_posts(db))==2
    assert any('找到 1 / 1 条作品' in c.value for c in app.caption)
    assert not any('已有作品' in m.value for m in app.markdown)
    app.button(key='library_clear_import').click().run()
    assert any('找到 2 / 2 条作品' in c.value for c in app.caption)
