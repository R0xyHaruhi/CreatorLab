import ast
from pathlib import Path
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub
from creatorlab.workspaces import set_mode,get_mode

ROOT=Path(__file__).resolve().parents[1]


def test_only_four_personal_pages_are_registered():
    tree=ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
    pages=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Page']
    assert set(pages)=={'app_pages/works.py','app_pages/create.py','app_pages/library.py','app_pages/settings.py'}


def test_old_team_setting_does_not_expose_team_ui_or_destroy_saved_setting(tmp_path,monkeypatch):
    db=tmp_path/'d.db';init_hub(db);set_mode(db,'team')
    monkeypatch.setenv('CREATORLAB_DB',str(db))
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    assert not app.exception
    assert all('工作模式' not in r.label for r in app.radio)
    app.session_state['settings_view']='备份与诊断'
    app.switch_page('app_pages/settings.py').run()
    assert not app.exception,[e.message for e in app.exception]
    assert not any('团队' in e.label or '旧版工具' in e.label for e in app.expander)
    assert get_mode(db)=='team'
