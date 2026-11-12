const $ = id => document.getElementById(id);
const fields = ['views','likes','comments','shares'];
const setStatus = (msg, good=false) => { $('status').textContent=msg; $('status').style.color=good?'#15803d':'#b45309'; };
chrome.storage.local.get(['bridgeToken','pickedRecord'], data => {
  $('token').value=data.bridgeToken||'';
  if (data.pickedRecord) applyRecord(data.pickedRecord);
});
function parseCount(s) {
  if (!s) return '';
  const m=String(s).replace(/,/g,'').trim().match(/^(\d+(?:\.\d+)?)(万|亿|[wW])?$/);
  if (!m) return '';
  const n=Number(m[1])*(m[2]==='亿'?1e8:(m[2]==='万'||m[2]?.toLowerCase()==='w')?1e4:1);
  return Number.isSafeInteger(Math.round(n)) ? String(Math.round(n)) : '';
}
function matchMetric(txt, words) {
  for(const word of words){
    const esc=word.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    for(const re of [new RegExp(esc+'[：:\\s]*([0-9][0-9,.]*(?:万|亿|w)?)','i'),new RegExp('([0-9][0-9,.]*(?:万|亿|w)?)\\s*'+esc,'i')]){
      const m=txt.match(re);if(m){const v=parseCount(m[1]);if(v)return v;}
    }
  }
  return '';
}
function metricValues(text){
  return {views:matchMetric(text,['播放量','播放次数','播放']),likes:matchMetric(text,['点赞量','点赞']),comments:matchMetric(text,['评论量','评论']),shares:matchMetric(text,['分享量','分享'])};
}
function applyRecord(d){
  if(d.url)$('url').value=d.url;
  if(d.name)$('name').value=d.name.slice(0,150);
  const values=metricValues(d.text||'');
  for (const key of fields) $(key).value=values[key]||'';
  setStatus('已读取所选作品的可见数据。'+(d.url?'已找到独立作品链接。':'当前列表没有暴露独立作品链接：请打开作品并复制链接填入上方，否则无法保存。')+' 请检查四项指标后确认。',!!d.url);
}
function pageSnapshot(){
  return {url:location.href,title:document.title,selected:window.getSelection()?.toString().slice(0,6000)||''};
}
async function activeDouyinTab(){
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.url || !/^https:\/\/([\w-]+\.)?douyin\.com\//.test(tab.url))throw Error('请打开抖音创作者中心或作品详情页');
  return tab;
}
$('read').addEventListener('click',async()=>{
  try{
    const tab=await activeDouyinTab();
    const out=await chrome.scripting.executeScript({target:{tabId:tab.id},func:pageSnapshot});
    const d=out[0].result;
    if (!d.selected){setStatus('作品管理包含多条作品，不能直接识别整页。请使用上方「在页面点选一条作品」。也可先用鼠标选中单条作品的文字后点击本按钮。');return;}
    applyRecord({url:/\/video\/\d+/.test(d.url)?d.url:'',name:'',text:d.selected});
  }catch(e){setStatus(e.message)}
});
// User-initiated one-click picker. No background monitoring or hidden requests.
function installPicker(){
  if(window.__creatorlabPickerCleanup){window.__creatorlabPickerCleanup();}
  const style=document.createElement('style');
  style.textContent='.__cl_hover{outline:3px solid #2563eb!important;outline-offset:2px!important;cursor:crosshair!important}';
  document.documentElement.appendChild(style);
  let hover=null;
  function candidate(target){
    let el=target;
    for(let i=0;i<10&&el&&el!==document.body;i++,el=el.parentElement){
      const t=(el.innerText||'');
      const count=['播放','点赞','评论','分享'].filter(k=>t.includes(k)).length;
      // Aim for one row/card, not the entire feed containing many videos.
      if(count>=3&&t.length>=20&&t.length<=1600)return el;
    }
    return null;
  }
  function move(ev){
    if(hover)hover.classList.remove('__cl_hover');
    hover=candidate(ev.target);
    if(hover)hover.classList.add('__cl_hover');
  }
  function cleanup(){document.removeEventListener('mousemove',move,true);document.removeEventListener('click',click,true);document.removeEventListener('keydown',key,true);if(hover)hover.classList.remove('__cl_hover');style.remove();delete window.__creatorlabPickerCleanup;}
  function key(e){if(e.key==='Escape')cleanup();}
  function click(ev){
    const el=candidate(ev.target);
    if(!el)return;
    ev.preventDefault();ev.stopImmediatePropagation();
    const txt=el.innerText||'';
    const link=el.querySelector('a[href*="/video/"]')||el.closest('a[href*="/video/"]');
    const url=link?.href||'';
    const lines=txt.split('\n').map(s=>s.trim()).filter(Boolean);
    const name=lines.find(s=>s.length>4&&!/^(播放|点赞|评论|分享|收藏|完播|吸粉|编辑作品|置顶|已发布)/.test(s)&&!/^\d+(\.\d+)?(万|亿)?$/.test(s))||'';
    chrome.storage.local.set({pickedRecord:{url,name,text:txt,pickedAt:Date.now()}},()=>{});
    cleanup();
    const toast=document.createElement('div');toast.textContent='✓ CreatorLab 已选中作品。重新打开扩展核对数据。';
    Object.assign(toast.style,{position:'fixed',top:'16px',right:'16px',background:'#166534',color:'white',padding:'12px',zIndex:'2147483647',borderRadius:'8px'});
    document.body.appendChild(toast);setTimeout(()=>toast.remove(),4500);
  }
  window.__creatorlabPickerCleanup=cleanup;
  document.addEventListener('mousemove',move,true);document.addEventListener('click',click,true);document.addEventListener('keydown',key,true);
}
$('pick').addEventListener('click',async()=>{
  try{
    const tab=await activeDouyinTab();
    await chrome.storage.local.remove('pickedRecord');
    await chrome.scripting.executeScript({target:{tabId:tab.id},func:installPicker});
    window.close();
  }catch(e){setStatus(e.message)}
});
$('send').addEventListener('click',async()=>{
  const token=$('token').value.trim();
  if(!token){setStatus('请先填写本地连接密钥');return;}
  const payload={url:$('url').value,name:$('name').value,evidence:'用户在抖音作品管理页选中单条作品后核对的可见数据'};
  if(!/https:\/\/(www\.)?douyin\.com\/video\/\d+/.test(payload.url)){
    setStatus('请先填写此作品的独立视频链接（不是创作者中心的作品管理页网址）');return;
  }
  for(const field of fields){
    const raw=$(field).value.trim();
    if(raw&&!/^\d+$/.test(raw)){setStatus(field+' 必须是整数；未知请留空');return;}
    payload[field]=raw===''?null:Number(raw);
  }
  try{
    const res=await fetch('http://127.0.0.1:8765/import',{method:'POST',headers:{'Content-Type':'application/json','X-CreatorLab-Token':token},body:JSON.stringify(payload)});
    const result=await res.json();
    if(!res.ok){setStatus('导入失败：'+result.error);return;}
    await chrome.storage.local.set({bridgeToken:token});
    await chrome.storage.local.remove('pickedRecord');
    setStatus('已保存到 CreatorLab（作品 #'+result.id+'）。刷新软件页面查看。',true);
  }catch(e){setStatus('无法连接本地服务。请启动 v0.7.1 的 start_windows.bat。');}
});

