"""Live platform search through visible browser loads; candidates are not verified leaders."""
import argparse,json,re,time
from html import unescape
from pathlib import Path
from urllib.parse import urlparse,parse_qs,quote
from creatorlab.peers import save_peer,profile_url
from creatorlab.bilibili_import import count,job_lock
from creatorlab.sync_browser import status_write


def search_url(platform,keyword):
    return ('https://search.bilibili.com/video?keyword=' if platform=='bilibili' else 'https://www.douyin.com/search/')+quote(keyword)


def query_for(minor,rows):
    from collections import Counter
    topics=Counter(str(r.get('topic') or '').strip() for r in rows if r.get('topic'))
    tags=Counter(t for r in rows for t in r.get('bili_tags',[]) if t and t!=minor)
    subject=topics.most_common(1)[0][0] if topics else tags.most_common(1)[0][0] if tags else ''
    return (subject+' '+minor).strip()[:80]


def parse_search(url,raw,keyword,videos_only=False):
    p=urlparse(url);q=parse_qs(p.query)
    if p.scheme!='https' or p.hostname!='api.bilibili.com' or p.path not in ('/x/web-interface/search/type','/x/web-interface/search/all/v2') or q.get('keyword')!=[keyword]:return []
    try:obj=json.loads(raw)
    except ValueError:return []
    if not isinstance(obj,dict) or obj.get('code')!=0 or not isinstance(obj.get('data'),dict):return []
    result=obj['data'].get('result',[])
    if not isinstance(result,list):return []
    flat=[]
    for row in result:
        if not isinstance(row,dict):continue
        if isinstance(row.get('data'),list):flat.extend(x for x in row['data'] if isinstance(x,dict))
        else:flat.append(row)
    out={}
    for row in flat:
        if videos_only and not re.fullmatch(r'BV[0-9A-Za-z]{10}',str(row.get('bvid') or '')):continue
        uid=str(row.get('mid') or '');name=row.get('uname') or row.get('author')
        if not re.fullmatch(r'[1-9][0-9]{0,19}',uid) or not isinstance(name,str) or not name.strip():continue
        current=out.setdefault(uid,{'name':unescape(re.sub('<[^>]+>','',name))[:100],'url':'https://space.bilibili.com/'+uid,'followers':count(row.get('fans')),'titles':[],'evidence_urls':[],'why':'作品出现在内容搜索结果中；按作品匹配，仍需检查账号整体赛道。' if videos_only else '平台关键词搜索候选，尚待确认。'})
        if row.get('bvid'):
            title=unescape(re.sub('<[^>]+>','',str(row.get('title') or '')))[:300]
            link='https://www.bilibili.com/video/'+str(row['bvid'])
            if title and link not in current['evidence_urls']:current['titles'].append(title);current['evidence_urls'].append(link)
    return list(out.values())[:12]


def segment(followers,own):
    if followers is None or not own:return '规模未知'
    r=followers/own
    return '同量级' if 1/3<=r<=3 else '稍领先' if 3<r<=10 else '较大账号参考' if r>10 else '更小规模'


DOM=r'''() => {
 const out=[];
 for(const card of document.querySelectorAll('.bili-video-card,.video-item')){
   const author=card.querySelector('a[href*="space.bilibili.com/"]');
   const video=card.querySelector('a[href*="/video/BV"]');
   if(!author||!video)continue;
   const title=card.querySelector('h3')?.title||card.querySelector('h3')?.innerText||video.title;
   out.push({url:author.href,name:(author.innerText||author.title||'').trim(),titles:title?[title]:[],evidence_urls:[video.href.split('?')[0]]});
 }
 for(const a of document.querySelectorAll('a[href*="douyin.com/user/"]'))out.push({url:a.href,name:(a.innerText||a.title||'').trim().slice(0,100)});
 return out.filter(x=>x.name);
}'''


def run(db,root,platform,major,minor,keyword=None):
    from datetime import date
    from playwright.sync_api import sync_playwright
    root=Path(root);status=root/'local'/'discovery_status.json';found={};keyword=(keyword or minor).strip()[:80]
    page_url=search_url(platform,keyword)
    def remember(row):
        try:
            url=profile_url(platform,row['url'])
            old=found.get(url,{})
            titles=list(dict.fromkeys(old.get('titles',[])+row.get('titles',[])))[:12]
            links=list(dict.fromkeys(old.get('evidence_urls',[])+row.get('evidence_urls',[])))[:12]
            row={**old,**row,'titles':titles,'evidence_urls':links}
            data={'observed_at':date.today().isoformat(),'source_url':page_url}
            if titles:data.update(matched_titles=titles,matched_videos=len(links),evidence_urls=links)
            if row.get('followers') is not None:data['followers']=row['followers']
            save_peer(db,platform,row['name'],url,major,minor,'public_search',row.get('why','平台搜索候选，赛道尚待确认。'),data);found[url]=row
        except (ValueError,KeyError,TypeError):pass
    with job_lock(root):
        try:
            status_write(status,state='starting',count=0,info='正在打开平台搜索；遇验证时请在窗口完成。')
            with sync_playwright() as pw:
                ctx=None
                for channel in ('msedge','chrome',None):
                    try:ctx=pw.chromium.launch_persistent_context(str(root/'local'/('bilibili_browser_profile' if platform=='bilibili' else 'douyin_discovery_profile')),channel=channel,headless=False);break
                    except Exception:pass
                if ctx is None:raise RuntimeError('浏览器无法启动；请安装导入浏览器。')
                def response(r):
                    p=urlparse(r.url)
                    if p.hostname=='api.bilibili.com' and p.path in ('/x/web-interface/search/type','/x/web-interface/search/all/v2'):
                        try:
                            for item in parse_search(r.url,r.text(),keyword,videos_only=True):remember(item)
                        except Exception:pass
                ctx.on('response',response)
                page=ctx.pages[0] if ctx.pages else ctx.new_page();page.goto(page_url,wait_until='domcontentloaded',timeout=45000)
                start=time.monotonic()
                while ctx.pages and time.monotonic()-start<60:
                    page.wait_for_timeout(1500)
                    location=urlparse(page.url)
                    on_search=(location.hostname=='search.bilibili.com' and parse_qs(location.query).get('keyword')==[keyword]) or (location.hostname=='www.douyin.com' and location.path.startswith('/search/'))
                    if on_search:
                        for row in page.evaluate(DOM):remember(row)
                    status_write(status,state='searching',count=len(found),info='已发现候选，尚未核验赛道或头部地位。')
                    if len(found)>=8:break
                ctx.close()
            status_write(status,state='completed' if found else 'empty',count=len(found),info='候选已保存，刷新页面后选择学习对象。' if found else '没有读到匹配候选；请处理验证、调整细分赛道或手动指定。')
        except Exception as exc:status_write(status,state='error',count=len(found),info=str(exc)[:250])

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('db','root','platform','major','minor'):p.add_argument('--'+key,required=True)
    p.add_argument('--keyword')
    a=p.parse_args();run(a.db,a.root,a.platform,a.major,a.minor,a.keyword)
