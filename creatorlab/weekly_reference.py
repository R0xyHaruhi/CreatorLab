"""Read-only Bilibili selected-video benchmarks, isolated from personal records."""
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from statistics import mean, median

DATASET = Path(__file__).resolve().parents[1] / 'assets' / 'references' / 'bilibili_weekly_100.sqlite3'
COUNTS = [('播放', 'views'), ('点赞', 'likes'), ('评论', 'comments'), ('收藏', 'favorites'),
          ('分享', 'shares'), ('投币', 'coins'), ('弹幕', 'danmaku')]


def normalize_tag(value):
    return unicodedata.normalize('NFKC', str(value)).strip().lstrip('#').casefold()


def parse_tags(value):
    return list(dict.fromkeys(normalize_tag(t) for t in re.split(r'[,，、;；\n]+', value or '') if normalize_tag(t)))


def load_dataset(path=DATASET):
    path = Path(path).resolve()
    return _load(str(path), path.stat().st_mtime_ns, path.stat().st_size)


@lru_cache(maxsize=4)
def _load(filename, modified, size):
    path = Path(filename)
    manifest = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('精选参照库校验失败，请从完整升级包恢复 assets/references。')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        if con.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('精选参照库版本不兼容')
        tags = {}
        for bvid, tag, normalized in con.execute('SELECT bvid,tag,normalized FROM sample_tags ORDER BY tag'):
            tags.setdefault(bvid, []).append((tag, normalized))
        periods = {}
        for bvid, issue in con.execute('SELECT bvid,issue FROM sample_memberships ORDER BY issue DESC'):
            periods.setdefault(bvid, []).append(issue)
        precision = {}
        for bvid, metric, raw, quality in con.execute('SELECT * FROM sample_precision'):
            precision.setdefault(bvid, {})[metric] = {'displayed_value': raw, 'precision': quality}
        records = []
        for r in con.execute('SELECT * FROM sample_videos ORDER BY bvid'):
            records.append(dict(r, tags=tuple(t[0] for t in tags.get(r['bvid'], [])),
                                normalized_tags=frozenset(t[1] for t in tags.get(r['bvid'], [])),
                                issues=tuple(periods[r['bvid']]), precision=precision.get(r['bvid'], {})))
        info = json.loads(con.execute("SELECT value FROM sample_metadata WHERE key='dataset'").fetchone()[0])
    if len(records) != info['videos']:
        raise ValueError('精选参照库记录数量不一致')
    return info, tuple(records)


def tag_facets(records):
    """Count works per public tag, never infer an editorial content category."""
    counts = Counter(t for r in records for t in r['normalized_tags'])
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def select_samples(records, tags=(), require_all=False, issues=(), published_range=None, exclude_bvids=(), required_tags=()):
    query = {normalize_tag(t) for t in tags if normalize_tag(t)}
    required = {normalize_tag(t) for t in required_tags if normalize_tag(t)}
    selected_issues = set(issues)
    excluded = set(exclude_bvids)
    frequencies = Counter(t for r in records for t in r['normalized_tags'])
    weight = lambda t: math.log((len(records) + 1) / (frequencies[t] + 1)) + 1
    selected = []
    for r in records:
        if not required.issubset(r['normalized_tags']):
            continue
        if r['bvid'] in excluded or (selected_issues and not selected_issues.intersection(r['issues'])):
            continue
        if published_range:
            # Only user-requested date filtering excludes missing publication dates.
            date = (r['published_at'] or '')[:10]
            if not date or not published_range[0] <= date <= published_range[1]:
                continue
        matched = query.intersection(r['normalized_tags'])
        if query and (not matched or (require_all and matched != query)):
            continue
        union = query.union(r['normalized_tags'])
        similarity = sum(weight(t) for t in matched) / sum(weight(t) for t in union) if query else 0
        selected.append(dict(r, matched_tags=tuple(sorted(matched)),
                             unmatched_tags=tuple(sorted(query - matched)), tag_similarity=similarity))
    return sorted(selected, key=lambda r: (-r['tag_similarity'], r['bvid']))


def comparison_rows(target, samples, rates=False):
    """Strictly-lower sample fractions, never a global rank or composite score."""
    out = []
    for label, key in COUNTS:
        if rates and key == 'views':
            continue
        value = target.get(key)
        if value is not None and not math.isfinite(float(value)):
            value = None
        if rates:
            if not target.get('views') or not target.get('_ratio_allowed', {}).get(key, True):
                value = None
            elif value is not None:
                value /= target['views']
            values = [r[key] / r['views'] for r in samples if r.get(key) is not None and r.get('views')]
        else:
            values = [r[key] for r in samples if r.get(key) is not None]
        out.append(dict(label=label + (' / 播放' if rates else ''), metric=key, value=value,
                        n=len(values), mean=mean(values) if values else None,
                        median=median(values) if values else None,
                        percent=100 * sum(v < value for v in values) / len(values)
                        if value is not None and values else None))
    return out
