"""Transparent game-like visuals: scores are own-history percentiles, never industry grades."""
import json
from statistics import median
from creatorlab.hub import connect,utcnow

AXES={
 'bilibili':[('触达','views'),('喜欢','like_ratio'),('讨论','comment_ratio'),('收藏','favorite_ratio'),('传播','share_ratio'),('投币支持','coin_ratio')],
 'douyin':[('触达','views'),('喜欢','like_ratio'),('讨论','comment_ratio'),('收藏','favorite_ratio'),('传播','share_ratio'),('留住观众','completion_rate')]}


def radar_scores(df,row,min_n=5):
    # All valid history for this account/platform; age and format never silently narrow it.
    cohort=df[(df.account_id==row['account_id'])&(df.platform==row['platform'])]
    if 'analysis_window' in cohort and row.get('analysis_window'):cohort=cohort[cohort.analysis_window==row['analysis_window']]
    out=[]
    for label,key in AXES[row['platform']]:
        values=cohort[key].dropna().tolist() if key in cohort else []
        value=row.get(key)
        import pandas as pd
        usable=len(values)>=min_n and pd.notna(value)
        score=100*(sum(v<value for v in values)+.5*sum(v==value for v in values))/len(values) if usable else None
        out.append(dict(axis=label,metric=key,value=None if pd.isna(value) else value,score=score,n=len(values)))
    return out


def init_experiments(db):
    with connect(db) as con:con.execute('''CREATE TABLE IF NOT EXISTS clab_experiments(
      id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES hub_accounts(id),title TEXT NOT NULL,
      hypothesis TEXT NOT NULL,metric TEXT NOT NULL,stage TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)''')


def save_experiment(db,aid,title,hypothesis,metric):
    if not title.strip() or not hypothesis.strip():raise ValueError('请填写挑战名称和准备测试的一处改动')
    init_experiments(db)
    with connect(db) as con:return con.execute('INSERT INTO clab_experiments(account_id,title,hypothesis,metric,stage,note,created_at) VALUES(?,?,?,?,?,?,?)',(aid,title[:150],hypothesis[:1500],metric,'计划中','',utcnow())).lastrowid


def experiments(db,aid):
    init_experiments(db)
    with connect(db) as con:return [dict(r) for r in con.execute('SELECT * FROM clab_experiments WHERE account_id=? ORDER BY id DESC',(aid,))]


def update_experiment(db,eid,stage,note):
    if stage not in ('计划中','制作中','已发布待复盘','已复盘'):raise ValueError('未知状态')
    with connect(db) as con:con.execute('UPDATE clab_experiments SET stage=?,note=? WHERE id=?',(stage,note[:3000],eid))