// Batch mode: extracts only the rendered DOM from the active Creator Center page.
// No cookies, background crawling, network interception, or automatic pagination.
let batchRecords=[];
function collectVisibleCards(){
  const compact = s => (s||'').replace(/\s+/g,' ').trim();
  const metricLabels=['播放','点赞','评论','分享'];
  const nodes=[...document.querySelectorAll('article,li,div')];
  const cards=[];
  for(const node of nodes){
    const text=node.innerText||'';
    if(text.length<35||text.length>1700)continue;
    if(!metricLabels.every(word=>text.includes(word)))continue;
    // Minimum enclosing video block: skip parents which contain a qualifying child.
    const child=[...node.children].some(el=>{
      const t=el.innerText||'';
      return t.length>=35&&t.length<1700&&metricLabels.every(w=>t.includes(w));
    });
    if(child)continue;
    const lines=text.split(/\n+/).map(compact).filter(Boolean);
    // Metric text may be "播放\n1.4万" or "播放 1.4万" or "1.4万\n播放".
    function count(s){const m=compact(s).replace(/,/g,'').match(/^(\d+(?:\.\d+)?)(亿|万|w|W)?$/);if(!m)return null;return Math.round(Number(m[1])*(m[2]==='亿'?1e8:['万','w','W'].includes(m[2])?1e4:1));}
    function metric(word){
      for(let i=0;i<lines.length;i++){
        const line=lines[i];
        for(const re of [new RegExp(word+'[：: ]*(\\d+(?:\\.\\d+)?(?:亿|万|w)?)'),new RegExp('(\\d+(?:\\.\\d+)?(?:亿|万|w)?)\\s*'+word)]){
          const m=line.match(re);if(m){const n=count(m[1]);if(n!==null)return n;}
        }
        if(line===word){for(const adjacent of [lines[i+1],lines[i-1]]){const n=count(adjacent);if(n!==null)return n;}}
      }
      return null;
    }
    const dated=lines.find(x=>/20\d\d[年\-/\.]\d{1,2}[月\-/\.]\d{1,2}/.test(x))||'';
    const title=lines.find(x=>x.length>=5&&!/^20\d\d/.test(x)&&!/(播放|点赞|评论|分享|收藏|完播率|吸粉|置顶|已发布|编辑作品|删除作品|作品管理|数据中心)/.test(x)&&!/^\d+(?:\.\d+)?(?:万|亿)?$/.test(x))||'';
    const url=([...node.querySelectorAll('a[href*="/video/"]')].map(a=>a.href).find(u=>/^https:\/\/(www\.)?douyin\.com\/video\/\d+/.test(u)))||'';
    const record={title:compact(title).slice(0,250),published_at:dated.slice(0,50),url,views:metric('播放'),likes:metric('点赞'),comments:metric('评论'),shares:metric('分享')};
    if(record.title&&[record.views,record.likes,record.comments,record.shares].some(v=>v!==null))cards.push(record);
  }
  const unique=new Map();
  cards.forEach(r=>unique.set(r.title+'|'+r.published_at,r));
  return [...unique.values()].slice(0,100);
}
function renderBatch(){
  $('batchList').replaceChildren();
  $('batchSummary').textContent=batchRecords.length?`识别到 ${batchRecords.length} 条，核对无误后勾选保存。`:'未识别到完整作品卡片。请确认已进入创作者中心的内容管理页，且列表已加载。';
  batchRecords.forEach((r,i)=>{
    const el=document.createElement('div');el.className='item';
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=true;checkbox.dataset.index=i;
    const title=document.createElement('span');title.textContent=r.title;title.style.fontWeight='600';
    const info=document.createElement('small');info.textContent=`${r.published_at||'时间未知'} · 播放 ${r.views??'未知'} · 点赞 ${r.likes??'未知'} · 评论 ${r.comments??'未知'} · 分享 ${r.shares??'未知'}`;
    el.append(checkbox,title,info);$('batchList').append(el);
  });
}
$('batchRead').addEventListener('click',async()=>{
  try{
    const tab=await activeDouyinTab();
    const out=await chrome.scripting.executeScript({target:{tabId:tab.id},func:collectVisibleCards});
    batchRecords=out[0]?.result||[];renderBatch();
  }catch(e){$('batchSummary').textContent='读取失败：'+e.message;}
});
$('batchSend').addEventListener('click',async()=>{
  const token=$('token').value.trim();
  if(!token){setStatus('请在下方填写 CreatorLab 本地连接密钥');return;}
  const rows=[...$('batchList').querySelectorAll('input:checked')].map(el=>batchRecords[Number(el.dataset.index)]);
  if(!rows.length){setStatus('请先读取并勾选需要导入的作品');return;}
  try{
    const res=await fetch('http://127.0.0.1:8765/import-batch',{method:'POST',headers:{'Content-Type':'application/json','X-CreatorLab-Token':token},body:JSON.stringify({rows})});
    const data=await res.json();if(!res.ok)throw Error(data.error||'保存失败');
    await chrome.storage.local.set({bridgeToken:token});
    setStatus(`已导入 ${data.total} 条：新增 ${data.created}，更新 ${data.updated}。请刷新 CreatorLab 的「作品管理」。`,true);
  }catch(e){setStatus('批量导入失败：'+e.message);}
});

