"""Safe public video URL recognition and optional TikTok oEmbed metadata."""
import json
import re
from urllib.parse import urlparse, urlunparse, parse_qs
from urllib.request import Request, urlopen

ALLOWED = {"www.tiktok.com", "tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "www.douyin.com", "douyin.com", "v.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}
URL_PATTERN = re.compile(r"https?://[^\s<>\"'，。]+")

class LinkError(ValueError): pass

def parse_video_link(text):
    match = URL_PATTERN.search(text.strip())
    if not match: raise LinkError("未找到有效的 https 视频链接 / No valid video URL found")
    url = match.group(0).rstrip('.,;!)]}')
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or host not in ALLOWED or parsed.username or parsed.password or parsed.port:
        raise LinkError('仅支持 TikTok / 抖音官方 HTTPS 链接 / Only official HTTPS links are supported')
    platform = 'tiktok' if 'tiktok.com' in host else 'douyin'
    video_id = None
    if platform == 'tiktok':
        m = re.search(r'/video/(\d+)',parsed.path)
        if m: video_id = m.group(1)
    else:
        m = re.search(r'/video/(\d+)',parsed.path)
        if m: video_id = m.group(1)
        elif 'modal_id' in parse_qs(parsed.query): video_id = parse_qs(parsed.query)['modal_id'][0]
    # Keep short share links intact. No untrusted redirect-following.
    canonical = f'https://{host}{parsed.path}'
    if not parsed.path or parsed.path == '/': raise LinkError('请输入具体作品的分享链接 / A video link is required')
    if platform == 'douyin' and video_id and 'modal_id' in parse_qs(parsed.query):
        canonical = f'https://www.douyin.com/video/{video_id}'
    return {'platform':platform,'url':canonical,'video_id':video_id}

def fetch_tiktok_oembed(url, timeout=5):
    """Best-effort public title/thumbnail; not analytics. No arbitrary URL fetches."""
    info = parse_video_link(url)
    if info['platform'] != 'tiktok' or not info['video_id']:
        return {}
    from urllib.parse import urlencode
    endpoint = 'https://www.tiktok.com/oembed?' + urlencode({'url':info['url']})
    try:
        req = Request(endpoint,headers={'User-Agent':'CreatorLabAI/0.5'})
        with urlopen(req,timeout=timeout) as res:
            data = json.load(res)
        return {'title':str(data.get('title') or '')[:300], 'author':str(data.get('author_name') or '')[:120], 'thumbnail_url':str(data.get('thumbnail_url') or '')}
    except (OSError, ValueError, KeyError, TimeoutError):
        return {}
