// CreatorLab v0.9: capture only work_list JSON responses received by the user-opened
// Douyin Creator Center tab. Explicit start/stop; no requests or credentials are sent.
const sessions = new Map();
const allowed = url => /^https:\/\/creator\.douyin\.com\//.test(url||'');
const itemURL = u => { try { return new URL(u).pathname.includes('work_list'); } catch { return false; } };
const safeNum = v => { if (v===null||v===undefined||v==='') return null; const n=Number(v); return Number.isFinite(n)&&n>=0 ? n : null; };
const whole = v => {const n=safeNum(v);return n===null?null:Math.round(n)};
function coverValue(v){
 if(typeof v==='string')return /^https:\/\//.test(v)?v:null;
 if(Array.isArray(v))return v.map(coverValue).find(Boolean)||null;
 if(v&&typeof v==='object')return coverValue(v.url_list)||coverValue(v.url);
 return null;
}
function normalizeItem(i){
 const m=i.metrics||{};
 const id=String(i.id||i.aweme_id||'');
 if(!/^\d{8,30}$/.test(id))return null;
 const ts=Number(i.create_time);
 const at=Number.isFinite(ts)&&ts>0 ? new Date(ts*(ts>1e12?1:1000)).toISOString() : '';
 return {video_id:id,title:String(i.description||i.desc||i.title||'').trim().slice(0,250)||`视频 ${id}`,
  cover_url:coverValue(i.cover)||coverValue(i.video_cover)||coverValue(i.cover_url)||coverValue(i.video?.cover)||coverValue(i.video?.origin_cover)||coverValue(i.video?.dynamic_cover),
  published_at:at, url:`https://www.douyin.com/video/${id}`,
  views:whole(m.play_count??m.play_count_total??m.total_play_count??m.view_count),
  likes:whole(m.like_count??m.digg_count),comments:whole(m.comment_count),shares:whole(m.share_count),
  avg_view_second:safeNum(m.avg_view_second),avg_view_proportion:safeNum(m.avg_view_proportion),
  bounce_rate_2s:safeNum(m.bounce_rate_2s),completion_rate:safeNum(m.completion_rate),
  completion_rate_5s:safeNum(m.completion_rate_5s)};
}
function parseResponse(raw){
 // JSON numeric Douyin IDs are often > Number.MAX_SAFE_INTEGER. Preserve decimal IDs
 // by rewriting only id/aweme_id to JSON strings BEFORE JSON.parse.
 const preserved=raw.replace(/("(?:id|aweme_id)"\s*:\s*)(\d{16,30})(?=\s*[,}\]])/g,'$1"$2"');
 const payload=JSON.parse(preserved);
 const root=payload?.data?.items?payload.data:payload?.items?payload:payload?.data?.data?.items?payload.data.data:null;
 if(!root||!Array.isArray(root.items))return null;
 const rows=root.items.map(normalizeItem).filter(Boolean);
 return {rows,total:Number(root.total)||null,hasMore:root.has_more===true||root.has_more===1,cursor:String(root.max_cursor??'')};
}
async function persist(tabId){
 const s=sessions.get(tabId);if(!s)return;
 const rows=[...s.rows.values()];
 await chrome.storage.local.set({['clSession_'+tabId]:{rows,total:s.total,hasMore:s.hasMore,pages:s.pages,active:true,lastAt:Date.now(),errors:s.errors,auto:!!s.auto,autoSteps:s.autoSteps||0,autoStagnant:s.autoStagnant||0,autoStopReason:s.autoStopReason||''}});
}
async function detach(tabId){
 const s=sessions.get(tabId);if(!s)return;
 sessions.delete(tabId);
 try{await chrome.debugger.detach({tabId});}catch{}
 await chrome.storage.local.set({['clSession_'+tabId]:{rows:[...s.rows.values()],total:s.total,hasMore:s.hasMore,pages:s.pages,active:false,lastAt:Date.now(),errors:s.errors,auto:!!s.auto,autoSteps:s.autoSteps||0,autoStagnant:s.autoStagnant||0,autoStopReason:s.autoStopReason||''}});
}
// Optional and bounded: interacts with visible page controls only. No private API calls.
// Navigate only the UI the creator has already opened. Never replay private endpoints.
function advanceVisiblePage(){
 const buttons=[...document.querySelectorAll('button,[role="button"],a')];
 const next=buttons.find(b=>{
   const label=[b.innerText,b.getAttribute('aria-label'),b.getAttribute('title')].filter(Boolean).join(' ').trim();
   return /^(下一页|下一页\s*[›>]|next(?: page)?|下页)$/i.test(label)
     && !b.disabled && b.getAttribute('aria-disabled')!=='true';
 });
 if(next){next.click();return {kind:'next',moved:true};}
 const nodes=[...document.querySelectorAll('div,main,section,[role="main"]')];
 const candidates=nodes.filter(e=>{
   const st=getComputedStyle(e);
   return e.scrollHeight>e.clientHeight+80 && e.clientHeight>150 && /(auto|scroll)/.test(st.overflowY);
 }).map(e=>{
   const txt=(e.innerText||'').slice(0,12000);
   const signals=['播放','点赞','评论','分享','作品','已发布'].filter(w=>txt.includes(w)).length;
   return {e,signals,area:e.clientHeight,remaining:e.scrollHeight-e.clientHeight-e.scrollTop};
 }).sort((a,b)=>(b.signals*100000+b.area)-(a.signals*100000+a.area));
 for(const {e} of candidates.slice(0,8)){
   const before=e.scrollTop;
   const delta=Math.max(250,Math.round(e.clientHeight*0.72));
   e.scrollTop=Math.min(e.scrollTop+delta,e.scrollHeight-e.clientHeight);
   if(e.scrollTop>before+2)return {kind:'scroll',moved:true};
 }
 const before=window.scrollY;
 window.scrollBy(0,Math.max(320,Math.round(innerHeight*0.72)));
 return {kind:'window-scroll',moved:window.scrollY>before+2};
}

