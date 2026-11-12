"""Opt-in, durable per-account scheduling while the local app server is running."""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

INTERVALS=(6,12,24)


def config_path(db):return Path(db).with_suffix('.auto-update.json')


def load(db):
    try:
        data=json.loads(config_path(db).read_text(encoding='utf-8'))
        if data.get('database')!=str(Path(db).resolve()) or not isinstance(data.get('accounts'),dict):return {}
        return {k:v for k,v in data['accounts'].items() if str(k).isdigit() and isinstance(v,dict)
                and isinstance(v.get('enabled'),bool) and v.get('hours') in INTERVALS}
    except (OSError,ValueError,AttributeError):return {}


def _save(db,accounts):
    from creatorlab.file_io import atomic_json
    atomic_json(config_path(db),{'database':str(Path(db).resolve()),'accounts':accounts})


def eligible_ids(db,aid):
    """Never expand a scheduled task to unreviewed or ambiguous account identities."""
    from creatorlab.hub import connect
    try:
        with connect(db) as con:
            own=con.execute("SELECT 1 FROM hub_accounts WHERE id=? AND platform='douyin' AND is_self=1",(aid,)).fetchone()
            if not own:return set()
            reviewed={r[0] for r in con.execute("SELECT DISTINCT e.video_id FROM clab_dy_events e JOIN clab_dy_runs r ON r.id=e.run_id WHERE r.account_id=? AND r.state='committed'",(aid,))}
            owners={}
            for r in con.execute("SELECT p.external_id,p.account_id FROM hub_posts p JOIN hub_accounts a ON a.id=p.account_id WHERE a.platform='douyin'"):
                owners.setdefault(r[0],set()).add(r[1])
            return {vid for vid in reviewed if owners.get(vid)=={aid}}
    except sqlite3.OperationalError:return set()


def configure(db,aid,enabled,hours=24,now=None):
    from creatorlab.hub import accounts
    from creatorlab.maintenance import database_gate
    if hours not in INTERVALS:raise ValueError('更新间隔请选择6、12或24小时')
    if not any(a['id']==aid and a['platform']=='douyin' and a['is_self'] for a in accounts(db)):raise ValueError('请选择自己的抖音账号')
    if enabled and not eligible_ids(db,aid):raise ValueError('请先核对并入库至少一批作品，再启用自动更新')
    at=time.time() if now is None else now
    with database_gate(config_path(db)):
        all_settings=load(db);old=all_settings.get(str(aid),{})
        all_settings[str(aid)]={**old,'enabled':bool(enabled),'hours':hours,'paused':False,
                               'next_at':at+30,'message':'将在一分钟内开始首次更新' if enabled else '已关闭；正在执行的任务会完成本轮'}
        _save(db,all_settings)


def launch_due(db,root,now=None,spawn=None):
    from creatorlab.bilibili_import import job_running
    from creatorlab.maintenance import database_gate
    if os.getenv('CREATORLAB_ANALYSIS_ONLY')=='1' or job_running(root,'douyin'):return False
    at=time.time() if now is None else now
    with database_gate(config_path(db)):
        settings=load(db)
        for key,item in settings.items():
            if not item.get('enabled') or item.get('paused'):continue
            if item.get('lease_until',0)>at:
                # The platform lock was free above. Allow a newly spawned worker
                # one minute to acquire it, then recover a crashed worker lease
                # instead of waiting half an hour after server interruption.
                if at-item.get('last_attempt',0)<=60:continue
                item.update(lease_until=0,next_at=min(item.get('next_at',at),at))
            if item.get('next_at',0)>at:continue
            token=uuid.uuid4().hex
            item.update(token=token,lease_until=at+1800,last_attempt=at,next_at=at+item['hours']*3600,message='正在后台更新已入库作品')
            _save(db,settings)
            try:
                if spawn:spawn(int(key),token)
                else:
                    log_path=config_path(db).with_suffix('.log')
                    with log_path.open('a',encoding='utf-8') as log:
                        subprocess.Popen([sys.executable,'-m','creatorlab.auto_update','--db',str(Path(db).resolve()),'--root',str(Path(root).resolve()),'--account-id',key,'--token',token],
                            cwd=str(root),stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
            except Exception as exc:
                item.update(lease_until=0,message='后台任务未能启动：'+str(exc)[:100]);_save(db,settings)
            return True
    return False


def finish(db,aid,token,code,message,now=None):
    from creatorlab.maintenance import database_gate
    with database_gate(config_path(db)):
        settings=load(db);item=settings.get(str(aid),{})
        if item.get('token')!=token:return
        item.update(lease_until=0,last_finished=time.time() if now is None else now,message=message,paused=code in (3,4))
        if code==0:item['last_success']=item['last_finished']
        if code==2:item['next_at']=item['last_finished']+900
        _save(db,settings)


def worker(db,root,aid,token):
    item=load(db).get(str(aid),{})
    if not item.get('enabled') or item.get('token')!=token:return
    code=1;message='自动更新失败，下个周期重试；可查看采集诊断'
    try:
        from creatorlab.sync_browser import start
        code=start(db,root,account_id=aid,mode='existing')
        message={0:'本轮已更新可读取的已入库作品，未导入新作品',2:'手动采集正在运行，稍后重试',
                 3:'自动更新已暂停：需要先核对作品归属或检查采集范围',4:'自动更新已暂停：请先手动同步，完成登录或验证后恢复'}.get(code,message)
        if code==0:
            try:
                status=json.loads((Path(root)/'local'/'sync_status.json').read_text(encoding='utf-8'))
                if status.get('database')==str(Path(db).resolve()) and status.get('account_id')==aid:message=status.get('info') or message
            except (OSError,ValueError):pass
    except Exception as exc:message='自动更新遇到问题：'+str(exc)[:120]
    finally:finish(db,aid,token,code,message)


def service_loop(db,root,stop):
    # This daemon belongs to the local Streamlit server, not a browser tab.
    while not stop.wait(30):
        try:launch_due(db,root)
        except Exception:pass  # A transient file lock must not end scheduling.


def main():
    parser=argparse.ArgumentParser()
    for arg in ('db','root','account-id','token'):parser.add_argument('--'+arg,required=True)
    args=parser.parse_args();worker(args.db,args.root,int(args.account_id),args.token)


if __name__=='__main__':main()
