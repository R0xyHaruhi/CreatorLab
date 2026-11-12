"""Additive workflow documents, kept beside (never inside) the personal database."""
import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path
from creatorlab.hub import connect, utcnow

KINDS={'scope','reference','refresh','plan','experiment_detail','lesson','inspection'}


def store_path(db):
    path=Path(db).resolve()
    return path.with_name(path.stem+'.workflow.sqlite3')


def check_owner(db,aid,platform):
    if platform not in ('douyin','bilibili'):raise ValueError('不支持的平台')
    with connect(db) as con:
        row=con.execute('SELECT platform,is_self FROM hub_accounts WHERE id=?',(aid,)).fetchone()
    if not row or row['platform']!=platform or not row['is_self']:
        raise ValueError('账号与平台不匹配，不能保存到其他账号')


@contextmanager
def _connection(db,write=False):
    path=store_path(db)
    if write:path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(str(path) if write else path.as_uri()+'?mode=ro',
                                uri=not write,timeout=15)) as con:
        con.row_factory=sqlite3.Row
        with con:
            if write:
                con.execute('''CREATE TABLE IF NOT EXISTS documents(
                    kind TEXT,account_id INTEGER,platform TEXT,record_key TEXT,
                    payload TEXT NOT NULL,updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind,account_id,platform,record_key))''')
            yield con


def put(db,kind,aid,platform,key,payload):
    if kind not in KINDS:raise ValueError('未知工作流类型')
    check_owner(db,aid,platform)
    value=json.dumps(payload,ensure_ascii=False,allow_nan=False)
    if len(value)>2_000_000:raise ValueError('记录过大，请缩小范围')
    with _connection(db,True) as con:
        con.execute('''INSERT INTO documents VALUES(?,?,?,?,?,?)
            ON CONFLICT(kind,account_id,platform,record_key) DO UPDATE SET
            payload=excluded.payload,updated_at=excluded.updated_at''',
            (kind,aid,platform,str(key),value,utcnow()))
    return str(key)


def documents(db,kind,aid,platform,limit=200):
    if kind not in KINDS:raise ValueError('未知工作流类型')
    check_owner(db,aid,platform)
    if not store_path(db).exists():return []
    with _connection(db) as con:
        rows=con.execute('''SELECT record_key,payload,updated_at FROM documents
            WHERE kind=? AND account_id=? AND platform=? ORDER BY updated_at DESC,record_key
            LIMIT ?''',(kind,aid,platform,min(max(int(limit),1),10000))).fetchall()
    return [dict(key=r['record_key'],updated_at=r['updated_at'],data=json.loads(r['payload'])) for r in rows]


def get(db,kind,aid,platform,key):
    check_owner(db,aid,platform)
    if kind not in KINDS:raise ValueError('未知工作流类型')
    if not store_path(db).exists():return None
    with _connection(db) as con:
        row=con.execute('SELECT payload FROM documents WHERE kind=? AND account_id=? AND platform=? AND record_key=?',
                        (kind,aid,platform,str(key))).fetchone()
    return json.loads(row['payload']) if row else None
