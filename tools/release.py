"""Check and build an allowlisted source release without personal runtime files."""
import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

DIRECTORIES={'creatorlab','app_pages','tests','tools','docs','assets','chrome-extension','.github','.agents'}
FILES={'.gitignore','.dockerignore','.env.example','AGENTS.md','HANDOFF.md','README.md','LICENSE',
       'CHANGELOG.md','app.py','bootstrap.py','Dockerfile','docker-compose.yml',
       'requirements.txt','requirements.lock','requirements-dev.txt','pytest.ini','RELEASE_MANIFEST.json',
       'README.txt'}
FORBIDDEN_DIRS={'local','artifacts','dist','private','__pycache__','.pytest_cache','.git','node_modules'}
PUBLIC_DB='assets/references/bilibili_weekly_100.sqlite3'
TEXT={'.py','.md','.txt','.json','.toml','.yaml','.yml','.js','.mjs','.html','.css','.bat','.sh','.csv','.lock'}
LEAKS=[('absolute user path',re.compile(r'[A-Za-z]:[/\\]Users[/\\][^\s/\\<>]+[/\\]',re.I)),
       ('absolute checkout path',re.compile(r'[A-Za-z]:[/\\]LabGit[/\\]',re.I)),
       ('literal API credential',re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})'))]


def allowed(path):
    p=Path(path);parts=p.parts;name=p.name
    if not parts or any(x in FORBIDDEN_DIRS or x.startswith('.venv') for x in parts):return False
    if p.as_posix()==PUBLIC_DB:return True
    if name in {'Local State','Login Data','Cookies','secrets.toml','.env'}:return False
    if p.suffix.lower() in {'.db','.sqlite','.sqlite3','.log','.zip','.pyc','.tmp','.lock'} and name!='requirements.lock':return False
    if '-journal' in name or name.endswith(('-wal','-shm','.access.lock','.auto-update.json')):return False
    if parts[0] in DIRECTORIES:return True
    if parts[0]=='data':return p.as_posix()=='data/demo_videos.csv'
    if parts[0]=='.streamlit':return p.as_posix()=='.streamlit/config.toml'
    return len(parts)==1 and (name in FILES or name.endswith('_windows.bat') or name=='start_mac_linux.sh')


def candidates(root):
    # Prune excluded trees instead of walking browser caches and virtualenvs.
    import os
    root=Path(root)
    for base,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if d not in FORBIDDEN_DIRS and not d.startswith('.venv')]
        for name in names:
            p=Path(base)/name;relative=p.relative_to(root)
            if allowed(relative):yield p


def version(root):
    tree=ast.parse((Path(root)/'creatorlab/version.py').read_text(encoding='utf-8'))
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets))


def check(root,tracked=False):
    root=Path(root);issues=[];files=list(candidates(root))
    for p in files:
        rel=p.relative_to(root).as_posix()
        if p.is_symlink():issues.append(f'{rel}: symbolic link is not release-safe');continue
        if p.suffix.lower() not in TEXT:continue
        try:text=p.read_text(encoding='utf-8-sig')
        except UnicodeError:issues.append(f'{rel}: text is not UTF-8');continue
        for label,pattern in LEAKS:
            for match in pattern.finditer(text):issues.append(f'{rel}:{text[:match.start()].count(chr(10))+1}: {label}')
    current=version(root)
    app=ast.parse((root/'app.py').read_text(encoding='utf-8'))
    for node in ast.walk(app):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='Page' and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
            target=node.args[0].value
            if not (root/target).is_file() or not allowed(target):issues.append(f'app.py: required navigation page omitted: {target}')
    for name in ('README.md','HANDOFF.md','docs/RELEASE_CHECKS.md'):
        if current not in (root/name).read_text(encoding='utf-8'):issues.append(f'{name}: missing current version {current}')
    document_names=sorted(p.relative_to(root).as_posix() for p in files if p.suffix=='.md' and (p.parent==root or p.relative_to(root).parts[0]=='docs'))
    for name in document_names:
        for target in re.findall(r'\]\(([^)]+)\)',(root/name).read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'):continue
            dest=(root/name).parent/target.split('#')[0]
            if not dest.exists():issues.append(f'{name}: broken local link {target}')
    if tracked:
        result=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True)
        if result.returncode:issues.append('Git tracked-file audit unavailable: directory is not a Git repository')
        else:
            for name in result.stdout.decode('utf-8').split('\0'):
                if name and not allowed(name):issues.append(f'{name}: tracked file outside release allowlist')
    return files,issues


def build(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    if output==root or output.exists():raise ValueError('Output must be a new directory; existing files are never overwritten')
    archive=output.parent/(output.name+'.zip')
    if archive.exists():raise ValueError('Release ZIP already exists; choose a new output directory')
    files,issues=check(root)
    if issues:raise ValueError('\n'.join(issues))
    files=[p for p in files if p.relative_to(root).as_posix()!='RELEASE_MANIFEST.json']
    manifest={}
    for p in files:
        rel=p.relative_to(root);dest=output/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest);manifest[rel.as_posix()]=hashlib.sha256(dest.read_bytes()).hexdigest()
    (output/'RELEASE_MANIFEST.json').write_text(json.dumps({'version':version(root),'files':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in output.rglob('*'):
            if p.is_file():z.write(p,Path(output.name)/p.relative_to(output))
    return archive,len(manifest)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--tracked',action='store_true');parser.add_argument('--output')
    args=parser.parse_args();files,issues=check(args.root,args.tracked)
    if issues:
        print('\n'.join(issues));raise SystemExit(1)
    print(f'Release check passed: {len(files)} allowlisted files; no runtime directories included.')
    if args.output:
        archive,count=build(args.root,args.output);print(f'Built {count} files: {archive}')


if __name__=='__main__':main()
