"""User-started public-space import. Observe normal browser loads, never replay APIs."""
import argparse
from contextlib import contextmanager
import json
import math
import os
import re
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from creatorlab.hub import init_hub,connect,add_account,upsert_post,METRIC_FIELDS
from creatorlab.covers import cached_cover,save_cover,count_cached,cover_current
from creatorlab.sync_browser import status_write

BV=re.compile(r'BV[0-9A-Za-z]{10}')
LIST_PATHS={'/x/space/wbi/arc/search','/x/space/arc/search'}
DETAIL_PATHS={'/x/web-interface/view','/x/web-interface/wbi/view','/x/web-interface/view/detail','/x/web-interface/wbi/view/detail'}
TERMINAL={'completed','partial','empty','stopped','error'}


def parse_uid(value):
    value=str(value or '').strip()
    if re.fullmatch(r'[1-9][0-9]{0,19}',value):return value
    p=urlparse(value)
    if p.scheme=='https' and p.hostname=='space.bilibili.com' and not p.username and not p.password and not p.port:
        uid=p.path.strip('/').split('/')[0]
        if re.fullmatch(r'[1-9][0-9]{0,19}',uid):return uid
    raise ValueError('请填写数字UID，或 https://space.bilibili.com/UID 形式的空间链接')


def count(value):
    if value is None or isinstance(value,bool) or value=='':return None
    try:
        n=float(value)
        return int(n) if math.isfinite(n) and 0<=n<=10**13 and n==int(n) else None
    except (TypeError,ValueError):return None


def duration(value):
    if isinstance(value,str) and ':' in value:
        parts=value.split(':')
        if len(parts) not in (2,3) or not all(x.isdigit() for x in parts) or any(int(x)>=60 for x in parts[1:]):return None
        n=0
        for x in parts:n=n*60+int(x)
    else:n=count(value)
    return n if n and n<=86400 else None


def image_url(value):
    if not isinstance(value,str):return None
    if value.startswith('//'):value='https:'+value
    p=urlparse(value)
    if p.scheme in ('http','https') and p.hostname and (p.hostname=='hdslb.com' or p.hostname.endswith('.hdslb.com')) and not p.username and not p.password and not p.port:
        return 'https://'+p.netloc+p.path+('?' + p.query if p.query else '')
    return None


def normalize(item):
    if not isinstance(item,dict) or not BV.fullmatch(str(item.get('bvid') or '')):return None
    stat=item.get('stat') if isinstance(item.get('stat'),dict) else {}
    raw_time=item.get('pubdate',item.get('created'));at=None
    ts=count(raw_time)
    if ts:
        try:at=datetime.fromtimestamp(ts,timezone.utc).isoformat()
        except (ValueError,OverflowError,OSError):pass
    return dict(external_id=item['bvid'],title=str(item.get('title') or ('标题待同步 '+item['bvid']))[:500],
       partition_name=str(item.get('tname') or '')[:100],description=str(item.get('desc') or '')[:3000],
       tags=list(dict.fromkeys(str(t.get('tag_name') or '')[:100] if isinstance(t,dict) else str(t)[:100] for t in item.get('tags',[]) if isinstance(t,(dict,str))))[:20] if isinstance(item.get('tags'),list) else [],
       published_at=at,url='https://www.bilibili.com/video/'+item['bvid'],
       visibility='private' if item.get('visibility')=='private' else None,
       cover_url=image_url(item.get('pic') or item.get('cover')),
       duration_seconds=duration(item.get('duration',item.get('length'))),
       metrics={'views':count(stat.get('view',item.get('play'))),
          'comments':count(stat.get('reply',item.get('comment'))),
          'likes':count(stat.get('like')),'favorites':count(stat.get('favorite')),'shares':count(stat.get('share')),'coins':count(stat.get('coin')),'danmaku':count(stat.get('danmaku',item.get('video_review')))})


