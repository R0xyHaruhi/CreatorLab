"""Collection health: notice platform changes instead of silently reading nothing.

The collectors depend on page responses that a platform may rename at any time.
This module (1) locates candidate lists for diagnosis only, (2) records a
*structure-only* fingerprint of responses the parser could not read, and (3) flags
metric columns that vanished from otherwise healthy rows.

Fingerprints contain key paths and value types only. Never values, titles, IDs, cookies.
"""
import json
import re
from creatorlab.hub import connect, utcnow

ID_KEYS = ('aweme_id', 'awemeId', 'id', 'item_id', 'itemId')
ID_PATTERN = re.compile(r'\d{8,30}')
METRIC_WORDS = ('play', 'view', 'like', 'digg', 'comment', 'share', 'collect', 'favorite', 'complet', 'bounce')
MAX_DEPTH = 7
MAX_PATHS = 300
KEEP_PER_PLATFORM = 20
CORE_FIELDS = ('views', 'likes', 'comments', 'shares', 'favorites')


def _looks_like_id(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(ID_PATTERN.fullmatch(str(value)))


def _is_item_list(items):
    sample = [x for x in items[:20] if isinstance(x, dict)]
    if not sample or len(sample) < min(len(items), 20) * 0.6:
        return False
    hits = sum(any(_looks_like_id(x.get(k)) for k in ID_KEYS) for x in sample)
    return hits >= max(1, int(len(sample) * 0.6))


def find_item_container(obj):
    """Return (parent_dict, key, list) for the largest list of ID-bearing dicts, else (None, None, None).

    Diagnostic only; callers must not automatically ingest an arbitrary ID-bearing list.
    """
    best = (None, None, None)
    stack = [(obj, 0, None, None)]
    while stack:
        node, depth, parent, key = stack.pop()
        if depth > MAX_DEPTH:
            continue
        if isinstance(node, list):
            if node and isinstance(parent, dict) and _is_item_list(node) and (best[2] is None or len(node) > len(best[2])):
                best = (parent, key, node)
            stack.extend((x, depth + 1, None, None) for x in node[:3] if isinstance(x, (dict, list)))
        elif isinstance(node, dict):
            stack.extend((v, depth + 1, node, k) for k, v in node.items() if isinstance(v, (dict, list)))
    return best


def find_item_list(obj):
    """Return the largest list of ID-bearing dicts, or None."""
    return find_item_container(obj)[2]


def structure(obj):
    """Bounded schema fingerprint; unknown/dynamic keys never leave raw text behind."""
    known={'data','items','aweme_list','item_list','list','entries','statistics','metrics','stats','video','author','id','aweme_id','awemeId','total','has_more','page','code','vid','plays','title','description','desc','create_time','publish_time','cover','url_list','owner','mid','vlist','count','pn','ps','View','Tags','tags'}
    known.update(CORE_FIELDS)
    known.update({'play_count','digg_count','like_count','comment_count','share_count','collect_count','favorite_count','completion_rate','bounce_rate_2s','avg_view_second','avg_view_proportion','view','like','reply','favorite','coin','danmaku','share'})
    paths=set();stack=[('',obj,0)];visited=0
    while stack and len(paths)<MAX_PATHS and visited<3000:
        path,node,depth=stack.pop();visited+=1
        if depth>MAX_DEPTH:continue
        if isinstance(node,dict):
            for key,value in list(node.items())[:300]:
                key=key if key in known else '<unknown-key>'
                child=f'{path}.{key}' if path else key
                if isinstance(value,(dict,list)):stack.append((child,value,depth+1))
                else:paths.add(f'{child}:{type(value).__name__}')
        elif isinstance(node,list):
            for value in node[:3]:
                if isinstance(value,(dict,list)):stack.append((f'{path}[]',value,depth+1))
                else:paths.add(f'{path}[]:{type(value).__name__}')
    return sorted(paths)[:MAX_PATHS]


def metric_hints(paths):
    """Key paths whose name looks like a metric; helps pinpoint renamed fields."""
    return [p for p in paths if any(w in p.rsplit('.', 1)[-1].lower() for w in METRIC_WORDS)]


def init_health(db):
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS clab_parser_drift(
          id INTEGER PRIMARY KEY, platform TEXT NOT NULL, endpoint TEXT NOT NULL,
          seen_at TEXT NOT NULL, reason TEXT NOT NULL, structure_json TEXT NOT NULL)''')


def record_unparsed(db, platform, endpoint, raw, reason='unrecognised-structure'):
    """Store a structure-only fingerprint of a response the parser could not use."""
    if not isinstance(raw, str) or len(raw) > 4_000_000:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    paths = structure(obj)
    if not paths:
        return None
    init_health(db)
    endpoint = 'douyin_work_list' if 'work_list' in str(endpoint) else 'bilibili_list' if 'arc/search' in str(endpoint) else 'bilibili_detail' if 'web-interface' in str(endpoint) else 'unrecognized-endpoint'
    with connect(db) as con:
        last = con.execute('SELECT structure_json FROM clab_parser_drift WHERE platform=? AND endpoint=? ORDER BY id DESC LIMIT 1',
                           (platform, endpoint)).fetchone()
        if last and json.loads(last['structure_json']) == paths:
            return False  # identical structure already recorded
        con.execute('INSERT INTO clab_parser_drift(platform,endpoint,seen_at,reason,structure_json) VALUES(?,?,?,?,?)',
                    (platform, endpoint, utcnow(), reason, json.dumps(paths, ensure_ascii=False)))
        con.execute('''DELETE FROM clab_parser_drift WHERE platform=? AND id NOT IN
                       (SELECT id FROM clab_parser_drift WHERE platform=? ORDER BY id DESC LIMIT ?)''',
                    (platform, platform, KEEP_PER_PLATFORM))
    return True


def assess_rows(rows, fields=CORE_FIELDS, min_rows=5):
    """Flag metric columns that are empty across many rows; likely a renamed field."""
    issues = []
    rows=[r for r in rows if r.get('visibility') not in ('private','deleted','unlisted')]
    n = len(rows)
    if n == 0:
        return [{'level': 'error', 'field': None, 'message': '没有读到任何作品：请确认已登录并打开作品管理；若持续如此，可能是平台改版。'}]
    if n < min_rows:
        return issues
    for field in fields:
        filled = sum(r.get(field) is not None for r in rows)
        if filled == 0:
            issues.append({'level': 'warn', 'field': field,
                           'message': f'{n} 条作品中「{field}」全部缺失，疑似平台调整了字段名或可见范围。'})
        elif filled / n < 0.5:
            issues.append({'level': 'info', 'field': field,
                           'message': f'「{field}」只有 {filled}/{n} 条有值，可能需要补采。'})
    return issues


def recent_drift(db, platform=None, limit=5):
    init_health(db)
    q = 'SELECT * FROM clab_parser_drift'
    args = ()
    if platform:
        q += ' WHERE platform=?'
        args = (platform,)
    with connect(db) as con:
        rows = [dict(r) for r in con.execute(q + ' ORDER BY id DESC LIMIT ?', (*args, limit))]
    for r in rows:
        r['structure'] = json.loads(r.pop('structure_json'))
        r['metric_hints'] = metric_hints(r['structure'])
    return rows


def export_report(db, platform=None):
    """Shareable text. Structure only, safe to paste into a bug report."""
    items = recent_drift(db, platform, limit=KEEP_PER_PLATFORM)
    return json.dumps({'note': '仅包含字段路径与类型，不含任何作品内容、账号或登录信息',
                       'generated_at': utcnow(), 'records': [
                           {k: r[k] for k in ('platform', 'endpoint', 'seen_at', 'reason', 'structure', 'metric_hints')}
                           for r in items]}, ensure_ascii=False, indent=1)
