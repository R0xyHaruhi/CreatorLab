"""SQLite persistence. No external database required."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS videos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL, role TEXT NOT NULL, format TEXT NOT NULL,
 hook TEXT NOT NULL, duration_sec REAL NOT NULL CHECK(duration_sec > 0),
 publish_hour INTEGER NOT NULL CHECK(publish_hour BETWEEN 0 AND 23),
 views INTEGER NOT NULL DEFAULT 0 CHECK(views >= 0),
 likes INTEGER NOT NULL DEFAULT 0 CHECK(likes >= 0),
 comments INTEGER NOT NULL DEFAULT 0 CHECK(comments >= 0),
 shares INTEGER NOT NULL DEFAULT 0 CHECK(shares >= 0),
 new_followers INTEGER NOT NULL DEFAULT 0 CHECK(new_followers >= 0),
 published_at TEXT, notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS experiments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL, hypothesis TEXT NOT NULL, control TEXT NOT NULL,
 variant TEXT NOT NULL, metric TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned'
 CHECK(status IN ('planned','running','completed','cancelled')),
 result TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback (
 id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id INTEGER NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('accept','modify','reject')),
 reason TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);
'''

@contextmanager
def connection(path):
    from creatorlab.maintenance import database_gate
    with database_gate(path):
        with _connection(path) as con:yield con


@contextmanager
def _connection(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS creator_profiles (
 id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL CHECK(platform IN ('tiktok','douyin')),
 handle TEXT NOT NULL, niche TEXT NOT NULL DEFAULT '', audience TEXT NOT NULL DEFAULT '',
 goals TEXT NOT NULL DEFAULT '', constraints TEXT NOT NULL DEFAULT '',
 UNIQUE(platform,handle)
);
CREATE TABLE IF NOT EXISTS content_plans (
 id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL CHECK(platform IN ('tiktok','douyin')),
 account_handle TEXT NOT NULL, planned_date TEXT NOT NULL, topic TEXT NOT NULL,
 hook TEXT NOT NULL DEFAULT '', format TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'idea'
 CHECK(status IN ('idea','planned','filmed','published')), notes TEXT NOT NULL DEFAULT ''
);
"""

def upsert_profile(path, platform, handle, niche, audience, goals, constraints):
    with connection(path) as con:
        con.execute("""INSERT INTO creator_profiles(platform,handle,niche,audience,goals,constraints)
        VALUES(?,?,?,?,?,?) ON CONFLICT(platform,handle) DO UPDATE SET niche=excluded.niche,
        audience=excluded.audience,goals=excluded.goals,constraints=excluded.constraints""",
        (platform,handle,niche,audience,goals,constraints))

def add_plan(path, platform, account_handle, planned_date, topic, hook, format, notes):
    with connection(path) as con:
        con.execute("""INSERT INTO content_plans(platform,account_handle,planned_date,topic,hook,format,notes)
        VALUES(?,?,?,?,?,?,?)""",(platform,account_handle,planned_date,topic,hook,format,notes))

def set_plan_status(path, plan_id, status):
    if status not in ('idea','planned','filmed','published'): raise ValueError('Invalid status')
    with connection(path) as con:
        con.execute('UPDATE content_plans SET status=? WHERE id=?',(status,plan_id))

def init_db(path):
    with connection(path) as con:
        con.executescript(SCHEMA)
        cols = {r['name'] for r in con.execute('PRAGMA table_info(videos)')}
        if 'platform' not in cols:
            con.execute("ALTER TABLE videos ADD COLUMN platform TEXT NOT NULL DEFAULT 'unassigned'")
        con.executescript(EXTRA_SCHEMA)

