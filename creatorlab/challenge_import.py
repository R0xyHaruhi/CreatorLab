"""Explicit, previewed external samples, isolated from personal accounts."""
from urllib.parse import urlparse
from creatorlab.hub import _read_csv,connect,add_account,upsert_post,METRIC_FIELDS


def preview(db,data,platform):
    from creatorlab.measurements import timestamp
    rows=_read_csv(data)
    if not rows:raise ValueError('文件没有作品。')
    with connect(db) as con:
        own={r[0] for r in con.execute('SELECT handle FROM hub_accounts WHERE platform=? AND is_self=1',(platform,))}
        known={r['external_id']:r['handle'] for r in con.execute('SELECT p.external_id,a.handle FROM hub_posts p JOIN hub_accounts a ON a.id=p.account_id WHERE a.platform=? AND p.external_id IS NOT NULL',(platform,))}
    hosts={'douyin':('douyin.com',),'bilibili':('bilibili.com','b23.tv')}[platform]
    for r in rows:
        handle=(r.get('creator_id') or '').strip();r['creator_id']=handle
        if not handle or len(handle)>100:raise ValueError('每行需要有效的 creator_id，属于同一人的作品请使用同一个账号ID。')
        if handle in own:raise ValueError('参照中包含你的个人账号，不能混作同行。')
        if platform=='bilibili':
            from creatorlab.bilibili_import import parse_uid
            if parse_uid(handle)!=handle:raise ValueError('B站 creator_id 请填写规范数字UID。')
        if not r.get('external_id'):raise ValueError('每行需要 external_id，避免重复计入同一作品。')
        if r['external_id'] in known and known[r['external_id']]!=handle:raise ValueError('同一作品ID已归属于其他账号，请先核对账号归属。')
        at=timestamp(r.get('published_at'));obs=timestamp(r.get('observed_at'))
        if at is None or obs is None or obs<at:raise ValueError('发布时间和采集时间需含时分、时区，且采集不能早于发布。')
        p=urlparse(r.get('url') or '')
        if p.scheme!='https' or p.username or p.password or not any(p.hostname==h or (p.hostname or '').endswith('.'+h) for h in hosts):raise ValueError('每条参照需要对应平台的 HTTPS 作品来源链接。')
        try:views=float(str(r.get('views') or 0).replace(',','').replace('，',''))
        except ValueError:raise ValueError('参照播放量需填写精确数字，不能把“万”等缩略显示当作精确值。')
        if views<=0:raise ValueError('参照作品需要真实、正数的播放量；未知不能填写0。')
        if (r.get('media_format') or 'video') not in ('video','image'):raise ValueError('media_format 只能是 video 或 image。')
    return rows


def commit(db,data,platform,pair):
    from creatorlab.genres import set_genre,valid_genre
    from creatorlab.work_formats import save_format
    from creatorlab.maintenance import database_gate,backup_database
    from creatorlab.hub import _number
    from contextlib import closing
    import sqlite3
    if not valid_genre(platform,*pair):raise ValueError('请选择当前平台的有效赛道。')
    with database_gate(db):
        rows=preview(db,data,platform);backup=backup_database(db,'before-challenge-reference')
        try:
            for r in rows:
                with connect(db) as con:old=con.execute('SELECT id FROM hub_accounts WHERE platform=? AND handle=?',(platform,r['creator_id'])).fetchone()
                aid=old['id'] if old else add_account(db,platform,r['creator_id'],'对标 · '+r['creator_id'])
                with connect(db) as con:con.execute('UPDATE hub_accounts SET is_self=0 WHERE id=?',(aid,))
                pid=upsert_post(db,aid,r['title'],r['external_id'],r['published_at'],r['url'],
                    {k:_number(r.get(k),k) for k in METRIC_FIELDS},source='csv',source_ref='用户核对的外部参照CSV',visibility='public',observed_at=r['observed_at'])
                set_genre(db,pid,*pair,evidence='用户确认的外部CSV样本；来源见作品链接')
                save_format(db,pid,r.get('media_format') or 'video')
        except Exception:
            with closing(sqlite3.connect(str(backup))) as source,closing(sqlite3.connect(str(db))) as target:source.backup(target)
            raise
    return len(rows)
