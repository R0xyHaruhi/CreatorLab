"""Own-list-bound public detail fallback and honest collection status."""
import json
import re
from html import unescape
from urllib.parse import unquote


def detail_rows(value,allowed):
    from creatorlab.sync_browser import normalize_item
    queue=[value];seen=set();rows={}
    for _ in range(6000):
        if not queue:break
        node=queue.pop()
        if not isinstance(node,(dict,list)) or id(node) in seen:continue
        seen.add(id(node))
        if isinstance(node,dict):
            vid=str(node.get('aweme_id') or node.get('awemeId') or node.get('id') or '')
            if vid in allowed and any(isinstance(node.get(k),dict) for k in ('metrics','statistics','stats')):
                row=normalize_item(node)
                if row:
                    old=rows.get(vid,{})
                    rows[vid]={**row,**old,**{k:v for k,v in row.items() if v is not None and v!=''}}
            queue.extend(v for v in node.values() if isinstance(v,(dict,list)))
        else:queue.extend(v for v in node[:500] if isinstance(v,(dict,list)))
    return list(rows.values())


def parse_detail(raw,allowed):
    if not isinstance(raw,str) or len(raw)>8_000_000:return []
    try:return detail_rows(json.loads(raw),set(allowed))
    except ValueError:return []


def page_details(page,vid):
    rows=[]
    try:
        html=page.content()
        if len(html)>10_000_000:return []
        for match in re.finditer(r'<script\b([^>]*)>(.*?)</script>',html,re.S|re.I):
            attrs,body=match.groups()
            if not re.search(r'RENDER_DATA|application/(?:ld\+)?json|__NEXT_DATA__',attrs,re.I):continue
            rows.extend(parse_detail(unquote(unescape(body)),{vid}))
    except Exception:pass
    return rows


def pending(row):
    from creatorlab.measurements import timestamp
    if row.get('visibility') in ('private','deleted','unlisted'):return []
    required=['views','likes','comments','favorites','shares']+([] if row.get('media_format')=='image' else ['completion_rate'])
    fields=[k for k in required if row.get(k) is None]
    if not timestamp(row.get('published_at')):fields.append('published_at')
    return fields


def collection_state(count,total,has_more,stagnant,steps):
    if total is not None and count>=total:return 'completed'
    if has_more is False:return 'partial' if total is not None and count<total else 'completed'
    if stagnant>=8 or steps>=160:return 'stalled'
    return 'collecting'
