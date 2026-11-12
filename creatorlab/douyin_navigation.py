"""Navigate the visible creator UI; never guess a private API or a login step."""
import json
from pathlib import Path
from urllib.parse import urlsplit

CENTER = 'https://creator.douyin.com/'
MENU_LABELS = ('作品管理', '视频管理', '内容管理')

# Only rendered labels/links are inspected. No cookies, tokens or page internals.
NAV_EVIDENCE = r"""() => {
  const visible=e=>!!(e.getClientRects().length && getComputedStyle(e).visibility!=='hidden');
  const candidates=[...document.querySelectorAll('a,button,[role="button"],[role="menuitem"],span,div')]
    .filter(visible).filter(e=>['作品管理','视频管理','内容管理'].includes((e.innerText||'').trim()))
    .map(e=>({label:e.innerText.trim(),href:e.closest('a')?.href||''}));
  const text=(document.body?.innerText||'').slice(0,30000);
  return {candidates, verification:/请完成.{0,8}验证|拖动.{0,8}滑块|安全验证/.test(text),
    login:/扫码登录|扫描二维码登录|手机号登录|验证码登录|登录抖音创作者中心/.test(text)
      || (!candidates.length && [...document.querySelectorAll('button,[role="button"]')]
        .some(e=>visible(e) && /^(登录|立即登录|登录\/注册)$/.test((e.innerText||'').trim())))};
}"""


def safe_manager_url(value):
    """Remember just a same-origin path, never auth/query material."""
    if not isinstance(value,str):return None
    try:p=urlsplit(value)
    except ValueError:return None
    if p.scheme!='https' or p.netloc!='creator.douyin.com':return None
    if p.path in ('','/') or any(x in p.path.lower() for x in ('login','auth','logout')):return None
    if p.query or p.fragment:return None
    return CENTER.rstrip('/')+p.path


class CreatorNavigator:
    def __init__(self,root,account_id):
        self.path=Path(root)/'local'/f'douyin_navigation_{int(account_id)}.json'
        self.attempted={};self.last_step=-10;self.last_click=-10
        self.started_at=None;self.last_state='navigating';self.remembered=False

    def entry_url(self):
        try:return safe_manager_url(json.loads(self.path.read_text()).get('manager_url')) or CENTER
        except (OSError,ValueError,AttributeError):return CENTER

    def remember(self,page):
        if self.remembered:return
        url=safe_manager_url(page.url)
        if url:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.path.write_text(json.dumps({'manager_url':url}),encoding='utf-8')
            self.remembered=True

    def step(self,page,now,has_list=False):
        if now-self.last_step<3:return self.last_state
        self.last_step=now
        if self.started_at is None:self.started_at=now
        try:evidence=page.evaluate(NAV_EVIDENCE)
        except Exception:return self.last_state
        if not isinstance(evidence,dict):return self.last_state
        # A login/verification wall must remain entirely user-operated.
        if evidence.get('verification'):
            self.started_at=now;self.last_state='waiting_verification';return self.last_state
        if evidence.get('login'):
            self.started_at=now;self.last_state='waiting_login';return self.last_state
        try:origin=urlsplit(page.url)
        except ValueError:origin=None
        if not origin or origin.scheme!='https' or origin.netloc!='creator.douyin.com':
            self.last_state='navigation_needed';return self.last_state
        if has_list:
            self.remember(page)
            self.last_state='collecting';return 'collecting'
        candidates=evidence.get('candidates') or []
        for label in MENU_LABELS:
            if not any(isinstance(c,dict) and c.get('label')==label for c in candidates):continue
            key=(page.url,label)
            if self.attempted.get(key,0)>=2 or now-self.last_click<8:continue
            self.attempted[key]=self.attempted.get(key,0)+1
            self.last_click=now
            try:
                # Click only a visible exact label on the official origin.
                for element in page.get_by_text(label,exact=True).all():
                    if element.is_visible():
                        href=element.evaluate("e=>e.closest('a')?.href||''")
                        if href:
                            target=urlsplit(href)
                            if target.scheme!='https' or target.netloc!='creator.douyin.com':continue
                        element.click(timeout=1500)
                        self.last_state='navigating';return self.last_state
            except Exception:pass
        self.last_state='navigation_needed' if now-self.started_at>=30 else 'navigating'
        return self.last_state


NAV_MESSAGES={
    'navigating':'正在自动进入作品管理；通常无需手动切换页面',
    'waiting_login':'请在采集窗口登录，成功后CLab会自动进入作品管理',
    'waiting_verification':'请在采集窗口完成验证，完成后自动继续；CLab不会代填',
    'navigation_needed':'未能自动找到作品管理入口，请在采集窗口进入一次；成功后将记住该页面',
}