function visibleCoverLinks(){
 const found=[];
 for(const img of document.querySelectorAll('img')){
  const src=img.currentSrc||img.src;
  if(!/^https:\/\//.test(src||'')||!img.complete||img.naturalWidth<60)continue;
  for(let p=img,d=0;p&&d<6;p=p.parentElement,d++){
   const ids=new Set();
   for(const el of [p,...p.querySelectorAll('[data-aweme-id],[data-video-id],a[href]')]){
    for(const attr of ['data-aweme-id','data-video-id']){const v=el.getAttribute(attr);if(/^\d{8,30}$/.test(v||''))ids.add(v);}
    const m=(el.getAttribute('href')||'').match(/\/video\/(\d{8,30})(?:\D|$)/);if(m)ids.add(m[1]);
   }
   if(ids.size>1)break;
   if(ids.size===1){found.push({id:[...ids][0],url:src});break;}
  }
 }
 return found;
}
async function enrichVisibleCovers(tabId){
 const session=sessions.get(tabId);if(!session)return;
 try{
  const result=await chrome.scripting.executeScript({target:{tabId},func:visibleCoverLinks});
  for(const {id,url} of result?.[0]?.result||[]){const row=session.rows.get(id);if(row&&!row.cover_url)row.cover_url=url;}
 }catch{}
}

const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function autoAdvance(tabId){
 const s=sessions.get(tabId);if(!s||s.autoRunning)return;
 s.autoRunning=true;s.auto=true;s.autoStopReason='';
 let stagnant=0, noMove=0;
 try{
  for(let step=0;step<110 && s.auto;step++){
   const tab=await chrome.tabs.get(tabId);
   if(!allowed(tab.url)){s.autoStopReason='已离开抖音创作者中心';break;}
   const before=s.rows.size;
   await enrichVisibleCovers(tabId);
   const action=await chrome.scripting.executeScript({target:{tabId},func:advanceVisiblePage});
   const moved=action?.[0]?.result?.moved===true;
   noMove=moved?0:noMove+1;
   // DOM changes are asynchronous. Await a few short intervals for network capture.
   for(let poll=0;poll<3&&s.auto;poll++){
     await delay(500);
     if(s.rows.size>before)break;
   }
   stagnant=s.rows.size>before?0:stagnant+1;
   s.autoSteps=step+1;
   s.autoStagnant=stagnant;
   if(step%3===0)await persist(tabId);
   if(s.total&&s.rows.size>=s.total){s.autoStopReason='已达到后台报告的作品总数';break;}
   if(stagnant>=10&&noMove>=3){s.autoStopReason='当前列表没有更多可滚动内容或新响应';break;}
   if(stagnant>=16){s.autoStopReason='连续多次未收到新的作品响应；请手动翻页后重试';break;}
  }
  if(!s.autoStopReason && s.auto)s.autoStopReason='已达到单次自动操作上限（110步），可以继续手动翻页';
 }catch(e){s.autoStopReason='自动翻页异常：'+String(e.message||e).slice(0,100);}
 finally{s.auto=false;s.autoRunning=false;await persist(tabId);}
}
chrome.debugger.onEvent.addListener(async(source,method,params)=>{
 const s=sessions.get(source.tabId);if(!s)return;
 if(method==='Network.responseReceived'&&params?.response?.status===200&&itemURL(params.response.url))s.pending.add(params.requestId);
 if(method==='Network.loadingFinished'&&s.pending.delete(params.requestId)){
  try{
   const r=await chrome.debugger.sendCommand({tabId:source.tabId},'Network.getResponseBody',{requestId:params.requestId});
   const json=r.base64Encoded?atob(r.body):r.body;
   if(json.length>1500000)return;
   const result=parseResponse(json);if(!result)return;
   for(const row of result.rows)s.rows.set(row.video_id,row);
   s.pages+=1;s.total=result.total||s.total;s.hasMore=result.hasMore;
   await persist(source.tabId);
  }catch(e){s.errors=String(e.message||e).slice(0,150);await persist(source.tabId);}
 }
});
chrome.debugger.onDetach.addListener(async(source)=>{
 const s=sessions.get(source.tabId);if(!s)return;
 sessions.delete(source.tabId);
 await chrome.storage.local.set({['clSession_'+source.tabId]:{rows:[...s.rows.values()],total:s.total,hasMore:s.hasMore,pages:s.pages,active:false,lastAt:Date.now(),errors:'调试会话已断开'}});
});
chrome.tabs.onRemoved.addListener(tabId=>{detach(tabId)});
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
 (async()=>{
  if(!Number.isInteger(msg.tabId))throw Error('无效标签页');
  const tab=await chrome.tabs.get(msg.tabId);
  if(msg.action==='start'){
   if(!allowed(tab.url))throw Error('请在 creator.douyin.com 创作者中心使用');
   if(sessions.has(tab.id))return {ok:true};
   const old=await chrome.storage.local.get('clSession_'+tab.id);
   const prev=old['clSession_'+tab.id]||{};
   await chrome.debugger.attach({tabId:tab.id},'1.3');
   await chrome.debugger.sendCommand({tabId:tab.id},'Network.enable',{});
   sessions.set(tab.id,{rows:new Map((prev.rows||[]).map(r=>[r.video_id,r])),pending:new Set(),total:prev.total||null,pages:prev.pages||0,hasMore:true,errors:''});
   await persist(tab.id);
   return {ok:true,notice:'已启动。请在页面切换到内容管理或刷新以触发作品列表。'};
  }
  if(msg.action==='auto'){const s=sessions.get(tab.id);if(!s)throw Error('请先点击开始跨页采集');autoAdvance(tab.id);return {ok:true,notice:'自动翻页已启动；最多110次界面操作，持续无新数据才会停止。请刷新采集进度查看原因。'};}
  if(msg.action==='pauseAuto'){const s=sessions.get(tab.id);if(s){s.auto=false;s.autoStopReason='用户主动停止';}return {ok:true};}
  if(msg.action==='stop'){const s=sessions.get(tab.id);if(s)s.auto=false;await detach(tab.id);return {ok:true};}
  if(msg.action==='clear'){await detach(tab.id);await chrome.storage.local.remove('clSession_'+tab.id);return {ok:true};}
  if(msg.action==='status'){await enrichVisibleCovers(tab.id);if(sessions.has(tab.id))await persist(tab.id);const data=await chrome.storage.local.get('clSession_'+tab.id);return {ok:true,session:data['clSession_'+tab.id]||{rows:[],total:null,pages:0,active:false}};}
  throw Error('未知操作');
 })().then(reply).catch(e=>reply({ok:false,error:String(e.message||e)}));
 return true;
});
