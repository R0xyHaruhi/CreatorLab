"""Explicitly selected Bilibili learning reference. Keep it out of personal metrics."""
import argparse
from creatorlab.hub import init_hub,connect,add_account
from creatorlab.bilibili_import import parse_uid,run


def prepare_reference(db,uid):
    uid=parse_uid(uid);init_hub(db)
    with connect(db) as con:old=con.execute("SELECT id,is_self FROM hub_accounts WHERE platform='bilibili' AND handle=?",(uid,)).fetchone()
    if old and old['is_self']:raise ValueError('该UID已是你的个人账号，不转为学习参照。')
    aid=old['id'] if old else add_account(db,'bilibili',uid,'学习参照 · '+uid)
    with connect(db) as con:con.execute('UPDATE hub_accounts SET is_self=0 WHERE id=?',(aid,))
    return uid


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--root',required=True);p.add_argument('--uid',required=True)
    args=p.parse_args();uid=prepare_reference(args.db,args.uid)
    raise SystemExit(run(args.db,args.root,uid,50,False))

if __name__=='__main__':main()
