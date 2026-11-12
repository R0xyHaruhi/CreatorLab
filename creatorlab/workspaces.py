"""Persist interface mode without changing or destroying existing video data."""
from .storage import connection

def init_workspace(path):
    with connection(path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS workspace_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

def get_mode(path):
    init_workspace(path)
    with connection(path) as con:
        row=con.execute("SELECT value FROM workspace_settings WHERE key='mode'").fetchone()
        return row['value'] if row and row['value'] in ('creator','team') else 'creator'

def set_mode(path,mode):
    if mode not in ('creator','team'):raise ValueError('Invalid mode')
    init_workspace(path)
    with connection(path) as con:
        con.execute("INSERT INTO workspace_settings(key,value) VALUES('mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(mode,))
