"""Posting-time and title insights that say how sure they are.

Comparisons stay within one account, platform, format and observation scope.
Bootstrap intervals describe uncertainty in this historical sample, not causation
or corrected significance across the many exploratory comparisons.
"""
import math
import re
from datetime import datetime, timezone, timedelta
import numpy as np

CN = timezone(timedelta(hours=8))
MIN_ACCOUNT_POSTS = 8      # fewer works: the account median is too unstable to normalise by
MIN_GROUP = 6              # works needed on each side of a comparison
HOUR_BUCKETS = (('凌晨 0–5点', 0, 5), ('早间 6–8点', 6, 8), ('上午 9–11点', 9, 11), ('午间 12–13点', 12, 13),
                ('下午 14–17点', 14, 17), ('晚间 18–20点', 18, 20), ('深夜 21–23点', 21, 23))
WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')
EMOJI = re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF]')


def _time(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=CN)   # date-only/naive values are read as China time
    return t.astimezone(CN)


def _has_clock_time(value):
    return bool(value) and ('T' in str(value) or ':' in str(value))


def prepare(rows, now=None, mature_days=7):
    """Return (items, stats). Each item: dict(title, t, rel, has_clock, account_key, prev_gap_days)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('比较时间必须包含时区')
    stats = {'input': len(rows), 'no_views': 0, 'no_time': 0, 'too_new': 0, 'small_account': 0, 'used': 0, 'excluded':0, 'invalid':0}
    groups = {}
    for r in rows:
        if r.get('visibility') in ('private','unlisted','deleted') or 'views' in r.get('approx_fields',[]):
            stats['excluded']+=1;continue
        views = r.get('views')
        if isinstance(views,bool) or views is not None and (not isinstance(views,(int,float)) or not math.isfinite(views)):
            stats['invalid']+=1;continue
        t = _time(r.get('published_at'))
        if views is None or views <= 0:
            stats['no_views'] += 1
            continue
        if t is None:
            stats['no_time'] += 1
            continue
        if (not r.get('analysis_window') or r['analysis_window']=='当前累计') and now - t < timedelta(days=mature_days):
            stats['too_new'] += 1
            continue
        key = (r.get('platform'), r.get('account_id',r.get('account_name') or r.get('account')),r.get('media_format','unknown'),r.get('analysis_window') or r.get('age_band','unknown'))
        groups.setdefault(key, []).append({'title': str(r.get('title') or ''), 't': t, 'views': float(views),
                                           'has_clock': _has_clock_time(r.get('published_at')), 'account_key': key})
    items = []
    for key, g in groups.items():
        if len(g) < MIN_ACCOUNT_POSTS:
            stats['small_account'] += len(g)
            continue
        med = float(np.median([x['views'] for x in g]))
        g.sort(key=lambda x: x['t'])
        for i, x in enumerate(g):
            x['rel'] = x['views'] / med
            x['prev_gap_days'] = (x['t'] - g[i - 1]['t']).total_seconds() / 86400 if i else None
            items.append(x)
    stats['used'] = len(items)
    return items, stats


def bootstrap_diff(a, b, n=1500, seed=11):
    """Median(log a) - median(log b) with a 90% bootstrap interval. Returns (diff, lo, hi)."""
    a,b=np.asarray(a,float),np.asarray(b,float)
    if not len(a) or not len(b) or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)) or np.any(a<=0) or np.any(b<=0):raise ValueError('比较需要有限正数')
    la,lb=a,b
    rng = np.random.default_rng(seed)
    da = np.log(np.concatenate([np.median(rng.choice(la,(min(100,n-i),len(la))),axis=1) for i in range(0,n,100)]))
    db = np.log(np.concatenate([np.median(rng.choice(lb,(min(100,n-i),len(lb))),axis=1) for i in range(0,n,100)]))
    d = da - db
    return float(np.log(np.median(la))-np.log(np.median(lb))), float(np.percentile(d, 5)), float(np.percentile(d, 95))


def compare(group_rel, rest_rel):
    """Describe one group against everything else. `verdict` is one of better / worse / unclear / few."""
    out = {'n': len(group_rel), 'n_rest': len(rest_rel), 'median': None, 'lift': None, 'verdict': 'few'}
    if len(group_rel) >= 1:
        out['median'] = float(np.median(group_rel))
    if len(group_rel) < MIN_GROUP or len(rest_rel) < MIN_GROUP:
        return out
    diff, lo, hi = bootstrap_diff(group_rel, rest_rel)
    out['lift'] = math.exp(diff)
    out['lift_lo'], out['lift_hi'] = math.exp(lo), math.exp(hi)
    out['verdict'] = 'better' if lo > 0 else 'worse' if hi < 0 else 'unclear'
    return out


def _split(items, predicate):
    yes = [x['rel'] for x in items if predicate(x)]
    no = [x['rel'] for x in items if not predicate(x)]
    return compare(yes, no)


def timing(items):
    clock = [x for x in items if x['has_clock']]
    hours = [{'label': label, **_split(clock, lambda x, lo=lo, hi=hi: lo <= x['t'].hour <= hi)} for label, lo, hi in HOUR_BUCKETS]
    days = [{'label': name, **_split(items, lambda x, i=i: x['t'].weekday() == i)} for i, name in enumerate(WEEKDAYS)]
    weekend = {'label': '周末 vs 工作日', **_split(items, lambda x: x['t'].weekday() >= 5)}
    return {'hours': hours, 'weekdays': days, 'weekend': weekend, 'clock_n': len(clock)}


def title_features(items):
    feats = (
        ('标题较长（超过20字）', lambda x: len(x['title']) > 20),
        ('标题很短（10字以内）', lambda x: 0 < len(x['title']) <= 10),
        ('含数字', lambda x: bool(re.search(r'\d', x['title']))),
        ('含问号', lambda x: bool(re.search(r'[?？]', x['title']))),
        ('含感叹号', lambda x: bool(re.search(r'[!！]', x['title']))),
        ('含话题 #', lambda x: '#' in x['title']),
        ('含括号标注（【】[]《》）', lambda x: bool(re.search(r'[【】\[\]《》]', x['title']))),
        ('含表情符号', lambda x: bool(EMOJI.search(x['title']))),
    )
    return [{'label': label, **_split(items, fn)} for label, fn in feats]


def cadence(items):
    """Does posting soon after the previous work go with better or worse relative views?"""
    gapped = [x for x in items if x['prev_gap_days'] is not None]
    return {'quick': {'label': '距上一条参与比较的作品不到3天', **_split(gapped, lambda x: x['prev_gap_days'] < 3)},
            'long': {'label': '距上一条参与比较的作品超过10天', **_split(gapped, lambda x: x['prev_gap_days'] > 10)}}


def describe(entry):
    """One plain-Chinese sentence for a comparison entry, or None if there is nothing honest to say."""
    v = entry['verdict']
    if v == 'few':
        return None
    pct = lambda x: f'{abs(x - 1) * 100:.0f}%'
    rng = f'（区间约 {entry["lift_lo"]:.2f}–{entry["lift_hi"]:.2f} 倍）'
    if v == 'better':
        return f'{entry["label"]}的作品，播放中位数约为其余作品的 {entry["lift"]:.2f} 倍，高出约 {pct(entry["lift"])}{rng}；共 {entry["n"]} 条。'
    if v == 'worse':
        return f'{entry["label"]}的作品，播放中位数约为其余作品的 {entry["lift"]:.2f} 倍，低约 {pct(entry["lift"])}{rng}；共 {entry["n"]} 条。'
    return None


def summarize(rows, now=None, mature_days=7):
    items, stats = prepare(rows, now, mature_days)
    result = {'stats': stats, 'ready': stats['used'] >= 2 * MIN_GROUP, 'findings': [], 'timing': None, 'titles': None, 'cadence': None}
    if len({x['account_key'] for x in items})>1:
        result['ready']=False;result['reason']='请先选择同一账号、体裁和观察范围，不能合并推断。'
    if not result['ready']:
        return result
    result['timing'], result['titles'], result['cadence'] = timing(items), title_features(items), cadence(items)
    entries = [*result['timing']['hours'], *result['timing']['weekdays'], result['timing']['weekend'],
               *result['titles'], *result['cadence'].values()]
    result['findings'] = [s for s in (describe(e) for e in entries if e['verdict'] in ('better', 'worse')) if s]
    return result


CAVEAT = ('90%自助法区间仅用于探索，未校正多重比较，不表示统计显著或最佳发布时间。'
          '这些是历史作品里的相关性，不等于因果：发布时间、标题写法往往同时和选题、是否投流量、当时的热点绑在一起。'
          '建议把有迹象的结论当成下一次试验的假设，而不是定论。')
