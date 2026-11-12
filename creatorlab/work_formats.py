"""Source-observed format metadata, separate from user content categories."""
from urllib.parse import urlparse
from creatorlab.hub import connect


def save_format(db,pid,value):
    if value not in ('video','image'):return
    with connect(db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS clab_work_formats(post_id INTEGER PRIMARY KEY REFERENCES hub_posts(id),media_format TEXT NOT NULL)')
        con.execute('INSERT INTO clab_work_formats VALUES(?,?) ON CONFLICT(post_id) DO UPDATE SET media_format=excluded.media_format',(pid,value))


def formats(db):
    with connect(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='clab_work_formats'").fetchone():return {}
        return {r['post_id']:r['media_format'] for r in con.execute('SELECT * FROM clab_work_formats')}


DY_VISIBLE=r'''() => [...document.querySelectorAll('[class^="video-card-content-"]')].map(c=>{
 const cover=c.querySelector('[class^="video-card-cover-"]');
 const title=c.querySelector('[class^="info-title-text-"]')?.innerText||'';
 const badges=[...(cover?.querySelectorAll('[class^="badge-"]')||[])].map(e=>e.innerText.trim());
 const lines=c.innerText.split(/\n/).map(t=>t.trim());
 const image=badges.some(t=>/^\d+张$/.test(t))||lines.includes('平均浏览图片数');
 const video=badges.some(t=>/^\d+:\d+(?::\d+)?$/.test(t));
 const text=c.innerText;
 const after=label=>{const i=lines.lastIndexOf(label);return i>=0?lines[i+1]:null;};
 const number=t=>t!=null&&/^(?:\d+(?:\.\d+)?|\.\d+)%?$/.test(t)?parseFloat(t)/(t.endsWith('%')?100:1):null;
 const countBadge=badges.find(t=>/^\d+张$/.test(t));
 const date=c.querySelector('[class^="info-time-"]')?.innerText.match(/(\d{4})年(\d{2})月(\d{2})日\s+(\d{2}):(\d{2})/);
 const published=date?new Date(+date[1],+date[2]-1,+date[3],+date[4],+date[5]).toISOString():null;
 return {title,cover_url:cover?.style.backgroundImage?.match(/url\(["']?(.*?)["']?\)/)?.[1]||'',
 published_at:published,
 image_count:image&&!video&&countBadge?parseInt(countBadge):null,
 avg_image_views:image&&!video?number(after('平均浏览图片数')):null,
 swipe_away_rate:image&&!video?number(after('划走率')):null,
 text_expand_rate:image&&!video?number(after('文案展开率')):null,
 visibility:cover?.querySelector('[class^="private-mark-"]')?.innerText.includes('私密')?'private':c.querySelector('[class^="info-status-"]')?.innerText.trim()==='已发布'?'public':null,
 media_format:image&&!video?'image':video&&!image?'video':null};
})'''


def match_visible_metadata(cards,rows):
    """Use unique exact title+cover, or exact title+source publication minute."""
    from creatorlab.measurements import timestamp
    def title(value):return ' '.join(str(value or '').split())
    def minute(value):
        at=timestamp(value)
        return at.replace(second=0,microsecond=0) if at else None
    def identity(value):
        from creatorlab.hub import valid_cover
        if not value or not valid_cover(value):return None
        return urlparse(value).path.split('~',1)[0]
    from collections import Counter
    def placeholder(row):return row.get('title')==f"视频 {row.get('video_id')}"
    index={};dated={};untitled={}
    for row in rows:
        path=identity(row.get('cover_url'))
        text=title(row['title'])
        if path:index.setdefault((text,path),[]).append(row)
        at=minute(row.get('published_at'))
        if text and at:dated.setdefault((text,at),[]).append(row)
        if placeholder(row) and path and at:untitled.setdefault((path,at),[]).append(row)
    card_keys=Counter((identity(c.get('cover_url')),minute(c.get('published_at'))) for c in cards)
    updates=[]
    for card in cards:
        path=identity(card.get('cover_url'))
        text=title(card.get('title'))
        candidates=index.get((text,path),[]) if path else []
        if not candidates:
            at=minute(card.get('published_at'))
            candidates=dated.get((text,at),[]) if text and at else []
        if not candidates:
            at=minute(card.get('published_at'))
            key=(path,at)
            # Only the collector's exact ID placeholder may use this route.
            # Both source cards and stored rows must uniquely share cover+minute.
            if path and at and card_keys[key]==1:candidates=untitled.get(key,[])
        if len(candidates)!=1:continue
        row=candidates[0];fields={k:card.get(k) for k in ('visibility','media_format') if card.get(k) in ('private','public','video','image') and card.get(k)!=row.get(k)}
        from creatorlab.image_reading import FIELDS,valid
        if card.get('media_format')=='image' and card.get('visibility')=='public':
            observed={k:card[k] for k in FIELDS if valid(k,card.get(k))}
            if any(v!=row.get(k) for k,v in observed.items()):fields.update(observed)
        restored=text if placeholder(row) and text and len(text)<=500 else row['title']
        if fields or restored!=row['title']:updates.append({'video_id':row['video_id'],'title':restored,**fields})
    return updates


DY_LIST_EVIDENCE=r'''() => {
 const list=document.querySelector('[class^="list-scroll-"]');
 if(!list)return {count:null,ended:false};
 return {count:list.querySelectorAll('[class^="video-card-content-"]').length,
 ended:/没有更多作品\s*$/.test(list.innerText||'')};
}'''


def visible_list_exhausted(identified,rejected,evidence):
    return bool(isinstance(evidence,dict) and evidence.get('ended') is True and evidence.get('count')==identified and identified>0 and rejected==0)


def preserve_confirmed_formats(incoming,known):
    """Public detail payloads cannot override creator-list format evidence."""
    result=[]
    for r in incoming:
        old=known.get(r.get('video_id'),{}).get('media_format')
        result.append(dict(r,media_format=old) if old in ('video','image') else r)
    return result
