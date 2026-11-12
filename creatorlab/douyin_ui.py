"""One launch path shared by the sidebar and the visual unlock screen."""
import json
import subprocess
import sys
from pathlib import Path
import streamlit as st
from creatorlab.bilibili_import import job_running
from creatorlab.sync_browser import status_write

ROOT=Path(__file__).resolve().parents[1]
ACTIVE={'starting','waiting_login','collecting','recovering','details','covers'}
ACTIVE.update({'navigating','waiting_verification','navigation_needed'})
LABELS={'starting':'正在打开浏览器','waiting_login':'等待登录或进入作品管理','collecting':'正在收集作品','recovering':'正在恢复翻页','details':'正在补齐互动','covers':'正在保存作品封面','review':'采集已保存 · 待核对归属','imported':'已确认入库 · 缺项可继续同步','partial':'部分完成 · 可继续补采','completed':'本轮采集完成','stalled':'翻页暂停','stopped':'已停止','empty':'未读到作品','error':'采集遇到问题','interrupted':'任务已中断 · 数据已保留'}
LABELS.update(navigating='正在自动进入作品管理',waiting_verification='等待用户完成验证',navigation_needed='需要手动进入一次作品管理')


def read_status(root):
    try:data=json.loads((Path(root)/'local'/'sync_status.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    from datetime import datetime,timezone
    try:recent=(datetime.now(timezone.utc)-datetime.fromisoformat(data['updated_at'])).total_seconds()<10
    except (KeyError,ValueError,TypeError):recent=False
    paused_auto=data.get('sync_mode')=='existing' and data.get('state') in ('waiting_login','waiting_verification')
    if not paused_auto and data.get('state') in ACTIVE and not job_running(root,'douyin') and not (data.get('state')=='starting' and recent):
        data={**data,'state':'interrupted','info':'采集进程已退出，已入库作品仍可查看'}
    return data


def launch(db,root=ROOT,repair=False,account_id=None,mode=None):
    import os
    if os.getenv('CREATORLAB_ANALYSIS_ONLY')=='1':raise ValueError('容器模式只支持分析与文件导入；请在本机运行采集窗口')
    root=Path(root)
    from creatorlab.hub import accounts
    own=[a for a in accounts(db) if a['platform']=='douyin' and a['is_self']]
    if account_id is None and len(own)==1:account_id=own[0]['id']
    if not any(a['id']==account_id for a in own):raise ValueError('请先添加并选择本次抖音账号')
    if mode is None:
        from creatorlab.hub import connect
        with connect(db) as con:
            exists=con.execute('SELECT 1 FROM hub_posts WHERE account_id=? LIMIT 1',(account_id,)).fetchone()
        mode='full' if repair or not exists else 'recent'
    if mode not in ('recent','full'):raise ValueError('请选择首页同步或完整扫描')
    if job_running(root,'douyin'):raise ValueError('采集窗口已经打开，不需要重复启动')
    local=root/'local';local.mkdir(exist_ok=True)
    status_write(local/'sync_status.json',state='starting',sync_mode=mode,account_id=account_id,database=str(Path(db).resolve()),count=0,total=None,info='正在打开补采窗口' if repair else '正在打开同步窗口')
    with open(local/'douyin_import.log','a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,'-m','creatorlab.sync_browser','--db',str(db),'--root',str(root),'--account-id',str(account_id),'--mode',mode,'--budget-seconds','600' if repair else '300'],cwd=str(root),stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))


@st.fragment(run_every='3s')
def live_status(root):
    data=read_status(root)
    if not data:return
    from creatorlab.integrity import inventory_audit
    label=LABELS.get(data.get('state'),'等待同步')
    recent=data.get('sync_mode')=='recent'
    automatic=data.get('sync_mode')=='existing'
    if automatic and data.get('state') in ('waiting_login','waiting_verification'):label='自动更新已暂停 · 请先登录或验证'
    if not recent and not automatic and data.get('state') in ('imported','completed') and inventory_audit(data)['external_gap']:label='已有数据已入库 · 全量数量仍未核实'
    st.caption(label)
    count=data.get('count',0);total=data.get('total')
    if automatic:st.caption(f'自动更新：本轮读到 {data.get("refreshed_count",0)} / {data.get("target_count",0)} 条已核对作品 · 不导入新作品')
    elif recent:st.caption(f'本次首页读取 {count} 条 · 新作品 {data.get("new_count",0)} 条 · 未扫描全部历史')
    elif total is not None and total>0:st.progress(min(count/total,1),text=f'已识别 {count} / {total} 条作品')
    else:st.caption(f'已识别 {count} 条作品')
    from creatorlab.integrity import inventory_message,inventory_audit
    if not recent and not automatic and inventory_audit(data)['external_gap']:
        st.warning(inventory_message(data))
    elif not recent and not automatic and isinstance(total,int):st.caption(inventory_message(data))
    if data.get('private_count'):
        from creatorlab.integrity import privacy_notice
        st.caption(privacy_notice(data['private_count']))
    if data.get('cover_targets'):st.caption(f"真实封面缓存 {data.get('with_cover',0)} / {data['cover_targets']} 条（有封面地址且非私密）")
    if data.get('state') not in ACTIVE and data.get('list_end_reason'):
        if recent:st.caption('本轮只读取首页，未进行全量核对。')
        reasons={'inventory_matched':'作品数量已对上','visible_list_exhausted':'源页面当前可见列表已读完，平台总数仍未对齐','user_stopped':'用户停止','browser_closed':'浏览器窗口关闭','list_budget_exhausted':'达到列表采集时间预算','list_stalled':'翻页停滞，重试后仍无新增','capture_error':'采集过程发生错误'}
        if not recent:st.caption('列表结束原因：'+reasons.get(data['list_end_reason'],'需查看诊断'))
    if data.get('state') not in ACTIVE:st.caption(data.get('info',''))
    if data.get('state')=='review' and not automatic:
        st.warning(f'已读到 {data.get("new_count",0)} 条新作品，尚未入库。请在紧接下方的“待核对的抖音采集”确认归属；无需重新扫描。')
    signature=json.dumps([count,data.get('coverage'),data.get('state')],sort_keys=True)
    if 'dy_progress_seen' in st.session_state and st.session_state.dy_progress_seen!=signature:
        st.session_state.dy_progress_seen=signature;st.rerun()
    st.session_state.dy_progress_seen=signature


def actions(db,root=ROOT,key='dy',repair=False,account_id=None,compact=False):
    running=job_running(root,'douyin')
    from creatorlab.hub import connect
    with connect(db) as con:
        has_posts=con.execute('SELECT 1 FROM hub_posts WHERE account_id=? LIMIT 1',(account_id,)).fetchone()
    a,b=st.columns([2,1])
    if a.button('补齐互动数据' if repair else '同步首页作品' if has_posts else '首次导入抖音作品',key=key+'_start',disabled=running,type='primary',width='stretch'):
        try:launch(db,root,repair,account_id);st.toast('正在自动进入作品管理；需要登录或验证时会提示')
        except (OSError,ValueError) as exc:st.error(str(exc))
    if b.button('停止同步',key=key+'_stop',disabled=not running,width='stretch'):
        (Path(root)/'local'/'sync_stop').touch();st.toast('正在保存并停止')
    if not compact:live_status(root)
    if st.button('刷新数据',key=key+'_refresh'):st.rerun()


def sidebar_panel(db,root=ROOT,host=None):
    with (host or st.sidebar).expander('抖音同步',expanded=host is not None):
        from creatorlab.hub import accounts
        own=[a for a in accounts(db) if a['platform']=='douyin' and a['is_self']]
        aid=st.selectbox('本次采集归属',[a['id'] for a in own],format_func=lambda i:next(a['display_name'] for a in own if a['id']==i),key='dy_target_account') if own else None
        if not own:
            st.caption('先添加自己的抖音账号，保存后这里会显示同步入口。')
            return
        st.caption('日常只同步作品管理首页这一批，读取后就入库或核对，不再等待历史翻页。请保持最新发布排序；首次空库会完整导入。登录或验证时需你处理。')
        actions(db,root,key='dy_sidebar',account_id=aid,compact=host is not None)
        with st.expander('完整扫描历史作品'):
            st.caption('首次导入、首页之外还有漏采作品时使用。需要翻页，耗时较长；补齐缺项使用下方任务中心。')
            if st.button('扫描全部历史作品',key='dy_full_scan',disabled=job_running(root,'douyin')):
                try:launch(db,root,account_id=aid,mode='full');st.toast('完整扫描已启动')
                except (OSError,ValueError) as exc:st.error(str(exc))
        with st.expander('采集范围与问题详情'):
            st.caption('首次只需登录，随后自动进入作品管理；页面入口变化时可能需要手动进入一次。同一作者可自动更新；无作者标识时，仅更新此前已核对且ID归属唯一的已有作品，出现新ID则整批待核对。完播率缺失时保留空白。')
            data=read_status(root)
            if data.get('coverage'):st.json(data['coverage'])
            if data.get('warning'):st.caption(data['warning'])


def review_captures(db,root=ROOT):
    from creatorlab.douyin_capture import pending_captures,commit_capture,recover_interrupted
    if not job_running(root,'douyin'):recover_interrupted(db)
    runs=pending_captures(db)
    if not runs:return
    st.markdown('### 待核对的抖音采集')
    merged=sum(len(r.get('duplicate_ids',[])) for r in runs)
    st.caption(f'待核对 {len(runs)} 组作品'+(f' · 已合并 {merged} 批重复范围的采集' if merged else ''))
    for run in runs[:5]:
        with st.expander(run['display_name']+' · '+str(run['count'])+'条作品',expanded=run['id']==runs[0]['id']):
            st.write(f'**包含 {run["new_count"]} 条新作品，确认归属后才能出现在作品库。**')
            st.caption('新作品优先展示。请与采集窗口中的作品及账号核对。')
            st.caption('采集时间：'+run['created_at'])
            if run.get('duplicate_ids'):st.caption(f'同一组作品另有 {len(run["duplicate_ids"])} 次采集，已合并显示；确认一次一并入库，各次观测和原记录保留。')
            st.caption('请对照采集窗口中的登录账号和以下作品。无法确认归属时请勿入库；账号不会自动按列表顺序猜测。')
            st.table([{'作品':r['title'],'播放':r.get('views')} for r in run['preview']])
            if run['owner_key']:st.caption('已捕获一致的作者标识；仍请核对目标账号。')
            st.caption('核对后按作者标识自动更新；没有作者标识时，仅能自动刷新此前已核对且ID归属唯一的已有作品，新增或归属不明仍需核对。')
            checked=st.checkbox('我已核对，这批作品属于 '+run['display_name'],key='capture_check_'+run['id'])
            if st.button('确认归属并入库',disabled=not checked,key='capture_commit_'+run['id'],type='primary'):
                try:
                    n=commit_capture(db,run['id'],run['account_id'])
                    status=read_status(root)
                    same_database=not status.get('database') or Path(status['database']).resolve()==Path(db).resolve()
                    if same_database and status.get('run_id') in [run['id'],*run.get('duplicate_ids',[])]:
                        status_write(Path(root)/'local'/'sync_status.json',**{k:v for k,v in status.items() if k not in ('state','info','updated_at')},state='imported',info='已确认归属并入库')
                    from creatorlab.feedback import notify
                    notify(f'已入库 {n} 条作品，可在作品库查看。');st.rerun()
                except (ValueError,RuntimeError) as exc:st.error(str(exc))