def parse_response(url,raw,uid):
    """An allowlist plus UID binding excludes recommendations and unrelated uploads."""
    p=urlparse(url)
    if p.scheme!='https' or p.hostname!='api.bilibili.com' or p.path not in LIST_PATHS|DETAIL_PATHS:return None
    if not isinstance(raw,str) or len(raw)>5_000_000:return None
    try:obj=json.loads(raw)
    except ValueError:return None
    if not isinstance(obj,dict):return None
    if obj.get('code')!=0:return {'error':'平台返回错误 '+str(obj.get('code')),'rows':[]}
    data=obj.get('data')
    if not isinstance(data,dict):return None
    if p.path in LIST_PATHS:
        if parse_qs(p.query).get('mid')!=[str(uid)]:return None
        listing=data.get('list')
        if not isinstance(listing,dict) or not isinstance(listing.get('vlist'),list):return None
        rows=[]
        for item in listing['vlist']:
            if not isinstance(item,dict):continue
            owner=item.get('mid')
            if owner is not None and str(owner)!=str(uid):continue
            row=normalize(item)
            if row:rows.append(row)
        page=data.get('page') if isinstance(data.get('page'),dict) else {}
        total=count(page.get('count'));pn=count(page.get('pn'));ps=count(page.get('ps'))
        ended=bool(total is not None and pn and ps and pn*ps>=total)
        return {'rows':rows,'total':total,'ended':ended,'kind':'list'}
    tags=data.get('Tags',data.get('tags'))
    data=data.get('View',data.get('view',data))
    if not isinstance(data,dict) or not isinstance(data.get('owner'),dict) or str(data['owner'].get('mid'))!=str(uid):return None
    row=normalize({**data,**({'tags':tags} if isinstance(tags,list) else {})})
    return {'rows':[row] if row else [],'kind':'detail'}


def persist(db,uid,row):
    # Preserve manually named account and labels; a repeat updates the same BV record.
    with connect(db) as con:
        account=con.execute('SELECT id FROM hub_accounts WHERE platform=? AND handle=?',('bilibili',uid)).fetchone()
    aid=account['id'] if account else add_account(db,'bilibili',uid,'B站 · '+uid)
    with connect(db) as con:
        record=con.execute('SELECT p.*,'+','.join('s.'+k for k in METRIC_FIELDS)+''' FROM hub_posts p
          LEFT JOIN hub_snapshots s ON s.id=(SELECT max(id) FROM hub_snapshots WHERE post_id=p.id)
          WHERE p.account_id=? AND p.external_id=?''',(aid,row['external_id'])).fetchone()
        current=dict(record) if record else None
    if current and row['title'].startswith('标题待同步 '):row=dict(row,title=current['title'])
    changed=not current or any(row.get(k) and row[k]!=current.get(k) for k in ('title','published_at','cover_url','visibility')) or any(v is not None and current.get(k)!=v for k,v in row.get('metrics',{}).items())
    if changed:
        pid=upsert_post(db,aid,row['title'],row['external_id'],row.get('published_at'),row.get('url'),
           metrics=row.get('metrics'),source='bilibili_space',cover_url=row.get('cover_url'),visibility=row.get('visibility'))
    else:
        pid=current['id']
        from creatorlab.measurements import record
        record(db,pid,row.get('metrics',{}),source='bilibili_space')
    if row.get('duration_seconds'):
        with connect(db) as con:
            con.execute('''INSERT INTO hub_content(post_id,duration_seconds) VALUES(?,?)
              ON CONFLICT(post_id) DO UPDATE SET duration_seconds=COALESCE(hub_content.duration_seconds,excluded.duration_seconds)''',(pid,row['duration_seconds']))
    from creatorlab.bilibili_metadata import save_metadata
    save_metadata(db,pid,row)
    return changed


def ingest_row(db,uid,row,rows,seen):
    """One path for network, DOM and SSR. Timestamp ONLY newly observed fields."""
    if not row or len(rows)>=5000 and row['external_id'] not in rows:return
    fresh={k:v for k,v in row.get('metrics',{}).items() if v is not None}
    old=rows.get(row['external_id'],{})
    merged=dict(row,metrics={**old.get('metrics',{}),**fresh})
    for field in ('published_at','cover_url','duration_seconds','url','partition_name','description','tags','visibility'):
        if not merged.get(field) and old.get(field):merged[field]=old[field]
    if merged['title'].startswith('标题待同步 ') and old.get('title'):merged['title']=old['title']
    persist(db,uid,dict(merged,metrics=fresh))
    rows[row['external_id']]=merged
    seen.setdefault(row['external_id'],set()).update(fresh)


