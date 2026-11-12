"""Offline rescue even when the application cannot open its current database."""
import os
from pathlib import Path
import sys
from creatorlab.maintenance import database_gate,restore_backup,validate_database,archive_snapshot


def recover_file(root,backup):
    from creatorlab.bilibili_import import job_running
    root=Path(root)
    if job_running(root) or job_running(root,'douyin'):raise ValueError('请先关闭全部采集窗口')
    # Launcher holds this gate for the lifetime of the UI server.
    with database_gate(root/'local'/'ui-instance',timeout=.2):
        db=Path(os.getenv('CREATORLAB_DB',str(root/'local'/'creatorlab.db')))
        path=Path(backup)
        if path.stat().st_size>250_000_000:raise ValueError('备份文件不能超过250MB')
        data=archive_snapshot(path) if path.suffix.lower()=='.db' else path.read_bytes()
        with database_gate(db):
            corrupt=False
            if db.exists():
                try:validate_database(db)
                except Exception:corrupt=True
            moved=[]
            try:
                if corrupt:
                    import time
                    rescue=db.parent/'backups'/('damaged-'+str(time.time_ns()));rescue.mkdir(parents=True)
                    for part in (db,Path(str(db)+'-wal'),Path(str(db)+'-shm'),Path(str(db)+'-journal')):
                        if part.exists():
                            target=rescue/part.name;part.replace(target);moved.append((part,target))
                restore_backup(db,data)
            except Exception:
                if corrupt:
                    db.unlink(missing_ok=True)
                    for original,target in moved:target.replace(original)
                raise


if __name__=='__main__':
    try:recover_file(Path(__file__).resolve().parents[1],sys.argv[1]);print('恢复完成')
    except Exception as exc:print('恢复未完成：'+str(exc),file=sys.stderr);raise SystemExit(1)
