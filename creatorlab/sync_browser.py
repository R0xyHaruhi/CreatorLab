"""Opt-in creator-center UI assisted import. No private API replay or cookie export.

A separate browser launched by the user is monitored for *its own* work_list responses.
Only parsed post fields are stored in the CLab SQLite DB. No passwords/cookies stored by CLab.
"""
import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

CENTER = 'https://creator.douyin.com/'
MAX_ROWS = 10000


def iso_time(seconds):
    try:
        n = float(seconds)
        return datetime.fromtimestamp(n / 1000 if n > 1e12 else n, timezone.utc).isoformat() if n > 0 else ''
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def normalize_item(item):
    if not isinstance(item, dict):
        return None
    raw_id = str(item.get('aweme_id') or item.get('awemeId') or item.get('id') or '')
    if not re.fullmatch(r'\d{8,30}', raw_id):
        return None
    sources=[item.get(k) for k in ('metrics','statistics','stats')]+[item]
    sources=[s for s in sources if isinstance(s,dict)]
    title = str(item.get('description') or item.get('desc') or item.get('title') or f'视频 {raw_id}').strip()[:250]
    def count(*keys):
        for key in keys:
          for m in sources:
            v = m.get(key)
            if v is not None and v != '' and not isinstance(v, bool):
                try:
                    n = float(v)
                    if 0 <= n <= 2_000_000_000 and n == int(n):return int(n)
                except (ValueError, TypeError, OverflowError): pass
        return None
    def number(key):
        import math
        for m in sources:
            try:
                value=m[key];n=float(str(value).rstrip('%'))/(100 if str(value).endswith('%') else 1)
                if math.isfinite(n) and n>=0 and (key=='avg_view_second' or n<=1):return n
            except (KeyError,ValueError,TypeError):pass
        return None
    # A cover can only come from an actual image field returned by the platform.
    from creatorlab.covers import extract_cover
    cover=extract_cover(item)
    visibility=None  # Never guess visibility from metrics; schema requires verification.
    return {
        'cover_url':cover, 'visibility':visibility,
        'owner_key':owner_key(item),
        'media_format':'image' if isinstance(item.get('image_post_info'),dict) else 'video' if isinstance(item.get('video'),dict) else None,
        'video_id': raw_id, 'title': title, 'published_at': iso_time(item.get('create_time',item.get('publish_time'))),
        'url': f'https://www.douyin.com/video/{raw_id}',
        'views': count('play_count', 'play_count_total', 'total_play_count', 'view_count','playCount'),
        'likes': count('like_count','digg_count','diggCount'), 'comments': count('comment_count','commentCount'),
        'shares': count('share_count','shareCount'), 'favorites':count('collect_count','favorite_count','collection_count','collectCount'),
        'avg_view_second': number('avg_view_second'),
        'avg_view_proportion': number('avg_view_proportion'),
        'bounce_rate_2s': number('bounce_rate_2s'),
        'completion_rate': number('completion_rate'),
        'completion_rate_5s': number('completion_rate_5s'),
    }


def owner_key(item):
    author=item.get('author') if isinstance(item.get('author'),dict) else {}
    uid=author.get('uid') or item.get('author_id')
    if uid:return 'uid:'+str(uid)
    return 'sec:'+str(author['sec_uid']) if author.get('sec_uid') else ''


def parse_work_list(raw):
    if not isinstance(raw, str) or len(raw) > 4_000_000: return None
    # Numeric 19-digit video IDs must remain exact. JSON floats would lose precision.
    text = re.sub(r'("(?:id|aweme_id)"\s*:\s*)(\d{16,30})(?=\s*[,}\]])', r'\1"\2"', raw)
    try: obj = json.loads(text)
    except (ValueError, TypeError): return None
    root = obj
    for path in (('data',), ('data','data'), ()):
        tmp = obj
        for key in path:
            if not isinstance(tmp,dict): tmp = None; break
            tmp = tmp.get(key)
        if isinstance(tmp,dict) and any(isinstance(tmp.get(k),list) for k in ('items','aweme_list','item_list')):
            root=tmp; break
    else: return None
    listing=next(root[k] for k in ('items','aweme_list','item_list') if isinstance(root.get(k),list))
    rows = [normalize_item(x) for x in listing]
    total = root.get('total')
    return {'rows': [x for x in rows if x], 'raw_count':len(listing),'rejected_count':sum(x is None for x in rows), 'total': int(total) if str(total).isdigit() else None,
            'has_more':None if 'has_more' not in root else root.get('has_more') in (True,1,'1')}


