from datetime import datetime, timezone, timedelta
import numpy as np
from creatorlab.decision import (prepare, compare, summarize, bootstrap_diff, describe, title_features, MIN_GROUP)

NOW=datetime(2026,10,28,tzinfo=timezone.utc)
CN=timezone(timedelta(hours=8))


def make(n,hour_fn,title_fn=lambda i:f'作品{i}',views_fn=lambda i:1000,acct='A'):
    out=[]
    for i in range(n):
        t=datetime(2026,6,1,tzinfo=CN)+timedelta(days=i*2,hours=hour_fn(i))
        out.append({'platform':'bilibili','account_name':acct,'title':title_fn(i),'published_at':t.isoformat(),'views':views_fn(i)})
    return out


def test_prepare_filters_and_reports_why():
    rows=make(10,lambda i:12)+[
      {'platform':'bilibili','account_name':'A','title':'无播放','published_at':'2026-06-01T10:00:00+08:00','views':None},
      {'platform':'bilibili','account_name':'A','title':'零播放','published_at':'2026-06-01T10:00:00+08:00','views':0},
      {'platform':'bilibili','account_name':'A','title':'无时间','published_at':None,'views':5},
      {'platform':'bilibili','account_name':'A','title':'太新','published_at':(NOW-timedelta(days=2)).isoformat(),'views':5}]
    items,s=prepare(rows,NOW)
    assert (s['no_views'],s['no_time'],s['too_new'],s['used'])==(2,1,1,10)


def test_small_accounts_are_not_normalised():
    items,s=prepare(make(5,lambda i:12),NOW)
    assert items==[] and s['small_account']==5


def test_clear_hour_effect_is_found_and_flat_data_is_not():
    # evening posts get ~3x views
    rows=make(40,lambda i:20 if i%2 else 9,views_fn=lambda i:3000+i if i%2 else 1000+i)
    r=summarize(rows,NOW)
    ev=[h for h in r['timing']['hours'] if h['label'].startswith('晚间')][0]
    assert ev['verdict']=='better' and ev['lift']>2
    assert any('晚间' in f for f in r['findings'])
    flat=summarize(make(40,lambda i:20 if i%2 else 9,views_fn=lambda i:1000+(i*37)%11),NOW)
    assert flat['findings']==[]          # no invented pattern in noise


def test_too_few_in_group_says_nothing():
    rows=make(30,lambda i:20 if i<3 else 9,views_fn=lambda i:9000 if i<3 else 1000)
    r=summarize(rows,NOW)
    ev=[h for h in r['timing']['hours'] if h['label'].startswith('晚间')][0]
    assert ev['n']==3 and ev['verdict']=='few' and describe(ev) is None


def test_title_feature_detected():
    rows=make(40,lambda i:12,title_fn=lambda i:f'{i}个技巧' if i%2 else '随手记',views_fn=lambda i:2500 if i%2 else 1000)
    feats={f['label']:f for f in summarize(rows,NOW)['titles']}
    assert feats['含数字']['verdict']=='better'


def test_not_ready_with_little_data():
    assert summarize(make(9,lambda i:12),NOW)['ready'] is False


def test_bootstrap_is_deterministic_and_sign_correct():
    a=[3,3.2,2.9,3.1,3.3,3.0,2.8];b=[1,1.1,0.9,1.2,1.0,0.8,1.05]
    d1=bootstrap_diff(a,b);d2=bootstrap_diff(a,b)
    assert d1==d2 and d1[0]>0 and d1[1]>0
