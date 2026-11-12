"""Public content evidence, separate from performance measurements."""
import json
from creatorlab.hub import connect,utcnow


def init_metadata(db):
    with connect(db) as con:con.execute('''CREATE TABLE IF NOT EXISTS clab_bili_metadata(
      post_id INTEGER PRIMARY KEY,partition_name TEXT NOT NULL,description TEXT NOT NULL,
      tags_json TEXT NOT NULL,recorded_at TEXT NOT NULL)''')


def save_metadata(db,pid,row):
    partition=str(row.get('partition_name') or '')[:100]
    description=str(row.get('description') or '')[:3000]
    tags=row.get('tags') or []
    if not partition and not description and not tags:return
    init_metadata(db)
    with connect(db) as con:
        old=con.execute('SELECT * FROM clab_bili_metadata WHERE post_id=?',(pid,)).fetchone()
        partition=partition or (old['partition_name'] if old else '')
        description=description or (old['description'] if old else '')
        tags=tags or (json.loads(old['tags_json']) if old else [])
        con.execute('INSERT OR REPLACE INTO clab_bili_metadata VALUES(?,?,?,?,?)',(pid,partition,description,json.dumps(tags,ensure_ascii=False),utcnow()))
    from creatorlab.genres import TAXONOMY,set_genre,suggest_title
    exact=[(m,n) for m,names in TAXONOMY['bilibili'].items() for n in names if n==partition]
    suggestion=suggest_title('bilibili',' '.join([partition]+tags))
    if exact or suggestion:
        pair=exact[0] if exact else (suggestion['major'],suggestion['minor'])
        set_genre(db,pid,*pair,origin='platform_metadata',confidence=.8,evidence='平台分区：'+partition+'；标签：'+'、'.join(tags))


def metadata_rows(db):
    init_metadata(db)
    with connect(db) as con:rows=con.execute('SELECT * FROM clab_bili_metadata').fetchall()
    return {r['post_id']:{'bili_partition':r['partition_name'],'bili_description':r['description'],'bili_tags':json.loads(r['tags_json'])} for r in rows}
