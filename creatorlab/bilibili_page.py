"""Read exact video data from the page already opened by the user-started job.

Never evaluate script text or convert rounded display counts into exact metrics.
"""
import json
import re
from html import unescape
from urllib.parse import urlparse


def space_route(url,uid):
    p=urlparse(url)
    return p.hostname=='space.bilibili.com' and p.path.rstrip('/') in (f'/{uid}/upload/video',f'/{uid}/video')


def verification_page(page):
    try:return any(word in page.title() for word in ('验证码','安全验证','访问受限','登录'))
    except Exception:return False


def video_candidates(value,bvid,uid):
    """Bounded walk, with BOTH requested video and author identity required."""
    queue=[value];out=[];seen=set()
    for _ in range(6000):
        if not queue:break
        node=queue.pop()
        if not isinstance(node,(dict,list)) or id(node) in seen:continue
        seen.add(id(node))
        if isinstance(node,dict):
            owner=node.get('owner')
            if node.get('bvid')==bvid and isinstance(owner,dict) and str(owner.get('mid'))==str(uid):out.append(node)
            for key in ('videoData','View'):
                child=node.get(key)
                if isinstance(child,dict) and child.get('bvid')==bvid and isinstance(child.get('owner'),dict) and str(child['owner'].get('mid'))==str(uid):
                    tags=node.get('tags',node.get('Tags'))
                    if isinstance(tags,list):out.append({**child,'tags':tags})
            queue.extend(v for v in node.values() if isinstance(v,(dict,list)))
        else:queue.extend(v for v in node[:500] if isinstance(v,(dict,list)))
    return out


def page_values(html):
    """SSR fallback for JSON assignments; raw_decode never executes JavaScript."""
    if not isinstance(html,str) or len(html)>12_000_000:return []
    decoder=json.JSONDecoder();out=[]
    for match in re.finditer(r'(?:window\.)?__(?:INITIAL_STATE|NEXT_DATA|NUXT)__\s*=\s*',html):
        try:value,_=decoder.raw_decode(html[match.end():].lstrip())
        except ValueError:continue
        out.append(value)
    for match in re.finditer(r'<script\b[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',html,re.S|re.I):
        try:value=json.loads(unescape(match.group(1)))
        except ValueError:continue
        out.append(value)
    return out


def parse_page_html(html,bvid,uid):
    return [row for value in page_values(html) for row in video_candidates(value,bvid,uid)]


ACCOUNT_STATE=r'''uid=>{
 const queue=[window.__INITIAL_STATE__,window.__NEXT_DATA__,window.__NUXT__],seen=new Set(),out=[];
 for(let n=0;queue.length&&n<6000;n++){
   const o=queue.pop();if(!o||typeof o!=='object'||seen.has(o))continue;seen.add(o);
   if(String(o.mid)===uid)out.push({mid:o.mid,fans:o.fans,follower:o.follower,following:o.following,friend:o.friend,attention:o.attention});
   if(String(o.card?.mid)===uid)out.push({mid:o.card.mid,fans:o.follower??o.card.fans,friend:o.card.friend,like_num:o.like_num,archive_count:o.archive_count});
   for(const v of Object.values(o).slice(0,500))if(v&&typeof v==='object')queue.push(v);
 }return out;
}'''


def account_values(value,uid):
    from creatorlab.bilibili_import import count
    queue=[value];seen=set();result={}
    for _ in range(6000):
        if not queue:break
        node=queue.pop()
        if not isinstance(node,(dict,list)) or id(node) in seen:continue
        seen.add(id(node))
        if isinstance(node,dict):
            if str(node.get('mid'))==str(uid):
                for key,aliases in {'followers':('follower','fans'),'following':('following','friend','attention'),'total_likes':('like_num',),'video_count':('archive_count',)}.items():
                    for alias in aliases:
                        number=count(node.get(alias))
                        if number is not None:result[key]=number;break
            card=node.get('card')
            if isinstance(card,dict) and str(card.get('mid'))==str(uid):
                queue.append({**card,**{k:node[k] for k in ('follower','like_num','archive_count') if k in node}})
            queue.extend(v for v in node.values() if isinstance(v,(dict,list)))
        else:queue.extend(v for v in node[:500] if isinstance(v,(dict,list)))
    return result


