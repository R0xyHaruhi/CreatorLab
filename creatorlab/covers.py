"""Capture actual rendered covers, bound by video ID. Never synthesize a cover."""
import io
import re
from PIL import Image, UnidentifiedImageError
from creatorlab.hub import connect, valid_cover, utcnow


def extract_cover(item):
    def url(value):
        if isinstance(value,str): return value if valid_cover(value) else None
        if isinstance(value,list): return next((u for v in value if (u:=url(v))),None)
        if isinstance(value,dict): return url(value.get('url_list')) or url(value.get('url'))
    video=item.get('video') if isinstance(item.get('video'),dict) else {}
    return next((u for v in [item.get(k) for k in ('cover','video_cover','cover_url')]+[video.get(k) for k in ('cover','origin_cover','dynamic_cover')] if (u:=url(v))),None)


def init_covers(db):
    with connect(db) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS hub_covers(
          platform TEXT NOT NULL, external_id TEXT NOT NULL, image BLOB NOT NULL,
          source TEXT NOT NULL, captured_at TEXT NOT NULL,
          PRIMARY KEY(platform,external_id))''')
        cols={r['name'] for r in con.execute('PRAGMA table_info(hub_covers)')}
        if 'origin_url' not in cols:con.execute('ALTER TABLE hub_covers ADD COLUMN origin_url TEXT')


def save_cover(db,platform,external_id,data,source,origin_url=None):
    if platform not in ('douyin','bilibili') or not external_id: raise ValueError('封面缺少作品标识')
    if len(data)>5_000_000: raise ValueError('封面不能超过 5MB')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width*im.height>20_000_000: raise ValueError('封面尺寸过大')
            im.load();im.thumbnail((720,960));out=io.BytesIO();im.convert('RGB').save(out,format='JPEG',quality=88)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
        raise ValueError('封面图片无效') from exc
    init_covers(db)
    with connect(db) as con:
        con.execute('INSERT OR REPLACE INTO hub_covers(platform,external_id,image,source,captured_at,origin_url) VALUES(?,?,?,?,?,?)',
                    (platform,str(external_id),out.getvalue(),str(source)[:2048],utcnow(),origin_url))


def cached_cover(db,platform,external_id):
    if not db or not external_id:return None
    init_covers(db)
    with connect(db) as con:
        row=con.execute('SELECT image FROM hub_covers WHERE platform=? AND external_id=?',(platform,str(external_id))).fetchone()
        return row['image'] if row else None

# Match the nearest unambiguous card using explicit video IDs or a video link.
# Deliberately never bind by DOM position or fuzzy titles.
IMAGE_ID = r'''img => {
 for(let p=img,depth=0;p&&depth<6;p=p.parentElement,depth++){
   const ids=new Set();
   for(const el of [p,...p.querySelectorAll('[data-aweme-id],[data-video-id],a[href]')]){
     for(const attr of ['data-aweme-id','data-video-id']){
       const v=el.getAttribute(attr);if(/^\d{8,30}$/.test(v||''))ids.add(v);
     }
     const m=(el.getAttribute('href')||'').match(/\/video\/(\d{8,30})(?:\D|$)/);
     if(m)ids.add(m[1]);
   }
   if(ids.size===1)return [...ids][0];
   if(ids.size>1)return null;
 }
 return null;
}'''


def capture_visible(page, db):
    """Cache a thumbnail screenshot, cropped to the image, while the UI is visible."""
    captured=0
    from creatorlab.bridge import list_batch
    by_url={r['cover_url']:r['video_id'] for r in list_batch(db) if r.get('cover_url') and r.get('video_id')}
    try:
        images=page.locator('img')
        for i in range(min(images.count(),100)):
            img=images.nth(i)
            if not img.is_visible():continue
            box=img.bounding_box()
            if not box or box['width']<60 or box['height']<60:continue
            external_id=by_url.get(img.evaluate('(i)=>i.currentSrc || i.src')) or img.evaluate(IMAGE_ID)
            if not external_id or not re.fullmatch(r'\d{8,30}',external_id):continue
            if cached_cover(db,'douyin',external_id):continue
            if not img.evaluate('(i)=>i.complete && i.naturalWidth>0'):continue
            save_cover(db,'douyin',external_id,img.screenshot(type='png',timeout=1500),'creator_center_rendered_image')
            captured+=1
    except Exception:
        # A rerender/navigation must not abort metric synchronization.
        pass
    return captured


def fetch_browser_cover(context,db,platform,external_id,url,*,deadline=None):
    """Fetch image bytes through the browser request client, without opening tabs.

    Redirects are followed manually so every hop stays on the platform image CDN.
    A failed request leaves the existing cover intact; no visible-page fallback.
    """
    from urllib.parse import urlparse, urljoin
    domains={'bilibili':('hdslb.com',),'douyin':('douyinpic.com','byteimg.com','ibytedtos.com','pstatp.com')}
    def allowed(value):
        try:
            p=urlparse(value)
            return p.scheme=='https' and not p.username and not p.password and not p.port and any(p.hostname==d or (p.hostname or '').endswith('.'+d) for d in domains.get(platform,()))
        except (TypeError,ValueError):return False
    if not isinstance(url,str) or not allowed(url):return False
    if cover_current(db,platform,external_id,url):return True
    current=url
    for _ in range(4):
        response=None
        try:
            import time
            remaining=8000 if deadline is None else min(8000,int((deadline-time.monotonic())*1000))
            if remaining<=0:return False
            response=context.request.get(current,timeout=remaining,max_redirects=0,headers={'Referer':'https://www.bilibili.com/' if platform=='bilibili' else 'https://creator.douyin.com/'})
            if response.status in (301,302,303,307,308):
                target=urljoin(current,response.headers.get('location',''))
                if not response.headers.get('location') or not allowed(target):return False
                current=target
                continue
            if response.status!=200:return False
            headers=response.headers
            if not headers.get('content-type','').lower().startswith('image/'):return False
            if int(headers.get('content-length','0'))>5_000_000:return False
            data=response.body()
            if len(data)>5_000_000:return False
            save_cover(db,platform,external_id,data,'browser_request_platform_cover',origin_url=url)
            return True
        except Exception:return False
        finally:
            if response is not None:
                try:response.dispose()
                except Exception:pass
    return False


def cache_missing_covers(context,db,platform,rows,*,budget=20,stopped=lambda:False):
    """Bounded fast-sync pass. Never replace an existing or manually supplied cover."""
    import time
    targets={str(r['video_id']):r['cover_url'] for r in rows
             if r.get('video_id') and r.get('cover_url')
             and r.get('visibility') not in ('private','deleted','unlisted')}
    deadline=time.monotonic()+budget
    done=0
    for external_id,url in targets.items():
        if cached_cover(db,platform,external_id):
            done+=1
            continue
        if stopped() or time.monotonic()>=deadline:continue
        if fetch_browser_cover(context,db,platform,external_id,url,deadline=deadline):done+=1
    return done,len(targets)


def count_cached(db,platform,ids):
    init_covers(db)
    with connect(db) as con:known={r['external_id'] for r in con.execute('SELECT external_id FROM hub_covers WHERE platform=?',(platform,))}
    return sum(str(i) in known for i in ids)


def cover_current(db,platform,external_id,url):
    from urllib.parse import urlparse
    if not db:return False
    init_covers(db)
    with connect(db) as con:r=con.execute('SELECT source,origin_url FROM hub_covers WHERE platform=? AND external_id=?',(platform,str(external_id))).fetchone()
    if not r:return False
    if r['source']=='user_upload':return True
    def key(value):
        p=urlparse(str(value or ''));return (p.hostname,p.path.split('@')[0])
    return bool(r['origin_url']) and key(r['origin_url'])==key(url)
