"""User-confirmed reference scopes and bounded public updates with provenance."""
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from urllib import request, parse, error
from creatorlab.hub import utcnow
from creatorlab.workflow_store import put,documents,get,check_owner
from creatorlab.weekly_reference import load_dataset,normalize_tag
from creatorlab.genres import valid_genre


def reference_view(db,aid):
    info,base=load_dataset()
    updates={d['key']:d['data'] for d in documents(db,'reference',aid,'bilibili',10000)}
    records=[]
    for original in base:
        update=updates.get(original['bvid'])
        record=dict(original)
        if update:
            record.update(update)
            record['tags']=tuple(record['tags'])
            record['normalized_tags']=frozenset(normalize_tag(t) for t in record['tags'])
        records.append(record)
    return dict(info,locally_updated=len(updates)),tuple(records)


def save_scope(db,aid,name,major,minor,bvids,filters,records):
    if not name.strip() or not valid_genre('bilibili',major,minor):raise ValueError('请填写参照名称和B站细分赛道')
    ids=list(dict.fromkeys(bvids))
    allowed={r['bvid'] for r in records}
    if not ids or not set(ids)<=allowed or len(ids)>2000:raise ValueError('请选择并核对当前范围内的1—2000条作品')
    info,_=load_dataset()
    key=uuid.uuid4().hex
    put(db,'scope',aid,'bilibili',key,dict(name=name[:100],platform='bilibili',major=major,minor=minor,
        bvids=ids,filters=filters,dataset_id=info['id'],created_at=utcnow(),
        verification='用户核对样本后确认的赛道参照；并非平台自动分类或全站样本'))
    return key


def selected_scope(db,aid,key):
    scope=get(db,'scope',aid,'bilibili',key)
    if not scope:raise ValueError('参照范围不存在或不属于当前账号')
    _,records=reference_view(db,aid)
    return scope,[r for r in records if r['bvid'] in set(scope['bvids'])]


def _public_json(url):
    req=request.Request(url,headers={'User-Agent':'CreatorLab/2.6 (+local reference review)',
                                    'Referer':'https://www.bilibili.com/'})
    with request.urlopen(req,timeout=12) as response:
        # No login cookies, challenge solving, alternate hosts, or silent retries.
        return json.loads(response.read(2_000_001).decode('utf-8'))


def fetch_public_reference(bvid,fetch=None):
    if not re.fullmatch(r'BV[0-9A-Za-z]{10}',bvid):raise ValueError('无效BV号')
    fetch=fetch or _public_json
    url='https://api.bilibili.com/x/web-interface/view?'+parse.urlencode({'bvid':bvid})
    obj=fetch(url)
    if obj.get('code')!=0:raise ValueError('公开接口未返回作品，状态码 '+str(obj.get('code')))
    data=obj.get('data')
    if not isinstance(data,dict) or data.get('bvid')!=bvid or not isinstance(data.get('stat'),dict):
        raise ValueError('作品ID或响应结构不匹配，未更新')
    mapping={'views':'view','likes':'like','comments':'reply','favorites':'favorite',
             'shares':'share','coins':'coin','danmaku':'danmaku'}
    def number(value):
        return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
    values={key:number(data['stat'].get(raw)) for key,raw in mapping.items()}
    if values['views'] is None:raise ValueError('未取得可信播放计数，未更新')
    stamp=utcnow()
    values.update(title=str(data.get('title') or '').strip(),observed_at=stamp,
        source_url='https://www.bilibili.com/video/'+bvid,
        precision={k:{'displayed_value':str(v),'precision':'public_api_integer'} for k,v in values.items() if v is not None})
    if not values['title']:raise ValueError('缺少作品标题，未更新')
    tags=fetch('https://api.bilibili.com/x/tag/archive/tags?'+parse.urlencode({'bvid':bvid}))
    if tags.get('code')!=0 or not isinstance(tags.get('data'),list):
        raise ValueError('标签未成功读取；本条保留旧快照，未混合不同时间数据')
    values['tags']=[str(t['tag_name']) for t in tags['data'] if isinstance(t,dict) and isinstance(t.get('tag_name'),str)]
    return values


def refresh_references(db,aid,bvids,fetch=None,pause=.4):
    check_owner(db,aid,'bilibili')
    _,records=load_dataset()
    allowed={r['bvid'] for r in records}
    ids=list(dict.fromkeys(bvids))
    if not ids or len(ids)>10 or not set(ids)<=allowed:raise ValueError('每次仅更新已收录的1—10条公开样本')
    successes=[];failures=[];started=utcnow()
    for bvid in ids:
        try:
            value=fetch_public_reference(bvid,fetch)
            put(db,'reference',aid,'bilibili',bvid,value)
            successes.append(bvid)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            failures.append({'bvid':bvid,'reason':str(exc)[:240]})
            # Stop on failures (including verification/rate limiting); never hammer the endpoint.
            break
        if pause:time.sleep(pause)
    result=dict(started_at=started,finished_at=utcnow(),requested=ids,updated=successes,
                failures=failures,not_attempted=[b for b in ids if b not in successes and b not in {f['bvid'] for f in failures}],
                limitation='仅更新所选样本的当前累计计数和公开标签；不刷新整库，不代表全站')
    put(db,'refresh',aid,'bilibili',uuid.uuid4().hex,result)
    return result
