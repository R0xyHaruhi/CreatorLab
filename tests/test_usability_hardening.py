import io
import json
from pathlib import Path
import socket
import sqlite3
import zipfile
import pytest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts,connect,import_csv,preview_csv,auto_sync_douyin
from creatorlab.maintenance import export_backup,restore_backup,diagnostics,validate_database,daily_backup
from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture,pending_captures,commit_capture,recover_interrupted


def base(db):
    init_hub(db);return add_account(db,'douyin','one','账号一')


def event(vid='7412345678901234567',**extra):
    return {'video_id':vid,'title':'作品','views':100,'likes':5,**extra}


def test_capture_never_chooses_first_account_and_requires_review(tmp_path):
    db=tmp_path/'d.db';a=base(db);b=add_account(db,'douyin','two')
    with pytest.raises(ValueError):create_capture(db,None)
    run=create_capture(db,b);stage_rows(db,run,[event()]);finish_capture(db,run)
    assert latest_posts(db)==[]
    with pytest.raises(ValueError):commit_capture(db,run,a)
    assert commit_capture(db,run,b)==1
    assert latest_posts(db)[0]['account_id']==b
    assert commit_capture(db,run,b)==0


def test_account_switch_during_capture_rejects_whole_batch(tmp_path):
    db=tmp_path/'d.db';a=base(db);run=create_capture(db,a)
    stage_rows(db,run,[event(owner_key='author-one')])
    with pytest.raises(ValueError):stage_rows(db,run,[event(owner_key='author-two')])
    finish_capture(db,run)
    assert pending_captures(db)[0]['count']==1


def test_owner_identifier_namespaces_do_not_cause_false_account_switch(tmp_path):
    db=tmp_path/'d.db';a=base(db);run=create_capture(db,a)
    stage_rows(db,run,[event(owner_key='uid:123')])
    stage_rows(db,run,[event(owner_key='sec:opaque-id')])
    with pytest.raises(ValueError):stage_rows(db,run,[event(owner_key='uid:999')])


def test_failed_schema_upgrade_rolls_back_to_protection_copy(tmp_path,monkeypatch):
    import creatorlab.hub as module
    db=tmp_path/'d.db';a=base(db);upsert_post(db,a,'保留作品','one',metrics={'views':21})
    with connect(db) as con:con.execute('PRAGMA user_version=20300')
    def fail(db):
        with connect(db) as con:con.execute("UPDATE hub_posts SET title='migration changed this'")
        raise RuntimeError('simulated migration failure')
    monkeypatch.setattr(module,'_init_hub',fail)
    with pytest.raises(RuntimeError):module.init_hub(db)
    assert latest_posts(db)[0]['title']=='保留作品'
    with connect(db) as con:assert con.execute('PRAGMA user_version').fetchone()[0]==20300


def test_interrupted_capture_survives_without_automatic_import(tmp_path):
    db=tmp_path/'d.db';a=base(db);run=create_capture(db,a)
    stage_rows(db,run,[event()],observed_at='2026-01-02T00:00:00Z')
    recover_interrupted(db)
    assert pending_captures(db)[0]['id']==run and latest_posts(db)==[]
    commit_capture(db,run,a)
    assert latest_posts(db)[0]['field_observed_at']['views'].startswith('2026-01-02')


