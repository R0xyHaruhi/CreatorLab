import hashlib
import json
import pytest
from test_creative_workflow import seed,labelled
from creatorlab.creative_brief import build_brief,save_plan,plan_experiment
from creatorlab.workflow_backup import export_account,inspect_backup,import_account
from creatorlab.workflow_store import get,store_path,documents
from creatorlab.hub import add_account,latest_posts


def test_workflow_backup_is_account_bound_additive_and_roundtrips(tmp_path):
    db=tmp_path/'personal.db';aid,a,b=seed(db);rows=labelled(db)
    key=save_plan(db,build_brief(rows,rows[0],'views'))
    eid=plan_experiment(db,aid,'bilibili',key,'标题')
    before=latest_posts(db)
    raw=export_account(db,aid,'bilibili')
    assert len(inspect_backup(db,aid,'bilibili',raw)['records'])==2
    assert import_account(db,aid,'bilibili',raw)=={'added':0,'skipped':2}
    store_path(db).unlink()  # disposable test workflow only; primary DB remains intact
    assert import_account(db,aid,'bilibili',raw)=={'added':2,'skipped':0}
    assert get(db,'plan',aid,'bilibili',key)['title']==rows[0]['title']
    assert latest_posts(db)==before
    other=add_account(db,'bilibili','different')
    with pytest.raises(ValueError,match='账号'):inspect_backup(db,other,'bilibili',raw)


def test_invalid_backup_is_rejected_before_any_document_write(tmp_path):
    db=tmp_path/'personal.db';aid,a,b=seed(db)
    save_plan(db,build_brief(labelled(db),labelled(db)[0],'views'))
    raw=export_account(db,aid,'bilibili');obj=json.loads(raw)
    obj['payload']['records'][-1]['kind']='unexpected'
    body=json.dumps(obj['payload'],ensure_ascii=False,sort_keys=True,allow_nan=False)
    obj['sha256']=hashlib.sha256(body.encode()).hexdigest()
    store_path(db).unlink()
    with pytest.raises(ValueError):import_account(db,aid,'bilibili',json.dumps(obj).encode())
    assert not store_path(db).exists()
    with pytest.raises(ValueError):inspect_backup(db,aid,'bilibili',b'{broken')