def read_account(page,uid):
    result={}
    try:result.update(account_values(page.evaluate(ACCOUNT_STATE,str(uid)),uid))
    except Exception:pass
    try:
        for value in page_values(page.content()):result.update(account_values(value,uid))
    except Exception:pass
    return result


DETAIL_STATE=r'''({bvid,uid}) => {
 const queue=[window.__INITIAL_STATE__,window.__NEXT_DATA__,window.__NUXT__];
 const seen=new Set(),out=[];
 for(let n=0;queue.length&&n<6000;n++){
   const obj=queue.pop();if(!obj||typeof obj!=='object'||seen.has(obj))continue;seen.add(obj);
   if(obj.bvid===bvid&&String(obj.owner?.mid)===uid){
     out.push({bvid:obj.bvid,title:obj.title,pic:obj.pic,pubdate:obj.pubdate,duration:obj.duration,tname:obj.tname,desc:obj.desc,tags:obj.tags,
       owner:{mid:obj.owner.mid},stat:obj.stat});
   }
   for(const v of Object.values(obj).slice(0,500))if(v&&typeof v==='object')queue.push(v);
 }
 return out;
}'''


DETAIL_VISIBLE=r'''({bvid,uid}) => {
 const canonical=document.querySelector('link[rel="canonical"]')?.href||location.href;
 if(!canonical.includes('/video/'+bvid))return null;
 const owners=[...document.querySelectorAll('.up-info a[href],.up-panel-container a[href],.up-info-container a[href]')];
 if(!owners.some(a=>{try{return new URL(a.href).hostname==='space.bilibili.com'&&new URL(a.href).pathname.replace(/\/$/,'')==='/'+uid;}catch{return false;}}))return null;
 const exact=sel=>{
   const root=document.querySelector(sel);if(!root)return null;
   for(const el of [root,...root.querySelectorAll('*')]){
     for(const text of [el.getAttribute('data-count'),el.getAttribute('title'),el.innerText]){
       const t=(text||'').trim();if(/^\d[\d,，]*$/.test(t))return Number(t.replace(/[,，]/g,''));
     }
   }return null;
 };
 const date=document.querySelector('meta[itemprop="uploadDate"]')?.content;
 const ts=date?Date.parse(date):NaN;
 return {bvid,owner:{mid:uid},title:document.querySelector('h1')?.title||document.querySelector('h1')?.innerText,
   pic:document.querySelector('meta[property="og:image"]')?.content,
   pubdate:Number.isFinite(ts)?Math.floor(ts/1000):undefined,
   stat:{view:exact('.view-text'),like:exact('.video-like'),reply:exact('.reply-header .total-reply'),
     favorite:exact('.video-fav'),share:exact('.video-share'),coin:exact('.video-coin'),danmaku:exact('.dm-text')}};
}'''


def read_detail(page,bvid,uid):
    from creatorlab.bilibili_import import normalize
    candidates=[]
    try:candidates.extend(page.evaluate(DETAIL_STATE,{'bvid':bvid,'uid':str(uid)}) or [])
    except Exception:pass
    try:candidates.extend(parse_page_html(page.content(),bvid,uid))
    except Exception:pass
    try:
        visible=page.evaluate(DETAIL_VISIBLE,{'bvid':bvid,'uid':str(uid)})
        if visible:candidates.append(visible)
    except Exception:pass
    result=None
    for data in candidates:
        if not video_candidates(data,bvid,uid):continue
        row=normalize(data)
        if not row:continue
        if result is None:result=row;continue
        for key in ('published_at','cover_url','duration_seconds','partition_name','description','tags'):
            if not result.get(key) and row.get(key):result[key]=row[key]
        for key,value in row['metrics'].items():
            if result['metrics'].get(key) is None and value is not None:result['metrics'][key]=value
    return result
