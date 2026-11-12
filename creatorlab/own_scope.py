"""Explicit reference scope for own-work rankings; never infer a track."""
from creatorlab.hub import eligible


def track_key(row):
    genre=row.get('genre')
    if not isinstance(genre,dict) or genre.get('origin') not in ('manual','platform_metadata'):return None
    if not genre.get('major') or not genre.get('minor'):return None
    return genre['major'],genre['minor']


def scope_key(row,scope='all'):
    window=row.get('analysis_window')
    window=window if isinstance(window,str) and window else '当前累计'
    base=(row.get('account_id'),row.get('platform'),window,row.get('demo') is True)
    if scope=='track':return base+(track_key(row) or ('未分类',row['id']),)
    if scope!='all':raise ValueError('未知自己的作品参照范围')
    return base


def scope_label(row,scope='all'):
    if scope=='all':return '全部作品'
    pair=track_key(row)
    return '同赛道：'+' / '.join(pair) if pair else '同赛道：当前作品未分类'


def references(rows,target,scope='all'):
    key=scope_key(target,scope)
    return [r for r in eligible(rows) if r['id']!=target['id'] and scope_key(r,scope)==key]