def test_failed_capture_import_restores_existing_data(tmp_path,monkeypatch):
    import creatorlab.douyin_capture as module
    db=tmp_path/'d.db';a=base(db);upsert_post(db,a,'已有作品','existing',metrics={'views':777})
    run=create_capture(db,a);stage_rows(db,run,[event(),event('7412345678901234568')]);finish_capture(db,run)
    original=module.upsert_post;calls=[0]
    def fail(*args,**kwargs):
        calls[0]+=1
        if calls[0]==2:raise OSError('simulated disk failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'upsert_post',fail)
    with pytest.raises(OSError):commit_capture(db,run,a)
    assert [p['views'] for p in latest_posts(db)]==[777]
    assert pending_captures(db)[0]['state']=='review'


def test_ambiguous_legacy_rows_are_not_assigned_to_first_account(tmp_path):
    from creatorlab.bridge import save_batch
    db=tmp_path/'d.db';base(db);add_account(db,'douyin','two')
    save_batch(db,{'rows':[event()]})
    assert not auto_sync_douyin(db)['available'] and latest_posts(db)==[]


def test_backup_restores_works_and_keeps_pre_restore_copy(tmp_path):
    db=tmp_path/'d.db';a=base(db);upsert_post(db,a,'作品','one',metrics={'views':100})
    data=export_backup(db)
    assert set(zipfile.ZipFile(io.BytesIO(data)).namelist())=={'creatorlab.db','manifest.json'}
    upsert_post(db,a,'作品','one',metrics={'views':999})
    safety=restore_backup(db,data)
    assert safety.is_file() and latest_posts(db)[0]['views']==100
    validate_database(db)


def test_invalid_backup_does_not_modify_database(tmp_path):
    db=tmp_path/'d.db';a=base(db);upsert_post(db,a,'保留','one',metrics={'views':222})
    with pytest.raises(ValueError):restore_backup(db,b'not a backup')
    assert latest_posts(db)[0]['views']==222


def test_upgrade_creates_backup_before_altering_old_schema(tmp_path):
    db=tmp_path/'old.db'
    with sqlite3.connect(db) as con:con.execute('CREATE TABLE videos(id INTEGER PRIMARY KEY,title TEXT)');con.execute("INSERT INTO videos VALUES(1,'原数据')")
    init_hub(db)
    backups=list((tmp_path/'backups').glob('*before-upgrade.db'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as con:
        assert con.execute('SELECT title FROM videos').fetchone()[0]=='原数据'
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='hub_posts'").fetchone()
    assert daily_backup(db).is_file() and daily_backup(db) is None


def test_database_connection_closes_after_context(tmp_path):
    db=tmp_path/'d.db';base(db)
    with connect(db) as con:con.execute('SELECT 1')
    with pytest.raises(sqlite3.ProgrammingError):con.execute('SELECT 1')


def test_diagnostics_excludes_user_data_secrets_and_raw_logs(tmp_path):
    db=tmp_path/'d.db';a=base(db);upsert_post(db,a,'私密标题-SECRET','private-id',metrics={'views':1})
    local=tmp_path/'local';local.mkdir()
    (local/'sync_status.json').write_text(json.dumps({'state':'error','count':3,'uid':'SECRET-USER','error':'Bearer SECRET-TOKEN','coverage':{'views':2,'SECRET-KEY':123}}))
    data=diagnostics(db,tmp_path).decode()
    assert 'SECRET' not in data and 'private-id' not in data
    assert json.loads(data)['jobs']['sync_status.json']['count']==3


def test_csv_preview_encoding_and_duplicate_import_are_safe(tmp_path):
    db=tmp_path/'d.db';a=base(db)
    raw='title,external_id,views\n中文作品,one,200\n'.encode('gb18030')
    plan=preview_csv(db,a,raw)
    assert plan['rows'][0]['title']=='中文作品' and not plan['duplicate']
    assert latest_posts(db)==[]
    assert import_csv(db,a,raw)==1 and import_csv(db,a,raw)==0
    assert len(latest_posts(db))==1
    with pytest.raises(ValueError):preview_csv(db,a,'title,external_id,views\nA,same,1\nB,same,2\n')


def test_port_conflict_chooses_free_local_port():
    import bootstrap
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        assert bootstrap.available_port(port)!=port


def test_daily_launch_does_not_run_pip_when_environment_is_ready(tmp_path,monkeypatch):
    import bootstrap
    from types import SimpleNamespace
    (tmp_path/'requirements.lock').write_text('pandas==2.2.3\n')
    python=tmp_path/'venv-python';python.write_text('')
    (tmp_path/'local').mkdir();(tmp_path/'local'/'environment.json').write_text(json.dumps({'requirements':bootstrap.dependency_fingerprint(tmp_path)}))
    monkeypatch.setattr(bootstrap,'env_python',lambda root:python)
    monkeypatch.setattr(bootstrap,'dependencies_ok',lambda *args:True)
    calls=[]
    def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0,stdout='3.12\n')
    monkeypatch.setattr(bootstrap.subprocess,'run',run)
    bootstrap.ensure_environment(tmp_path)
    assert len(calls)==1 and not any('pip' in args for args in calls)


def test_batched_profiles_match_original_scores_with_ties_and_missing_values(tmp_path):
    from creatorlab.content_analysis import frame
    from creatorlab.battlecard import profile,profiles
    db=tmp_path/'d.db';a=base(db)
    for i in range(12):upsert_post(db,a,str(i),str(i),'2026-01-01T00:00:00Z',metrics={'views':100+(i%3)*100,'likes':10 if i%2 else None,'completion_rate':.5},observed_at='2026-02-01T00:00:00Z')
    df=frame(latest_posts(db));fast=profiles(df)
    for row in df.to_dict('records'):
        old=profile(df,row)
        for expected,actual in zip(old['scores'],fast[row['id']]['scores']):
            assert expected['n']==actual['n']
            assert actual['score']==pytest.approx(expected['score']) if expected['score'] is not None else actual['score'] is None


def test_recovery_from_automatic_snapshot_even_if_current_database_is_corrupt(tmp_path,monkeypatch):
    from creatorlab.maintenance import backup_database
    from creatorlab.recovery import recover_file
    local=tmp_path/'local';local.mkdir();db=local/'creatorlab.db';a=base(db)
    upsert_post(db,a,'可恢复作品','one',metrics={'views':123})
    saved=backup_database(db,'daily');db.write_bytes(b'corrupt database')
    monkeypatch.delenv('CREATORLAB_DB',raising=False)
    recover_file(tmp_path,saved)
    assert latest_posts(db)[0]['views']==123
    assert list((local/'backups').glob('damaged-*'))


def test_first_use_sample_does_not_write_accounts_works_or_experiments(tmp_path):
    from streamlit.testing.v1 import AppTest
    from creatorlab.hub import accounts
    db=tmp_path/'d.db';init_hub(db)
    code='from creatorlab.personal_ui import hero\nhero([],'+repr(str(db))+',"douyin")'
    app=AppTest.from_string(code).run()
    assert not app.exception
    app.button(key='demo_start').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.button(key='hero_accept').disabled
    assert accounts(db)==[] and latest_posts(db)==[]
    assert any('示例预览' in i.value for i in app.info)


def test_first_use_can_create_account_and_show_import_action(tmp_path):
    from streamlit.testing.v1 import AppTest
    from creatorlab.hub import accounts
    db=tmp_path/'d.db';init_hub(db)
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nhero([],'+repr(str(db))+',"douyin")').run()
    next(t for t in app.text_input if t.label=='账号昵称').set_value('我的新账号')
    app.button(key='FormSubmitter:first_account-添加账号').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert accounts(db)[0]['display_name']=='我的新账号'
    assert app.button(key='first_dy_start').label=='首次导入抖音作品'


def test_capture_review_ui_imports_only_after_user_checks_destination(tmp_path):
    from streamlit.testing.v1 import AppTest
    db=tmp_path/'d.db';a=base(db);run=create_capture(db,a);stage_rows(db,run,[event()]);finish_capture(db,run)
    code='from creatorlab.douyin_ui import review_captures\nreview_captures('+repr(str(db))+','+repr(str(tmp_path))+')'
    app=AppTest.from_string(code).run()
    assert not app.exception and app.button(key='capture_commit_'+run).disabled
    assert latest_posts(db)==[]
    app.checkbox(key='capture_check_'+run).check().run()
    app.button(key='capture_commit_'+run).click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert latest_posts(db)[0]['account_id']==a and pending_captures(db)==[]


def test_csv_metadata_update_preserves_existing_classification(tmp_path):
    from creatorlab.content_analysis import annotate
    db=tmp_path/'d.db';a=base(db);pid=upsert_post(db,a,'作品','one',metrics={'views':1})
    annotate(db,pid,'生活 / Vlog','故事','校园',30)
    assert import_csv(db,a,'title,external_id,views,duration_seconds\n作品,one,3,45\n')==1
    row=latest_posts(db)[0]
    assert row['category']=='故事' and row['topic']=='校园' and row['duration_seconds']==45


def test_legacy_import_failure_rolls_back_prior_rows(tmp_path,monkeypatch):
    from creatorlab.hub import import_douyin_existing
    db=tmp_path/'d.db';a=base(db)
    upsert_post(db,a,'原有作品','original',metrics={'views':1})
    monkeypatch.setattr('creatorlab.bridge.list_batch',lambda _: [
        {'id':1,'video_id':'first','title':'第一条','views':10},
        {'id':2,'video_id':'broken','title':'错误行','views':-1}])
    with pytest.raises(ValueError):import_douyin_existing(db,a,db)
    assert [r['external_id'] for r in latest_posts(db)]==['original']