def complete_row(row,seen):
    from creatorlab.sync_jobs import FIELDS
    from creatorlab.measurements import timestamp
    return bool(timestamp(row.get('published_at')) and all(k in seen.get(row['external_id'],set()) for k in FIELDS))


def detail_priority(row,seen):
    from creatorlab.measurements import timestamp
    at=timestamp(row.get('published_at'))
    return (complete_row(row,seen),at is not None,-at.timestamp() if at else 0)


DOM_CARDS=r'''() => {
 const rows=new Map();
 for(const a of document.querySelectorAll('.bili-video-card a[href*="/video/BV"],.small-item a[href*="/video/BV"],.video-list-item a[href*="/video/BV"],.upload-video-card a[href*="/video/BV"]')){
   let u;try{u=new URL(a.href);}catch{continue;}
   if(!['www.bilibili.com','bilibili.com'].includes(u.hostname))continue;
   const m=u.pathname.match(/^\/video\/(BV[A-Za-z0-9]{10})(?:\/|$)/);if(!m)continue;
   const card=a.closest('.bili-video-card,.small-item,.video-list-item,.upload-video-card');
   const img=a.querySelector('img')||card?.querySelector('img');
   const title=a.getAttribute('title')||(img&&img.alt)||(a.innerText||'').trim();
   if(!title||title.length>500)continue;
   const previous=rows.get(m[1]);
   rows.set(m[1],{bvid:m[1],title,visibility:/仅自己可见|退回仅自见/.test(card?.innerText||'')?'private':null,pic:(img&&(img.currentSrc||img.src))||(previous&&previous.pic)});
 }
 return [...rows.values()];
}'''
NEXT_PAGE=r'''() => {
 const elements=[...document.querySelectorAll('button,[role="button"],a')];
 const next=elements.find(e=> /^(下一页|下页|next(?: page)?)$/i.test((e.innerText||e.getAttribute('aria-label')||e.title||'').trim())&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!/disabled/.test(e.className||''));
 if(next){next.click();return true;}return false;
}'''


def capture_images(page,db,known):
    for img in page.locator('a[href*="/video/BV"] img').all()[:80]:
        try:
            bvid=img.evaluate("i=>{const a=i.closest('a');const m=(a?.href||'').match(/\\/video\\/(BV[A-Za-z0-9]{10})/);return m&&m[1]}")
            if bvid not in known or cover_current(db,'bilibili',bvid,known[bvid].get('cover_url')) or not img.is_visible():continue
            if not img.evaluate('i=>i.complete&&i.naturalWidth>40'):continue
            save_cover(db,'bilibili',bvid,img.screenshot(type='png',timeout=1200),'bilibili_rendered_cover',origin_url=known[bvid].get('cover_url'))
        except Exception:continue


@contextmanager
def job_lock(root,name='bilibili'):
    if name not in ('bilibili','douyin'):raise ValueError('未知采集任务')
    path=Path(root)/'local'/(name+'_sync.lock');path.parent.mkdir(parents=True,exist_ok=True)
    f=open(path,'a+b')
    if path.stat().st_size==0:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise RuntimeError('已有B站导入任务正在运行，请先停止或等待完成。')
    try:yield
    finally:
        f.seek(0)
        if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()


def job_running(root,name='bilibili'):
    try:
        with job_lock(root,name):return False
    except RuntimeError:return True


def run(db,root,uid,details=0,creator=False,retry_only=False,budget=300):
    if os.getenv('CREATORLAB_ANALYSIS_ONLY')=='1':raise ValueError('容器模式不运行浏览器采集，请在本机启动')
    with job_lock(root):return _run(db,root,uid,5000 if details==-1 else min(5000,max(0,details)),creator,retry_only,budget)


