"""Quarantine a capture until its exact destination account has been reviewed."""
import json
import uuid
from datetime import datetime,timezone
from creatorlab.hub import connect,METRIC_FIELDS,upsert_post,utcnow


def init_captures(db):
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS clab_dy_runs(
          id TEXT PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES hub_accounts(id),
          state TEXT NOT NULL,created_at TEXT NOT NULL,owner_key TEXT)''')
        con.execute('''CREATE TABLE IF NOT EXISTS clab_dy_events(
          id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES clab_dy_runs(id),
          video_id TEXT NOT NULL,observed_at TEXT NOT NULL,row_json TEXT NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS clab_dy_owners(
          account_id INTEGER PRIMARY KEY REFERENCES hub_accounts(id),owner_json TEXT NOT NULL)''')


def create_capture(db,account_id):
    init_captures(db)
    with connect(db) as con:
        account=con.execute("SELECT * FROM hub_accounts WHERE id=? AND platform='douyin' AND is_self=1",(account_id,)).fetchone()
        if not account:raise ValueError('请先选择一个个人抖音账号作为本次归属')
        run_id=uuid.uuid4().hex
        con.execute('INSERT INTO clab_dy_runs VALUES(?,?,?, ?,NULL)',(run_id,account_id,'collecting',utcnow()))
    return run_id


def stage_rows(db,run_id,rows,observed_at=None):
    from creatorlab.hub import _number
    from creatorlab.measurements import timestamp
    at=timestamp(observed_at or utcnow())
    if at is None or at>datetime.now(timezone.utc):raise ValueError('采集时间不合法')
    safe=[]
    for row in rows:
        clean={k:_number(row.get(k),k) for k in METRIC_FIELDS}
        from creatorlab.image_reading import FIELDS,valid
        clean.update({k:row[k] for k in FIELDS if valid(k,row.get(k))})
        clean.update({k:row.get(k) for k in ('video_id','title','published_at','url','cover_url','visibility','owner_key','media_format')})
        if not str(clean.get('video_id') or '').isdigit() or not str(clean.get('title') or '').strip():raise ValueError('采集记录缺少作品标识')
        safe.append(clean)
    owners={}
    for row in safe:
        if row.get('owner_key'):
            key=str(row['owner_key']);kind=key.split(':',1)[0] if key.startswith(('uid:','sec:')) else 'raw'
            if kind in owners and owners[kind]!=key:raise ValueError('这一批出现多个作者标识，已暂停保存，请核对登录账号')
            owners[kind]=key
    with connect(db) as con:
        run=con.execute('SELECT * FROM clab_dy_runs WHERE id=?',(run_id,)).fetchone()
        if not run or run['state']!='collecting':raise ValueError('这次采集已结束，不能追加记录')
        bound=json.loads(run['owner_key']) if run['owner_key'] else {}
        if any(kind in bound and bound[kind]!=value for kind,value in owners.items()):raise ValueError('采集期间账号发生变化，已暂停保存')
        if owners:
            bound.update(owners);con.execute('UPDATE clab_dy_runs SET owner_key=? WHERE id=?',(json.dumps(bound),run_id))
        con.executemany('INSERT INTO clab_dy_events(run_id,video_id,observed_at,row_json) VALUES(?,?,?,?)',[(run_id,r['video_id'],at.isoformat(),json.dumps(r,ensure_ascii=False)) for r in safe])
    return len(safe)


def finish_capture(db,run_id):
    with connect(db) as con:
        n=con.execute('SELECT count(*) FROM clab_dy_events WHERE run_id=?',(run_id,)).fetchone()[0]
        con.execute("UPDATE clab_dy_runs SET state=? WHERE id=? AND state='collecting'",('review' if n else 'empty',run_id))
    return n


def pending_captures(db):
    init_captures(db)
    with connect(db) as con:
        runs=[dict(r) for r in con.execute("SELECT r.*,a.display_name FROM clab_dy_runs r JOIN hub_accounts a ON a.id=r.account_id WHERE r.state='review' ORDER BY r.created_at DESC")]
        for run in runs:
            events=con.execute('SELECT row_json FROM clab_dy_events WHERE run_id=? ORDER BY id',(run['id'],)).fetchall()
            seen={}
            for e in events:
                row=json.loads(e['row_json']);old=seen.get(row['video_id'],{})
                seen[row['video_id']]={**old,**{k:v for k,v in row.items() if v is not None and v!=''}}
            known={r[0] for r in con.execute('SELECT external_id FROM hub_posts WHERE account_id=?',(run['account_id'],))}
            run['new_count']=len(set(seen)-known)
            run['count']=len(seen);run['preview']=sorted(seen.values(),key=lambda r:r['video_id'] in known)[:5]
            run['_signature']=capture_signature(run,seen)
    # Compare all IDs, never just the preview. Repeated measurements of the
    # same works share one confirmation; every original event stays intact.
    grouped={}
    for run in runs:
        signature=run.pop('_signature')
        if signature in grouped:grouped[signature]['duplicate_ids'].append(run['id'])
        else:
            run['duplicate_ids']=[];grouped[signature]=run
    return list(grouped.values())


def capture_signature(run,rows):
    return json.dumps([run['account_id'],json.loads(run.get('owner_key') or '{}'),
                       sorted(rows)],sort_keys=True,ensure_ascii=False)


def recover_interrupted(db):
    init_captures(db)
    with connect(db) as con:
        con.execute("UPDATE clab_dy_runs SET state=CASE WHEN EXISTS(SELECT 1 FROM clab_dy_events e WHERE e.run_id=clab_dy_runs.id) THEN 'review' ELSE 'empty' END WHERE state='collecting'")


def known_capture_ids(con,run):
    """Already reviewed exact IDs can be refreshed without inventing an author."""
    reviewed={e[0] for e in con.execute("SELECT DISTINCT e.video_id FROM clab_dy_events e JOIN clab_dy_runs r ON r.id=e.run_id WHERE r.account_id=? AND r.state='committed'",(run['account_id'],))}
    if not reviewed:return False
    ids={e[0] for e in con.execute('SELECT DISTINCT video_id FROM clab_dy_events WHERE run_id=?',(run['id'],))}
    known={}
    for p in con.execute("SELECT p.external_id,p.account_id FROM hub_posts p JOIN hub_accounts a ON a.id=p.account_id WHERE a.platform='douyin'"):
        known.setdefault(p['external_id'],set()).add(p['account_id'])
    return bool(ids) and ids.issubset(reviewed) and all(known.get(vid)=={run['account_id']} for vid in ids)


def auto_commit_capture(db,run_id,account_id):
    """Only reuse an explicit prior review with a matching author on every work."""
    init_captures(db)
    with connect(db) as con:
        run=con.execute('SELECT * FROM clab_dy_runs WHERE id=?',(run_id,)).fetchone()
        binding=con.execute('SELECT owner_json FROM clab_dy_owners WHERE account_id=?',(account_id,)).fetchone()
        if not run or run['account_id']!=account_id or run['state']!='review':return 0
        captured=json.loads(run['owner_key'] or '{}')
        # Refresh only existing works whose IDs were explicitly reviewed before.
        # A single unknown or ambiguous ID keeps the entire batch for review.
        if not captured:
            if not known_capture_ids(con,run):return 0
            mode='known_ids'
        else:mode='author'
        owners=json.loads(binding['owner_json']) if binding else {}
        if mode=='known_ids':pass
        elif not owners or not captured or any(k in owners and owners[k]!=v for k,v in captured.items()):return 0
        latest={}
        for event in con.execute('SELECT video_id,row_json FROM clab_dy_events WHERE run_id=? ORDER BY id',(run_id,)):
            row=json.loads(event['row_json'])
            # Do not let an earlier author hide a later identity-less response.
            latest[event['video_id']]=row.get('owner_key')
        if not latest:return 0
        if mode=='author' and any(not owner or owner not in owners.values() for owner in latest.values()):return 0
    return commit_capture(db,run_id,account_id,require_bound=mode=='author',require_known=mode=='known_ids')


def commit_capture(db,run_id,account_id,require_bound=False,require_known=False):
    from creatorlab.maintenance import database_gate,backup_database
    with database_gate(db):
        with connect(db) as con:
            run=con.execute('SELECT * FROM clab_dy_runs WHERE id=?',(run_id,)).fetchone()
            if not run or run['account_id']!=account_id:raise ValueError('采集结果与所选账号不一致')
            if run['state']=='committed':return 0
            if run['state']!='review':raise ValueError('请等待采集结束后再核对入库')
            events=con.execute('SELECT * FROM clab_dy_events WHERE run_id=? ORDER BY id',(run_id,)).fetchall()
            owners=json.loads(run['owner_key'] or '{}')
            binding=con.execute('SELECT owner_json FROM clab_dy_owners WHERE account_id=?',(account_id,)).fetchone()
            bound=json.loads(binding['owner_json']) if binding else {}
            if any(k in bound and bound[k]!=v for k,v in owners.items()):raise ValueError('作者标识与此前确认的账号不同，请选择正确账号后重新采集')
            if require_bound and (not bound or not owners or not any(bound.get(k)==v for k,v in owners.items())):raise ValueError('作者归属尚未确认，请先核对本批作品')
            if require_known and not known_capture_ids(con,run):raise ValueError('作品ID归属不明确，请核对本批作品')
        group=next((r for r in pending_captures(db) if run_id in [r['id'],*r['duplicate_ids']]),None)
        duplicates=[i for i in [group['id'],*group['duplicate_ids']] if i!=run_id] if group else []
        if duplicates:
            with connect(db) as con:
                events=sorted([*events,*[e for other_id in duplicates for e in con.execute(
                    'SELECT * FROM clab_dy_events WHERE run_id=?',(other_id,)).fetchall()]],
                    key=lambda e:(e['observed_at'],e['id']))
        backup=backup_database(db,'before-capture-import')
        try:
            for e in events:
                row=json.loads(e['row_json'])
                pid=upsert_post(db,account_id,row['title'],row['video_id'],row.get('published_at'),row.get('url'),
                  metrics={k:row.get(k) for k in METRIC_FIELDS},source='douyin_creator_center',source_ref='capture:'+e['run_id'],
                  cover_url=row.get('cover_url'),visibility=row.get('visibility'),observed_at=e['observed_at'])
                from creatorlab.work_formats import save_format
                save_format(db,pid,row.get('media_format'))
                from creatorlab.image_reading import save
                save(db,pid,row,observed_at=e['observed_at'])
            with connect(db) as con:
                con.execute("UPDATE clab_dy_runs SET state='committed' WHERE id=?",(run_id,))
                # Preserve duplicate events, but do not ask to confirm them again.
                con.executemany("UPDATE clab_dy_runs SET state='superseded' WHERE id=? AND state='review'",[(i,) for i in duplicates])
                if owners:
                    con.execute('INSERT INTO clab_dy_owners VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET owner_json=excluded.owner_json',
                                (account_id,json.dumps({**bound,**owners})))
        except Exception:
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(str(backup))) as source,closing(sqlite3.connect(str(db))) as target:source.backup(target)
            raise
        return len({e['video_id'] for e in events})