def status_write(path, **data):
    from creatorlab.file_io import atomic_json
    obj={'updated_at':datetime.now(timezone.utc).isoformat(), **data}
    atomic_json(path,obj)


ADVANCE_UI = r"""() => {
  const btns=[...document.querySelectorAll('button,[role="button"],a')];
  const next=btns.find(b => {
    const label=[b.innerText,b.getAttribute('aria-label'),b.getAttribute('title')].filter(Boolean).join(' ').trim();
    return [b.innerText,b.getAttribute('aria-label'),b.getAttribute('title')].some(t=>/^(下一页|下一页\s*[›>]|next(?: page)?|下页)$/i.test((t||'').trim()))
      && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
  });
  if(next){next.click();return 'next';}
  const elements=[...document.querySelectorAll('div,main,section,[role="main"]')];
  const options=elements.filter(e => {
    const s=getComputedStyle(e);
    return e.scrollHeight>e.clientHeight+80 && e.clientHeight>150 && /(auto|scroll)/.test(s.overflowY);
  }).map(e=>{
    const text=(e.innerText||'').slice(0,12000);
    const relevance=['播放','点赞','评论','分享','作品','已发布'].filter(w=>text.includes(w)).length;
    return {e,relevance,height:e.clientHeight};
  }).sort((a,b)=>b.relevance*100000+b.height-a.relevance*100000-a.height);
  for(const {e} of options.slice(0,8)){
    const before=e.scrollTop;
    e.scrollTop=Math.min(before+Math.max(250,Math.round(e.clientHeight*.75)),e.scrollHeight-e.clientHeight);
    if(e.scrollTop>before+2)return 'scroll';
  }
  const before=window.scrollY;
  window.scrollBy(0,Math.max(320,Math.round(innerHeight*.75)));
  return window.scrollY>before+2 ? 'window-scroll':'stuck';
}"""


def wait_for_capture_review(context,db,run_id,stop_file,timeout=600):
    """Staging has finished. Let the user inspect the source and confirm in CLab.

    A closed source window is a normal user action; staged rows remain reviewable.
    No responses may append to the finished capture while this wait is active.
    """
    from creatorlab.hub import connect
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if stop_file.exists():return 'stopped'
        with connect(db) as con:
            run=con.execute('SELECT state FROM clab_dy_runs WHERE id=?',(run_id,)).fetchone()
        if not run or run['state']!='review':return run['state'] if run else 'missing'
        try:
            if not context.pages:return 'closed'
            context.pages[0].wait_for_timeout(500)
        except Exception:return 'closed'
    return 'timeout'


def start(db,root,budget=300,account_id=None,mode='full'):
    if mode not in ('recent','full','existing'):raise ValueError('未知同步范围')
    if os.getenv('CREATORLAB_ANALYSIS_ONLY')=='1':raise ValueError('容器模式不运行浏览器采集，请在本机启动')
    from creatorlab.bilibili_import import job_lock
    try:
        with job_lock(root,'douyin'):return _start(db,Path(root),budget,account_id,mode)
    except RuntimeError:return 2