def _run(db,root,uid,details=0,creator=False,retry_only=False,budget=300):
    uid=parse_uid(uid);root=Path(root);db=Path(db);init_hub(db)
    local=root/'local';local.mkdir(exist_ok=True)
    status=local/'bilibili_sync_status.json';stop=local/'bilibili_sync_stop'
    stop.unlink(missing_ok=True)
    from creatorlab.sync_jobs import retry_rows,record_attempt,estimate
    from creatorlab.bilibili_page import space_route,read_detail,read_account,verification_page
    targets=retry_rows(db,uid) if retry_only else []
    rows={r['external_id']:dict(visibility=r.get('visibility'),external_id=r['external_id'],title=r['title'],published_at=r.get('published_at'),url=r['url'],cover_url=r.get('cover_url'),metrics={k:r.get(k) for k in METRIC_FIELDS}) for r in targets}
    target_ids=set(rows);total=len(targets) if retry_only else None;ended=False;pages=0;last_error=None;details_done=0;verified_uid=None;account_fields=set();creator_saved=False
    phase_total=0;phase_started=time.monotonic();seen={};attempted=set();logged=set()

    def report(state,info):
        status_write(status,database=str(Path(db).resolve()),state=state,uid=uid,count=len(rows),total=total,pages=pages,
             private_count=sum(r.get('visibility')=='private' for r in rows.values()),
             with_views=sum(r.get('metrics',{}).get('views') is not None for r in rows.values()),
             details=details_done,phase_total=phase_total,radar_ready=sum(complete_row(r,seen) for r in rows.values()),remaining_seconds=estimate(time.monotonic()-phase_started,details_done,phase_total) if state=='details' else None,
             fresh_coverage={k:sum(k in v for v in seen.values()) for k in METRIC_FIELDS},with_cover=count_cached(db,'bilibili',rows.keys()),account_fields=sorted(account_fields),creator_saved=creator_saved,
             coverage={k:sum(r.get('metrics',{}).get(k) is not None for r in rows.values()) for k in ('views','likes','comments','shares','favorites','coins','danmaku')},info=info,warning=last_error)
    def on_response(response):
        nonlocal total,ended,pages,last_error,verified_uid
        try:
            parsed=urlparse(response.url)
            from creatorlab.bilibili_account import ACCOUNT_PATHS,parse_account_response,save_observation
            if parsed.hostname!='api.bilibili.com':return
            if parsed.path=='/x/web-interface/nav':
                try:
                    auth=json.loads(response.text());auth_data=auth.get('data',{})
                    verified_uid=str(auth_data.get('mid')) if auth.get('code')==0 and auth_data.get('isLogin') is True else None
                except (ValueError,AttributeError):verified_uid=None
                return
            if parsed.path in ACCOUNT_PATHS:
                metrics=parse_account_response(response.url,response.text(),uid)
                if metrics:
                    save_observation(db,uid,'account',metrics,'公开空间 '+parsed.path,'账号公开统计')
                    account_fields.update(metrics)
                return
            if parsed.path not in LIST_PATHS|DETAIL_PATHS:return
            result=parse_response(response.url,response.text(),uid) if response.request.resource_type in ('xhr','fetch') else None
            if not result:
                from creatorlab.collect_health import record_unparsed
                record_unparsed(db,'bilibili',parsed.path,response.text())
                last_error='暂未识别该投稿响应结构，正在尝试页面卡片导入。'
                return
            if result.get('error'):last_error=result['error'];return
            if result['kind']=='list' and not retry_only:
                pages+=1;ended=result.get('ended',False)
                if result.get('total') is not None:total=result['total']
            for row in result['rows']:
                if retry_only and row['external_id'] not in target_ids:continue
                ingest_row(db,uid,row,rows,seen)
            report('collecting','正在导入空间公开投稿。')
        except Exception as exc:last_error='部分响应未导入：'+str(exc)[:120]
    final='completed' if retry_only else 'partial'
    if retry_only and not targets:
        report('completed','没有缺失项或当前到期窗口需要补采。');return 0
    try:
        from playwright.sync_api import sync_playwright
        report('starting','正在打开B站空间；如遇登录或验证，请在窗口内完成。')
        with sync_playwright() as pw:
            context=None
            for channel in ('msedge','chrome',None):
                try:
                    context=pw.chromium.launch_persistent_context(str(local/'bilibili_browser_profile'),headless=False,
                       channel=channel,viewport={'width':1366,'height':900});break
                except Exception:continue
            if context is None:raise RuntimeError('浏览器启动失败。请安装Edge/Chrome，或双击 install_bilibili_browser_windows.bat 安装导入浏览器后重试。')
            context.add_init_script("addEventListener('play',e=>{if(e.target instanceof HTMLMediaElement){e.target.muted=true;e.target.pause();}},true)")
            context.route('**/*',lambda route:route.abort() if route.request.resource_type=='media' else route.continue_())
            context.on('response',on_response)
            page=context.pages[0] if context.pages else context.new_page()
            page.goto('https://space.bilibili.com/'+uid+'/upload/video',wait_until='domcontentloaded',timeout=60000)
            previous=-1;stagnant=0;steps=0;started=time.monotonic();last_advance=0
            while context.pages and not stop.exists() and not retry_only and time.monotonic()-started<budget:
                page.wait_for_timeout(900)
                if verification_page(page):
                    report('waiting_login','列表遇到验证，请在当前采集窗口完成；已保存记录，验证期间暂停翻页。')
                    continue
                # DOM fallback is bound to the requested space's video-tab URL only.
                if space_route(page.url,uid):
                    for item in page.evaluate(DOM_CARDS):
                        row=normalize(item)
                        if row and (row['external_id'] not in rows and len(rows)<5000 or row.get('visibility') and rows.get(row['external_id'],{}).get('visibility')!=row['visibility']):
                            ingest_row(db,uid,row,rows,seen)
                    capture_images(page,db,rows)
                    from creatorlab.bilibili_account import ACCOUNT_DOM,save_observation
                    account_data=page.evaluate(ACCOUNT_DOM)
                    if not isinstance(account_data,dict):account_data={}
                    account_data.update(read_account(page,uid))
                    if isinstance(account_data,dict) and account_data:
                        save_observation(db,uid,'account',account_data,'空间页可见账号数据','账号公开统计')
                        account_fields.update(account_data)
                report('collecting' if rows else 'waiting_login','正在翻页并保存作品。' if rows else '等待作品列表加载。若提示登录或验证，请在浏览器内完成。')
                if total==0:final='empty';break
                if (total is not None and len(rows)>=total) or (ended and total is not None and len(rows)>=total):final='completed';break
                if len(rows)>=5000:break
                if time.monotonic()-last_advance>=3 and rows:
                    stagnant=stagnant+1 if len(rows)==previous else 0;previous=len(rows)
                    moved=page.evaluate(NEXT_PAGE);steps+=int(moved);last_advance=time.monotonic()
                    if steps>=200 or stagnant>=10:break
            if stop.exists():final='stopped'
            if creator and final!='stopped':
                from creatorlab.bilibili_account import OVERVIEW_DOM,capture_creator_overview
                backend=context.new_page()
                report('creator','请登录目标UID，打开「数据中心 → 视频数据」。等待最多3分钟。')
                backend.goto('https://member.bilibili.com/platform/home',wait_until='domcontentloaded',timeout=30000)
                try:backend.get_by_text('数据中心',exact=True).first.click(timeout=3000)
                except Exception:pass
                started_backend=time.monotonic()
                while not stop.exists() and time.monotonic()-started_backend<180:
                    backend.wait_for_timeout(1000)
                    if verified_uid!=uid:
                        last_error='尚未验证为目标UID本人登录，创作中心数据暂不入库。'
                        continue
                    if urlparse(backend.url).hostname!='member.bilibili.com':continue
                    captured=backend.evaluate(OVERVIEW_DOM)
                    if capture_creator_overview(db,uid,verified_uid,captured):
                        creator_saved=True;last_error=None;break
                if not creator_saved:last_error='本次未采到创作中心概览；请确认登录UID和视频数据页，公开作品已保留。'
            # Optional normal video-page visits, explicitly bounded by the UI option.
            if details and rows and final!='stopped':
                detail_page=context.new_page()
                # Unknown dates need repair first; otherwise newest incomplete works first.
                candidates=sorted((r for r in rows.values() if r.get('visibility')!='private'),key=lambda r:detail_priority(r,seen))[:details]
                phase_total=len(candidates);phase_started=time.monotonic()
                for row in candidates:
                    if time.monotonic()-phase_started>budget:
                        final='partial';last_error='达到本轮时间预算；剩余作品可通过定向补采继续。';break
                    if stop.exists():final='stopped';break
                    attempted.add(row['external_id'])
                    report('details','正在通过作品页补充互动指标。')
                    for attempt in range(2):
                        if stop.exists():break
                        try:
                            detail_page.goto(row['url'],wait_until='domcontentloaded',timeout=20000)
                            polls=60 if verification_page(detail_page) else 8
                            if polls==60:report('waiting_login','作品页遇到验证，请在当前采集窗口完成；完成后继续读取，等待最多60秒。')
                            for poll in range(polls):
                                if time.monotonic()-phase_started>budget or stop.exists():break
                                detail_page.wait_for_timeout(1000)
                                enriched=read_detail(detail_page,row['external_id'],uid)
                                if enriched:ingest_row(db,uid,enriched,rows,seen)
                                account_data=read_account(detail_page,uid)
                                if account_data:
                                    from creatorlab.bilibili_account import save_observation
                                    save_observation(db,uid,'account',account_data,'视频页内嵌账号数据','账号公开统计')
                                    account_fields.update(account_data)
                                if complete_row(rows[row['external_id']],seen) or stop.exists():break
                            if complete_row(rows[row['external_id']],seen):break
                            last_error='详情页数据未齐，可能仍在加载或等待验证；将重试并记录缺项。'
                        except Exception:
                            last_error='作品页加载失败，已保留记录并加入补采清单。'
                            if attempt==0:detail_page.wait_for_timeout(1000)
                    details_done+=1
                    from creatorlab.sync_jobs import FIELDS
                    missing_now=[k for k in FIELDS if k not in seen.get(row['external_id'],set())]
                    if not rows[row['external_id']].get('published_at'):missing_now.append('published_at')
                    if not rows[row['external_id']].get('cover_url'):missing_now.append('cover_url')
                    if not cached_cover(db,'bilibili',row['external_id']):missing_now.append('cover')
                    record_attempt(db,uid,row['external_id'],missing_now,'详情页没有取得这些字段' if missing_now else '')
                    logged.add(row['external_id'])
            from creatorlab.covers import fetch_browser_cover
            for cover_row in list(rows.values()):
                if time.monotonic()-phase_started>budget:final='partial';last_error='本轮预算已用完，可定向补采剩余项。';break
                if stop.exists():final='stopped';break
                if context.pages and cover_row.get('cover_url') and not cover_current(db,'bilibili',cover_row['external_id'],cover_row.get('cover_url')):
                    attempted.add(cover_row['external_id'])
                    report('covers','正在保存真实作品封面。')
                    fetch_browser_cover(context,db,'bilibili',cover_row['external_id'],cover_row['cover_url'])
                from creatorlab.sync_jobs import FIELDS
                absent=[k for k in FIELDS if k not in seen.get(cover_row['external_id'],set())]
                if not cover_row.get('published_at'):absent.append('published_at')
                if not cover_row.get('cover_url'):absent.append('cover_url')
                if not cover_current(db,'bilibili',cover_row['external_id'],cover_row.get('cover_url')):absent.append('cover')
                if cover_row['external_id'] in attempted or cover_row['external_id'] in seen:
                    record_attempt(db,uid,cover_row['external_id'],absent,'本轮仍未取得这些字段' if absent else '',increment=cover_row['external_id'] not in logged)
            context.close()
        if rows and final=='completed' and any(not complete_row(r,seen) for r in rows.values() if r.get('visibility')!='private'):final='partial'
        ready=sum(complete_row(r,seen) for r in rows.values())
        messages={'completed':'公开投稿及本轮互动字段已读取；已缓存封面数量请查看完整度。',
          'partial':f'已识别 {len(rows)} 条作品，其中 {ready} 条已取得完整互动字段和发布时间；其余尚不能制作完整画像，可定向补采。',
          'empty':'空间列表报告公开投稿为0。','stopped':'已停止，之前导入的作品已保存。'}
        if not rows and final!='empty' and final!='stopped':
            final='error';messages[final]='没有读到作品。请确认UID、视频投稿页及登录/验证状态后重试。'
        report(final,messages[final]);return 0
    except Exception as exc:
        if rows:
            report('partial','页面导入中断，已保存采集到的作品。'+str(exc)[:180])
        else:report('error',str(exc)[:350])
        return 1
    finally:
        stop.unlink(missing_ok=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--db',required=True);ap.add_argument('--root',required=True);ap.add_argument('--uid',required=True);ap.add_argument('--details',type=int,default=0);ap.add_argument('--creator',action='store_true');ap.add_argument('--retry-missing',action='store_true');ap.add_argument('--budget-seconds',type=int,default=300)
    args=ap.parse_args();raise SystemExit(run(args.db,args.root,args.uid,args.details,args.creator,args.retry_missing,max(30,min(args.budget_seconds,1800))))

if __name__=='__main__':main()
