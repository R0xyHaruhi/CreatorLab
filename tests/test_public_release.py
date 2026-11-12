from pathlib import Path
import json
import hashlib
import zipfile
import pytest
from tools.release import allowed,build,check,version

ROOT=Path(__file__).resolve().parents[1]


def test_public_check_has_no_private_paths_and_current_docs_are_consistent():
    files,issues=check(ROOT)
    assert not issues,issues
    assert files and all(allowed(p.relative_to(ROOT)) for p in files)


@pytest.mark.parametrize('path',['local/creatorlab.db','artifacts/qa/example.py','docs/private/HANDOFF.md',
    '.venv/lib/example.py','.env','.streamlit/secrets.toml','creatorlab/debug.log',
    'assets/private.sqlite3','data/personal.csv','creatorlab/Local State','creatorlab/Cookies'])
def test_private_runtime_files_are_never_release_candidates(path):
    assert not allowed(path)


def test_build_contains_licenses_reference_db_and_manifest_but_no_runtime_data(tmp_path):
    dest=tmp_path/'CreatorLab-test'
    archive,count=build(ROOT,dest)
    manifest=json.loads((dest/'RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
    assert count==len(manifest['files']) and manifest['version']==version(ROOT)
    assert '.agents/skills/unslop/LICENSE' in manifest['files']
    assert 'assets/references/bilibili_weekly_100.sqlite3' in manifest['files']
    assert 'LICENSE' in manifest['files']
    assert all('app_pages/'+name+'.py' in manifest['files'] for name in ('works','create','library','settings'))
    assert not any(name.startswith('pages/') for name in manifest['files'])
    assert 'RELEASE_MANIFEST.json' not in manifest['files']
    assert all(hashlib.sha256((dest/name).read_bytes()).hexdigest()==digest for name,digest in manifest['files'].items())
    assert not (dest/'local').exists() and not (dest/'artifacts').exists()
    with zipfile.ZipFile(archive) as z:assert all('/local/' not in n and '/private/' not in n for n in z.namelist())
    with pytest.raises(ValueError):build(ROOT,dest)


def test_online_cli_accepts_existing_mode_without_starting_real_browser(monkeypatch,tmp_path):
    import creatorlab.sync_browser as sync
    import sys
    calls=[]
    monkeypatch.setattr(sync,'start',lambda *args:calls.append(args) or 0)
    monkeypatch.setattr(sys,'argv',['sync_browser','--db',str(tmp_path/'test.db'),'--root',str(tmp_path),
                                   '--account-id','1','--mode','existing'])
    with pytest.raises(SystemExit) as result:sync.main()
    assert result.value.code==0 and calls[0][-1]=='existing'


def test_privacy_guard_reports_location_without_echoing_sensitive_values(tmp_path):
    for name in ('README.md','HANDOFF.md','docs/RELEASE_CHECKS.md','docs/LIVE_VALIDATION.md','docs/PUBLISHING.md'):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('1.0',encoding='utf-8')
    package=tmp_path/'creatorlab';package.mkdir()
    (package/'version.py').write_text("VERSION = '1.0'",encoding='utf-8')
    (tmp_path/'app.py').write_text('',encoding='utf-8')
    credential='sk-'+'X'*32
    user_path='C:'+ '/Users/'+'PrivatePerson/'+'secret'
    (package/'accident.py').write_text(credential+'\n'+user_path,encoding='utf-8')
    _,issues=check(tmp_path)
    assert any('credential' in issue for issue in issues)
    assert any('absolute user path' in issue for issue in issues)
    assert all(credential not in issue and user_path not in issue for issue in issues)
    (tmp_path/'app.py').write_text("st.Page('pages/missing.py')",encoding='utf-8')
    assert any('required navigation page omitted' in issue for issue in check(tmp_path)[1])