// v0.9 passive network sync across pages; live data is never uploaded until user confirms.
let activeTabId=null;
async function activeCenter(){
 const tab=await activeDouyinTab();
 if(!/^https:\/\/creator\.douyin\.com\//.test(tab.url))throw Error('请打开抖音创作者中心');
 activeTabId=tab.id;return tab;
}
async function networkMessage(action){
 const tab=await activeCenter();
 const response=await chrome.runtime.sendMessage({action,tabId:tab.id});
 if(!response?.ok)throw Error(response?.error||'操作失败');return response;
}
async function refreshNetwork(){
 try{
  const data=(await networkMessage('status')).session;
  const rows=data.rows||[];
  const remaining=data.total!==null&&data.total!==undefined?Math.max(0,data.total-rows.length):'未知';
  $('netStatus').textContent=`${data.active?'🟢 正在采集':'⏸ 已暂停'}${data.auto?' · 自动翻页中':''}｜已收集 ${rows.length} / ${data.total??'未知'} 条｜剩余 ${remaining}｜收到 ${data.pages||0} 批响应｜自动操作 ${data.autoSteps||0} 步${data.autoStopReason?'｜停止原因：'+data.autoStopReason:''}${data.errors?'｜提示：'+data.errors:''}`;
  $('netPreview').textContent=rows.slice(-3).map(r=>`${r.title.slice(0,25)} · 播放 ${r.views??'未提供'} · 赞 ${r.likes??'未提供'}`).join('\n');
  return rows;
 }catch(e){$('netStatus').textContent=e.message;return []}
}
$('netStart').addEventListener('click',async()=>{try{const r=await networkMessage('start');setStatus(r.notice||'已开始采集。');await refreshNetwork();}catch(e){setStatus(e.message)}});
$('netStop').addEventListener('click',async()=>{try{await networkMessage('stop');await refreshNetwork();}catch(e){setStatus(e.message)}});
$('netRefresh').addEventListener('click',refreshNetwork);
$('netClear').addEventListener('click',async()=>{if(!confirm('确定清空当前标签页的采集进度？已导入 CreatorLab 的数据不会删除。'))return;try{await networkMessage('clear');await refreshNetwork()}catch(e){setStatus(e.message)}});
async function verifyBridgeToken(){
 const token=$('token').value.trim();
 const el=$('bridgeStatus');
 if(!token){el.textContent='请先粘贴左侧 CreatorLab 显示的本地密钥';return false;}
 try{
   const healthRes=await fetch('http://127.0.0.1:8765/health');
   const health=await healthRes.json();
   if(!healthRes.ok)throw Error('本地服务健康检查失败');
   if(health.version!=='0.9.1'){
     el.textContent=`⚠️ 8765端口运行的是旧版接收服务（${health.version||'未知版本'}）。关闭旧版黑色窗口后重启 v0.9.1。`;
     return false;
   }
   const res=await fetch('http://127.0.0.1:8765/verify',{method:'POST',headers:{'X-CreatorLab-Token':token}});
   if(res.status===401){el.textContent=`❌ 密钥不一致。当前运行的服务指纹：${health.bridge_id}。请确认网页与接收服务都来自同一 v0.9.1 文件夹。`;return false;}
   if(!res.ok)throw Error('密钥检查失败（HTTP '+res.status+'）');
   await chrome.storage.local.set({bridgeToken:token});
   el.textContent=`✅ 连接成功 · 服务版本 ${health.version} · 指纹 ${health.bridge_id}`;
   return true;
 }catch(e){el.textContent='❌ 无法连接本地接收服务：'+e.message+'。请检查 start_windows.bat 的接收服务窗口。';return false;}
}
$('verifyBridge').addEventListener('click',verifyBridgeToken);
$('netSend').addEventListener('click',async()=>{
 try{
  const token=$('token').value.trim();if(!token)throw Error('请先填写本地连接密钥');
  if(!await verifyBridgeToken())throw Error('请先修复上方本地连接状态');
  const rows=await refreshNetwork();if(!rows.length)throw Error('尚未采集到作品。点击开始并刷新抖音内容管理页面。');
  if(!confirm(`确认将 ${rows.length} 条作品及可用指标保存到本机 CreatorLab？`))return;
  let total=0,created=0,updated=0;
  for(let i=0;i<rows.length;i+=100){
   const res=await fetch('http://127.0.0.1:8765/import-batch',{method:'POST',headers:{'Content-Type':'application/json','X-CreatorLab-Token':token},body:JSON.stringify({rows:rows.slice(i,i+100),source:'network'})});
   const data=await res.json();if(!res.ok)throw Error(data.error||'导入失败');
   total+=data.total;created+=data.created;updated+=data.updated;
  }
  await chrome.storage.local.set({bridgeToken:token});
  setStatus(`完成！保存 ${total} 条，新增 ${created}，更新 ${updated}。刷新 CreatorLab 查看。`,true);
 }catch(e){setStatus('同步失败：'+e.message)}
});
refreshNetwork();

$('netAuto').addEventListener('click',async()=>{try{const d=await networkMessage('auto');setStatus(d.notice,true);await refreshNetwork()}catch(e){setStatus(e.message)}});
$('netPauseAuto').addEventListener('click',async()=>{try{await networkMessage('pauseAuto');setStatus('已请求停止自动翻页；已采集数据保留。',true)}catch(e){setStatus(e.message)}});