def _start(db,root,budget=300,account_id=None,mode='full'):
    from creatorlab.hub import init_hub,latest_posts,METRIC_FIELDS,connect
    from creatorlab.douyin_data import collection_state,pending,page_details,parse_detail
    init_hub(db);db=Path(db)
    with connect(db) as con:
        known_ids={r[0] for r in con.execute('SELECT external_id FROM hub_posts WHERE account_id=?',(account_id,))}
    if mode=='existing':
        from creatorlab.auto_update import eligible_ids
        known_ids=eligible_ids(db,account_id)
        if not known_ids:return 3
    from creatorlab.douyin_capture import create_capture,stage_rows,finish_capture
    from creatorlab.douyin_navigation import CreatorNavigator,NAV_MESSAGES
    navigator=CreatorNavigator(root,account_id)
    run_id=create_capture(db,account_id)
    status_file=root/'local'/'sync_status.json';stop_file=root/'local'/'sync_stop'
    stop_file.unlink(missing_ok=True)
    rows={}
    total=None;pages=0;has_more=None;errors=[];details_done=0;end_reason=None;raw_seen=0;rejected_rows=0;covers_done=0;cover_targets=0;source_list_count=None;source_list_ended=False
    last_change=time.monotonic();started=last_change;list_started=None;steps=0;stagnant=0;prev_count=0;listing='collecting'
    def report(state,info):
        status_write(status_file,database=str(Path(db).resolve()),sync_mode=mode,new_count=0 if mode=='existing' else len(set(rows)-known_ids),target_count=len(known_ids),refreshed_count=len(set(rows)&known_ids),state=state,count=len(rows),total=total,pages=pages,details=details_done,account_id=account_id,run_id=run_id,
          visible_list_count=source_list_count,visible_list_ended=source_list_ended,inventory_complete=total is not None and len(rows)==total,source_has_more=has_more,list_end_reason=end_reason,raw_rows_seen=raw_seen,rejected_rows=rejected_rows,with_cover=covers_done,cover_targets=cover_targets,private_count=sum(r.get('visibility')=='private' for r in rows.values()),missing_inventory=max(0,total-len(rows)) if total is not None else None,
          coverage={k:sum(r.get(k) is not None and r.get('visibility') not in ('private','deleted','unlisted') for r in rows.values()) for k in ('views','likes','comments','favorites','shares','completion_rate')},
          info=info,warning=errors[-1] if errors else None)
    def persist(new_rows,public_detail=False):
        nonlocal last_change
        valid=[r for r in new_rows if r.get('video_id') and r.get('title')]
        if not valid:return
        if public_detail:
            from creatorlab.work_formats import preserve_confirmed_formats
            valid=preserve_confirmed_formats(valid,rows)
        staged=[r for r in valid if mode!='existing' or r['video_id'] in known_ids]
        if staged:stage_rows(db,run_id,staged)
        for r in valid:
            old=rows.get(r['video_id'],{})
            if old.get('title') and r['title']==f"视频 {r['video_id']}":r['title']=old['title']
            if not old:last_change=time.monotonic()
            rows[r['video_id']]={**old,**{k:v for k,v in r.items() if v is not None and v!=''}}
    def on_response(response):
        nonlocal total,pages,has_more,list_started,raw_seen,rejected_rows
        try:
            from urllib.parse import urlparse
            p=urlparse(response.url)
            if p.scheme!='https' or p.hostname not in ('creator.douyin.com','www.douyin.com') or response.status!=200:return
            if p.hostname=='creator.douyin.com' and 'work_list' in p.path:
                data=parse_work_list(response.text())
                if not data:
                    from creatorlab.collect_health import record_unparsed
                    record_unparsed(db,'douyin',p.path,response.text())
                    errors.append('作品列表结构无法识别，已记录脱敏结构预警；未知列表未自动入库')
                    return
                total=data['total'] if data['total'] is not None else total
                has_more=data['has_more'];pages+=1;raw_seen+=data.get('raw_count',len(data['rows']));rejected_rows+=data.get('rejected_count',0)
                if list_started is None:list_started=time.monotonic()
                persist(data['rows'])
                report('collecting','正在读取作品列表与互动指标')
            elif rows and any(word in p.path for word in ('aweme','video','item')):
                persist(parse_detail(response.text(),set(rows)),public_detail=True)
        except Exception as exc:
            errors.append('部分字段未导入：'+str(exc)[:120])
            if '作者标识' in str(exc) or '账号发生变化' in str(exc):stop_file.touch()
    report('starting','正在打开抖音作品管理')
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            context=None
            for channel in ('msedge','chrome',None):
                try:
                    context=pw.chromium.launch_persistent_context(str(root/'local'/'douyin_browser_profiles'/('account_'+str(account_id))),channel=channel,headless=mode=='existing',viewport={'width':1366,'height':900});break
                except Exception:pass
            if context is None:raise RuntimeError('无法启动浏览器，请安装Edge、Chrome或导入浏览器')
            context.on('response',on_response)
            context.add_init_script("addEventListener('play',e=>{if(e.target instanceof HTMLMediaElement){e.target.muted=true;e.target.pause();}},true)")
            context.route('**/*',lambda r:r.abort() if r.request.resource_type=='media' else r.continue_())
            page=context.pages[0] if context.pages else context.new_page()
            entry=navigator.entry_url()
            try:page.goto(entry,wait_until='domcontentloaded',timeout=45000)
            except Exception:
                if entry==CENTER:raise
                page.goto(CENTER,wait_until='domcontentloaded',timeout=45000)
            if not pages:report('navigating',NAV_MESSAGES['navigating'])
            last_advance=time.monotonic();last_status=last_advance;recovered=False
            while context.pages and not stop_file.exists() and time.monotonic()-(list_started if list_started is not None else started)<(budget if list_started is not None else 600):
                page.wait_for_timeout(700)
                current=next((p for p in context.pages if p.url.startswith(CENTER)),page)
                nav_state=navigator.step(current,time.monotonic(),has_list=bool(pages))
                if nav_state in ('waiting_login','waiting_verification'):
                    if mode=='existing':
                        finish_capture(db,run_id)
                        report(nav_state,'自动更新已暂停。请手动同步并完成登录或验证，再恢复自动更新。')
                        context.close();return 4
                    if time.monotonic()-last_status>5:
                        report(nav_state,NAV_MESSAGES[nav_state]);last_status=time.monotonic()
                    continue
                if not pages and time.monotonic()-last_status>5:
                    report(nav_state,NAV_MESSAGES.get(nav_state,NAV_MESSAGES['navigating']))
                    last_status=time.monotonic()
                if mode=='recent' and pages:
                    navigator.remember(current)
                    end_reason='first_page_saved';break
                if mode=='existing' and known_ids.issubset(rows):
                    navigator.remember(current)
                    listing='completed';end_reason='existing_targets_read';break
                listing=collection_state(len(rows),total,has_more,stagnant if time.monotonic()-last_change>=45 else 0,steps)
                if pages and listing=='completed':
                    navigator.remember(current)
                    from creatorlab.work_formats import DY_VISIBLE,match_visible_metadata
                    try:persist(match_visible_metadata(current.evaluate(DY_VISIBLE),list(rows.values())))
                    except Exception:pass
                    break
                if listing=='partial':
                    from creatorlab.work_formats import DY_LIST_EVIDENCE,visible_list_exhausted
                    try:evidence=page.evaluate(DY_LIST_EVIDENCE)
                    except Exception:evidence={}
                    if isinstance(evidence,dict):
                        source_list_count=evidence.get('count');source_list_ended=evidence.get('ended') is True
                    if visible_list_exhausted(len(rows),rejected_rows,evidence):
                        from creatorlab.work_formats import DY_VISIBLE,match_visible_metadata
                        try:persist(match_visible_metadata(current.evaluate(DY_VISIBLE),list(rows.values())))
                        except Exception as exc:errors.append('最终作品类型核对未完成：'+str(exc)[:80])
                        end_reason='visible_list_exhausted';break
                if listing=='partial' and time.monotonic()-last_change>=45:listing='stalled'
                if listing=='stalled':
                    if not recovered:
                        report('recovering','翻页暂时停住，正在刷新作品页继续收集')
                        page.reload(wait_until='domcontentloaded',timeout=20000)
                        recovered=True;stagnant=0
                    else:end_reason='list_stalled';report('stalled','列表未收齐，已保留记录；接下来尝试补充已有作品指标');break
                if pages and time.monotonic()-last_advance>2:
                    stagnant=0 if len(rows)>prev_count else stagnant+1;prev_count=len(rows)
                    current=next((p for p in context.pages if p.url.startswith(CENTER)),None)
                    if current:
                        try:
                            from creatorlab.covers import capture_visible
                            capture_visible(current,db)
                            from creatorlab.work_formats import DY_VISIBLE,match_visible_metadata
                            persist(match_visible_metadata(current.evaluate(DY_VISIBLE),list(rows.values())))
                            current.evaluate(ADVANCE_UI);steps+=1
                        except Exception:errors.append('页面翻页失败，已保留当前作品')
                    last_advance=time.monotonic()
                if time.monotonic()-last_status>5:
                    report('collecting' if pages else nav_state,'自动翻页中' if pages else NAV_MESSAGES.get(nav_state,NAV_MESSAGES['navigating']))
                    last_status=time.monotonic()
            if end_reason is None:
                end_reason='user_stopped' if stop_file.exists() else 'inventory_matched' if listing=='completed' else 'browser_closed' if not context.pages else 'list_budget_exhausted'
            if mode in ('recent','existing') and context.pages and not stop_file.exists():
                # Fast paths used to return before the full-scan cover pass.
                # Use only this run's observed IDs; never open public video pages.
                from creatorlab.covers import cache_missing_covers
                targets=[r for r in rows.values() if mode!='existing' or r['video_id'] in known_ids]
                targets.sort(key=lambda r:r['video_id'] in known_ids)
                report('covers','作品数据已读取，正在保存缺失封面；不会扫描全部历史')
                covers_done,cover_targets=cache_missing_covers(context,db,'douyin',targets,stopped=stop_file.exists)
                if covers_done<cover_targets:
                    errors.append('部分封面暂未缓存；作品数据已保留，下次同步会重试。')
            if mode=='existing':
                # Refresh existing, reviewed identities only. Discovery rows stay
                # in memory for pagination accounting and never enter this run.
                finish_capture(db,run_id)
                context.remove_listener('response',on_response)
                imported=0
                if not stop_file.exists():
                    from creatorlab.douyin_capture import auto_commit_capture
                    imported=auto_commit_capture(db,run_id,account_id)
                report('imported' if imported else 'review',f'自动更新已入库作品 {imported} 条；未导入新作品。'+('本轮未确认全量覆盖；未读取到的作品保留原观测。' if listing!='completed' else ''))
                context.close();return 0 if imported else 3
            if mode=='recent' and rows:
                # Daily sync ends after the initial list response. Public detail
                # visits and historical pagination belong to the explicit repair
                # path; neither should delay the newly captured works.
                staged=finish_capture(db,run_id)
                imported=0
                if not stop_file.exists():
                    from creatorlab.douyin_capture import auto_commit_capture
                    try:imported=auto_commit_capture(db,run_id,account_id)
                    except Exception as exc:errors.append('自动入库未完成，记录保留待核对：'+str(exc)[:120])
                report('imported' if imported else 'review',
                       f'首页 {len(rows)} 条已入库，其中新增 {len(set(rows)-known_ids)} 条。未扫描全部历史；缺项可另行补采。' if imported else
                       f'已读到 {len(set(rows)-known_ids)} 条新作品，尚未入库。请返回CLab同步区，核对归属后点击“确认归属并入库”；窗口最多保留10分钟供你核对。')
                # Finished staging must not continue consuming background responses
                # while the browser remains open for visual ownership checks.
                context.remove_listener('response',on_response)
                if not imported:
                    outcome=wait_for_capture_review(context,db,run_id,stop_file)
                    if outcome in ('committed','superseded'):
                        report('imported','归属已确认，作品已入库。可到作品库查看新作品。')
                    else:
                        report('review','作品仍已保存、尚未入库。请在CLab同步区确认归属，无需重新同步。'+('核对等待已到10分钟，采集窗口已结束。' if outcome=='timeout' else ''))
                else:
                    # Make successful completion visible instead of a sudden close.
                    try:
                        if context.pages:context.pages[0].wait_for_timeout(5000)
                    except Exception:pass
                try:context.close()
                except Exception:pass
                return 0
            # Normal public video visits fill public interactions. Retention still needs creator data.
            candidates=[r for r in rows.values() if any(k!='completion_rate' for k in pending(r)) or (r.get('visibility')=='public' and r.get('media_format')=='image' and r.get('image_count') is None)]
            with connect(db) as con:
                con.execute('CREATE TABLE IF NOT EXISTS clab_douyin_attempts(video_id TEXT PRIMARY KEY,attempts INTEGER NOT NULL)')
                attempts={r['video_id']:r['attempts'] for r in con.execute('SELECT * FROM clab_douyin_attempts')}
            candidates.sort(key=lambda r:attempts.get(r['video_id'],0))
            if candidates and context.pages and not stop_file.exists():
                detail_started=time.monotonic()
                detail=context.new_page()
                for item in candidates:
                    if time.monotonic()-detail_started>=budget or stop_file.exists():break
                    report('details',f'正在补齐已有作品 {details_done+1}/{len(candidates)}')
                    try:
                        detail.goto('https://www.douyin.com/video/'+item['video_id'],wait_until='domcontentloaded',timeout=18000)
                        for _ in range(3):
                            detail.wait_for_timeout(1000)
                            found=page_details(detail,item['video_id'])
                            if found:persist(found,public_detail=True);break
                        if item.get('media_format')=='image' and item.get('image_count') is None:
                            from creatorlab.image_reading import public_count
                            total_images=None
                            for _ in range(3):
                                total_images=public_count(detail,item)
                                if total_images is not None:break
                                detail.wait_for_timeout(1000)
                            if total_images is not None:persist([dict(video_id=item['video_id'],title=item['title'],image_count=total_images,owner_key=item.get('owner_key'))])
                        from creatorlab.covers import capture_visible,fetch_browser_cover
                        capture_visible(detail,db)
                        current=rows[item['video_id']]
                        if current.get('cover_url'):fetch_browser_cover(context,db,'douyin',item['video_id'],current['cover_url'])
                    except Exception:errors.append('有作品页未加载成功，后续可以继续补采')
                    details_done+=1
                    with connect(db) as con:con.execute('INSERT INTO clab_douyin_attempts VALUES(?,1) ON CONFLICT(video_id) DO UPDATE SET attempts=attempts+1',(item['video_id'],))
            # Cover fetching is independent of metric repair: complete metrics must not skip covers.
            from creatorlab.covers import fetch_browser_cover,cover_current
            cover_rows=[r for r in rows.values() if r.get('visibility') not in ('private','deleted','unlisted') and r.get('cover_url')]
            cover_targets=len(cover_rows);cover_started=time.monotonic()
            cached={r['video_id'] for r in cover_rows if cover_current(db,'douyin',r['video_id'],r['cover_url'])}
            covers_done=len(cached)
            for item in cover_rows:
                if stop_file.exists() or not context.pages or time.monotonic()-cover_started>=budget:break
                if item['video_id'] not in cached:
                    report('covers','正在保存作品封面，互动指标已保留')
                    if fetch_browser_cover(context,db,'douyin',item['video_id'],item['cover_url']):cached.add(item['video_id'])
                covers_done=len(cached)
            context.close()
        if stop_file.exists():state='stopped';info='已停止，采集到的数据已保存'
        elif not rows:state='empty';info='没有读到作品，请登录后打开作品管理再试'
        elif any(pending(r) for r in rows.values()) or listing!='completed' or covers_done<cover_targets:
            state='partial';info='已有数据已保存，部分作品或指标待补齐；可继续补采'
        else:state='completed';info='本轮作品与六维指标已收集完成'
        staged=finish_capture(db,run_id)
        if staged and not stop_file.exists():
            from creatorlab.douyin_capture import auto_commit_capture
            try:
                imported=auto_commit_capture(db,run_id,account_id)
                if imported:
                    report('imported',f'已通过此前核对的作者标识或已有作品ID确认归属，自动更新 {imported} 条；缺项仍保留提示');return 0
            except Exception as exc:errors.append('自动入库未完成，记录保留待核对：'+str(exc)[:120])
        report('review' if staged else state,'采集已保存待核对，请确认账号归属后入库' if staged else info);return 0
    except Exception as exc:
        end_reason='capture_error';errors.append(str(exc)[:200]);staged=finish_capture(db,run_id);report('review' if staged else 'error','窗口中断，已采记录可核对后入库' if staged else '采集未启动成功');return 1
    finally:stop_file.unlink(missing_ok=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',required=True)
    ap.add_argument('--root',required=True)
    ap.add_argument('--budget-seconds',type=int,default=300)
    ap.add_argument('--account-id',type=int,required=True)
    ap.add_argument('--mode',choices=['recent','full','existing'],default='full')
    args=ap.parse_args()
    try:raise SystemExit(start(args.db,args.root,max(30,min(args.budget_seconds,900)),args.account_id,args.mode))
    except (ValueError,RuntimeError) as exc:
        status_write(Path(args.root)/'local'/'sync_status.json',state='error',info=str(exc));raise SystemExit(1)

if __name__=='__main__':main()
