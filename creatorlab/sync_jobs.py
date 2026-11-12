"""Per-item retry queue and an honest estimate based on work already completed."""
import json
from datetime import datetime,timezone
from creatorlab.hub import connect,latest_posts,utcnow
from creatorlab.covers import cached_cover
from creatorlab.measurements import due_windows

FIELDS=('views','likes','comments','favorites','shares','coins','danmaku')


def init_jobs(db):
    with connect(db) as con:con.execute('''CREATE TABLE IF NOT EXISTS clab_sync_items(
       platform TEXT NOT NULL,uid TEXT NOT NULL,external_id TEXT NOT NULL,
       attempts INTEGER NOT NULL,missing_json TEXT NOT NULL,error TEXT NOT NULL,updated_at TEXT NOT NULL,
       PRIMARY KEY(platform,uid,external_id))''')


def missing(row,db):
    fields=[k for k in FIELDS if row.get(k) is None]
    from creatorlab.measurements import timestamp
    if not timestamp(row.get('published_at')):fields.append('published_at')
    if not row.get('cover_url') and not cached_cover(db,'bilibili',row.get('external_id')):fields.append('cover_url')
    if not cached_cover(db,'bilibili',row.get('external_id')):fields.append('cover')
    return fields


def retry_rows(db,uid):
    rows=[r for r in latest_posts(db,include_references=True) if r['platform']=='bilibili' and r['handle']==uid]
    due={r['post_id'] for r in due_windows(db,rows)}
    failed={r['external_id'] for r in failures(db,uid)}
    return [r for r in rows if r.get('visibility') not in ('private','unlisted','deleted') and (missing(r,db) or r['id'] in due or r['external_id'] in failed)]


def record_attempt(db,uid,bvid,missing_fields,error='',increment=True):
    init_jobs(db)
    with connect(db) as con:con.execute('''INSERT INTO clab_sync_items VALUES('bilibili',?,?,1,?,?,?)
      ON CONFLICT(platform,uid,external_id) DO UPDATE SET attempts=attempts+?,
      missing_json=excluded.missing_json,error=excluded.error,updated_at=excluded.updated_at''',(uid,bvid,json.dumps(missing_fields),error[:300],utcnow(),int(increment)))


def failures(db,uid):
    init_jobs(db)
    with connect(db) as con:rows=[dict(r) for r in con.execute("SELECT * FROM clab_sync_items WHERE uid=? AND platform='bilibili' ORDER BY updated_at DESC",(uid,))]
    for row in rows:row['missing']=json.loads(row.pop('missing_json'))
    return [r for r in rows if r['missing']]


def estimate(elapsed,done,total):
    if done<2:return None
    return max(0,int(elapsed/done*(total-done)))