def list_rows(path, table):
    if table not in ('videos','experiments','feedback','creator_profiles','content_plans'):
        raise ValueError('Unsupported table')
    with connection(path) as con:
        return [dict(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY id DESC')]

def add_video(path, values):
    keys = ['title','role','format','hook','duration_sec','publish_hour','views','likes','comments','shares','new_followers','published_at','notes','platform']
    data = {k: values.get(k) for k in keys}
    data['platform'] = data['platform'] or 'unassigned'
    if data['platform'] not in ('unassigned','tiktok','douyin'): raise ValueError('Invalid platform')
    with connection(path) as con:
        cur = con.execute(f"INSERT INTO videos ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(data.values()))
        return cur.lastrowid

def update_video(path, video_id, values):
    keys = ['title','role','format','hook','duration_sec','publish_hour','views','likes','comments','shares','new_followers','published_at','notes','platform']
    updates = {k:v for k,v in values.items() if k in keys}
    if 'platform' in updates and updates['platform'] not in ('unassigned','tiktok','douyin'): raise ValueError('Invalid platform')
    if not updates:
        return False
    with connection(path) as con:
        cur = con.execute('UPDATE videos SET '+', '.join(f'{k}=?' for k in updates)+' WHERE id=?', (*updates.values(), video_id))
        return cur.rowcount > 0

def delete_video(path, video_id):
    with connection(path) as con:
        return con.execute('DELETE FROM videos WHERE id=?', (video_id,)).rowcount > 0

def add_experiment(path, title, hypothesis, control, variant, metric):
    with connection(path) as con:
        cur = con.execute('INSERT INTO experiments (title,hypothesis,control,variant,metric) VALUES (?,?,?,?,?)', (title,hypothesis,control,variant,metric))
        return cur.lastrowid

def update_experiment(path, experiment_id, status, result):
    with connection(path) as con:
        return con.execute('UPDATE experiments SET status=?, result=? WHERE id=?', (status,result,experiment_id)).rowcount > 0

def add_feedback(path, experiment_id, decision, reason):
    with connection(path) as con:
        con.execute('INSERT INTO feedback (experiment_id,decision,reason) VALUES (?,?,?)',(experiment_id,decision,reason))

def import_videos(path, df):
    """Import validated CSV rows. Re-importing adds rows; it does not deduplicate."""
    count = 0
    for _, row in df.iterrows():
        d = row.to_dict()
        d['title'] = str(d.get('title') or f"{d['role']} video {count+1}")
        d['published_at'] = str(d.get('published_at') or '')
        d['notes'] = str(d.get('notes') or '')
        add_video(path, d)
        count += 1
    return count


LINK_SCHEMA = """
CREATE TABLE IF NOT EXISTS linked_videos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 platform TEXT NOT NULL CHECK(platform IN ('tiktok','douyin')),
 url TEXT NOT NULL UNIQUE,
 video_id TEXT,
 display_name TEXT NOT NULL DEFAULT '',
 public_title TEXT NOT NULL DEFAULT '',
 author TEXT NOT NULL DEFAULT '',
 role TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 views INTEGER CHECK(views >= 0),
 likes INTEGER CHECK(likes >= 0),
 comments INTEGER CHECK(comments >= 0),
 shares INTEGER CHECK(shares >= 0),
 new_followers INTEGER CHECK(new_followers >= 0),
 metrics_source TEXT NOT NULL DEFAULT 'unavailable',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

def init_links(path):
    with connection(path) as con:
        con.executescript(LINK_SCHEMA)

def add_link(path, parsed, display_name='', public_title='', author='', role='', notes=''):
    init_links(path)
    with connection(path) as con:
        try:
            return con.execute("INSERT INTO linked_videos(platform,url,video_id,display_name,public_title,author,role,notes) VALUES(?,?,?,?,?,?,?,?)",(parsed['platform'],parsed['url'],parsed['video_id'],display_name,public_title,author,role,notes)).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError('这个作品已经添加过了 / Video already saved') from exc

def list_links(path):
    init_links(path)
    with connection(path) as con:
        return [dict(row) for row in con.execute('SELECT * FROM linked_videos ORDER BY id DESC')]

def update_link(path, item_id, values):
    allowed = {'display_name','role','notes','views','likes','comments','shares','new_followers'}
    updates = {k:v for k,v in values.items() if k in allowed}
    if not updates: return False
    if any(v is not None and (not isinstance(v,int) or v < 0) for k,v in updates.items() if k in {'views','likes','comments','shares','new_followers'}):
        raise ValueError('Metrics must be nonnegative integers or unknown')
    if any(k in updates for k in ('views','likes','comments','shares','new_followers')):
        updates['metrics_source'] = 'manual'
    with connection(path) as con:
        cur=con.execute('UPDATE linked_videos SET '+', '.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),item_id))
        return cur.rowcount > 0

def delete_link(path, item_id):
    with connection(path) as con:
        return con.execute('DELETE FROM linked_videos WHERE id=?',(item_id,)).rowcount > 0
