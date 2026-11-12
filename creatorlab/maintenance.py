"""Offline database safety and privacy-preserving diagnostics."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import zipfile
from datetime import datetime,timezone

from creatorlab.version import VERSION
_locks={};_local=threading.local();_map_guard=threading.Lock()


@contextlib.contextmanager
def database_gate(db,timeout=15):
    key=str(Path(db).resolve())
    with _map_guard:lock=_locks.setdefault(key,threading.RLock())
    if not lock.acquire(timeout=timeout):raise RuntimeError('数据库正在维护，请稍后重试')
    held=getattr(_local,'held',{});_local.held=held
    f=None
    try:
        if key not in held:
            path=Path(key+'.access.lock');path.parent.mkdir(parents=True,exist_ok=True)
            f=open(path,'a+b')
            if path.stat().st_size==0:f.write(b'0');f.flush()
            started=time.monotonic()
            while True:
                f.seek(0)
                try:
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic()-started>=timeout:raise RuntimeError('另一个窗口正在使用数据库，请稍后重试')
                    time.sleep(.05)
        held[key]=held.get(key,0)+1
        yield
    finally:
        if key in held:
            held[key]-=1
            if not held[key]:del held[key]
        if f:
            try:
                f.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(),fcntl.LOCK_UN)
            except OSError:pass
            f.close()
        lock.release()


def validate_database(path):
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with contextlib.closing(sqlite3.connect(uri,uri=True)) as con:
        if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库校验失败')
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'hub_accounts','hub_posts','hub_snapshots'}<=tables:raise ValueError('这不是CLab作品数据库')
        for table,fields in {'hub_accounts':{'id','platform','handle'},'hub_posts':{'id','account_id','title'},'hub_snapshots':{'id','post_id','views'}}.items():
            if not fields<={r[1] for r in con.execute('PRAGMA table_info('+table+')')}:raise ValueError('数据库结构不兼容')
        if con.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('数据库存在不完整的关联记录')


def backup_database(db,reason='manual'):
    db=Path(db);dest=db.parent/'backups';dest.mkdir(parents=True,exist_ok=True)
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+reason+'.db'
    target=dest/name
    with database_gate(db),contextlib.closing(sqlite3.connect(str(db))) as source,contextlib.closing(sqlite3.connect(str(target))) as out:
        source.backup(out)
    return target


def daily_backup(db):
    db=Path(db)
    if not db.exists() or not db.stat().st_size:return None
    day=datetime.now(timezone.utc).strftime('%Y%m%d')
    with database_gate(db):
        if list((db.parent/'backups').glob(day+'*-daily.db')):return None
        result=backup_database(db,'daily')
        old=sorted((db.parent/'backups').glob('*-daily.db'))
        for path in old[:-7]:path.unlink()
        return result


def prepare_upgrade(db,schema=20400):
    db=Path(db)
    if not db.exists() or not db.stat().st_size:return
    with contextlib.closing(sqlite3.connect(str(db))) as con:
        current=con.execute('PRAGMA user_version').fetchone()[0]
        existing=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
    if current>schema:raise ValueError('数据库由更高版本创建，请使用对应新版程序，避免降级写入')
    if existing and current<schema:return backup_database(db,'before-upgrade')


def export_backup(db):
    with database_gate(db):
        snapshot=backup_database(db,'export')
        try:
            return archive_snapshot(snapshot)
        finally:snapshot.unlink(missing_ok=True)


def archive_snapshot(path):
    validate_database(path)
    raw=Path(path).read_bytes();manifest={'format':'clab-backup-1','version':VERSION,'sha256':hashlib.sha256(raw).hexdigest()}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('creatorlab.db',raw);z.writestr('manifest.json',json.dumps(manifest))
    return out.getvalue()


def restore_backup(db,data):
    if len(data)>250_000_000:raise ValueError('备份文件超过250MB')
    db=Path(db);tmp=db.with_name(db.name+'.restore.tmp')
    with database_gate(db):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if len(z.namelist())!=2 or set(z.namelist())!={'creatorlab.db','manifest.json'}:raise ValueError('备份内容不符合格式')
                if z.getinfo('creatorlab.db').file_size>1_000_000_000:raise ValueError('备份解压后过大')
                if z.getinfo('manifest.json').file_size>10000:raise ValueError('备份清单无效')
                raw=z.read('creatorlab.db');meta=json.loads(z.read('manifest.json'))
                if not isinstance(meta,dict) or meta.get('format')!='clab-backup-1' or hashlib.sha256(raw).hexdigest()!=meta.get('sha256'):raise ValueError('备份完整性校验失败')
            tmp.write_bytes(raw);validate_database(tmp)
            with contextlib.closing(sqlite3.connect(str(tmp))) as source:
                if source.execute('PRAGMA user_version').fetchone()[0]>20400:raise ValueError('请先升级程序，再恢复较新版本的备份')
                safety=backup_database(db,'before-restore') if db.exists() else None
                with contextlib.closing(sqlite3.connect(str(db))) as target:source.backup(target)
            return safety
        except (zipfile.BadZipFile,KeyError,json.JSONDecodeError,sqlite3.DatabaseError) as exc:raise ValueError('备份文件损坏或格式不支持') from exc
        finally:tmp.unlink(missing_ok=True)


def diagnostics(db,root):
    import platform
    import importlib.metadata as metadata
    result={'app_version':VERSION,'python':platform.python_version(),'system':platform.system(),'database':{},'jobs':{},'dependencies':{}}
    for name in ('streamlit','pandas','plotly','playwright','Pillow'):
        try:result['dependencies'][name]=metadata.version(name)
        except metadata.PackageNotFoundError:result['dependencies'][name]='missing'
    with database_gate(db),contextlib.closing(sqlite3.connect(str(db))) as con:
        result['database']['integrity']=con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        result['database']['works_by_platform']=dict(con.execute('SELECT a.platform,count(*) FROM hub_posts p JOIN hub_accounts a ON a.id=p.account_id GROUP BY a.platform'))
    for name in ('sync_status.json','bilibili_sync_status.json'):
        try:
            data=json.loads((Path(root)/'local'/name).read_text(encoding='utf-8'))
            state=data.get('state')
            safe={'state':state if state in {'starting','waiting_login','collecting','recovering','details','review','imported','partial','completed','stalled','stopped','empty','error','interrupted','covers','creator'} else 'unknown'}
            safe.update({k:v for k in ('count','total','pages','details','raw_rows_seen','rejected_rows','with_cover','cover_targets','visible_list_count') if isinstance((v:=data.get(k)),int) and not isinstance(v,bool) and v>=0})
            if data.get('list_end_reason') in {'visible_list_exhausted','inventory_matched','user_stopped','browser_closed','list_budget_exhausted','list_stalled','capture_error'}:safe['list_end_reason']=data['list_end_reason']
            if isinstance(data.get('visible_list_ended'),bool):safe['visible_list_ended']=data['visible_list_ended']
            if isinstance(data.get('source_has_more'),bool):safe['source_has_more']=data['source_has_more']
            safe['coverage']={k:v for k,v in data.get('coverage',{}).items() if k in {'views','likes','comments','shares','favorites','coins','danmaku','completion_rate'} and isinstance(v,int) and v>=0}
            result['jobs'][name]=safe
        except (OSError,ValueError):pass
    return json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8')


def environment_report():
    import platform
    found=[]
    for base in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
        folder=os.environ.get(base)
        if folder:
            for suffix in ('Microsoft/Edge/Application/msedge.exe','Google/Chrome/Application/chrome.exe'):
                if (Path(folder)/suffix).is_file():found.append('Edge' if 'Edge' in suffix else 'Chrome')
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if Path(p.chromium.executable_path).is_file():found.append('Chromium')
    except Exception:pass
    return [{'项目':'Python','状态':platform.python_version()},
      {'项目':'采集浏览器','状态':'、'.join(sorted(set(found))) if found else '未发现，请点击安装导入浏览器'},
      {'项目':'本地视频抽帧（可选）','状态':'已安装FFmpeg' if shutil.which('ffmpeg') else '未安装；仍可直接上传关键帧'},
      {'项目':'AI（可选）','状态':'未配置模型也可使用导入、图表和手动分类'}]


def clear_profiles(root,platform):
    from creatorlab.bilibili_import import job_running
    if platform not in ('douyin','bilibili'):raise ValueError('未知平台')
    if job_running(root) or job_running(root,'douyin'):raise ValueError('请先停止全部采集窗口')
    local=Path(root)/'local'
    names=['douyin_browser_profile','douyin_browser_profiles','douyin_discovery_profile'] if platform=='douyin' else ['bilibili_browser_profile']
    for name in names:
        path=local/name
        if path.is_symlink():raise ValueError('登录目录是外部链接，已停止清理')
    for name in names:
        path=local/name
        if path.exists():shutil.rmtree(path)
