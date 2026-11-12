"""One account-scoped answer to: is it saved, when did it change, what next?"""
import json
from datetime import datetime
import streamlit as st
from creatorlab.hub import connect,accounts


def summarize(db,platform,account_id=None,status=None):
    own=[a for a in accounts(db) if a['is_self'] and a['platform']==platform]
    chosen=next((a for a in own if a['id']==account_id),own[0] if own else None)
    data=dict(status or {})
    if chosen and ((data.get('account_id') is not None and data['account_id']!=chosen['id']) or
                   (platform=='bilibili' and data.get('uid') and str(data['uid'])!=str(chosen['handle']))):data={}
    stored=0;last_saved=None;pending=set();known=set();groups=0
    if chosen:
        with connect(db) as con:
            posts=con.execute('SELECT external_id,last_synced FROM hub_posts WHERE account_id=? AND demo=0',(chosen['id'],)).fetchall()
            stored=len(posts);known={r['external_id'] for r in posts}
            last_saved=max((r['last_synced'] for r in posts if r['last_synced']),default=None)
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clab_dy_runs'").fetchone()
            if platform=='douyin' and exists:
                runs=con.execute("SELECT id,owner_key FROM clab_dy_runs WHERE account_id=? AND state='review'",(chosen['id'],)).fetchall()
                signatures=set()
                for run in runs:
                    ids={r[0] for r in con.execute('SELECT DISTINCT video_id FROM clab_dy_events WHERE run_id=?',(run['id'],))}
                    pending.update(ids)
                    owner=json.dumps(json.loads(run['owner_key'] or '{}'),sort_keys=True)
                    signatures.add((owner,tuple(sorted(ids))))
                groups=len(signatures)
    new=len(pending-known);state=data.get('state');automatic=data.get('sync_mode')=='existing'
    title='作品已入库，可以查看分析';action='到“看作品”选择一条作品，或继续同步更新。';tone='success'
    if not chosen:
        title='先添加自己的账号';action='添加账号后同步作品；也可以先回“看作品”浏览示例。';tone='info'
    elif state in ('waiting_login','waiting_verification'):
        title='自动更新已暂停' if automatic else '需要你完成登录或验证'
        action='先手动同步完成登录或验证，再保存自动更新设置恢复。' if automatic else '在独立采集窗口完成登录或验证，完成后继续读取。'
        tone='warning'
    elif state in ('starting','navigating','navigation_needed','collecting','recovering','details','covers','creator'):
        title='后台正在更新已有作品' if automatic else '正在读取作品，请稍候'
        if state=='navigation_needed':title='请进入作品管理';action='在采集窗口手动进入一次作品管理，识别成功后会继续。';tone='warning'
        else:action='可以继续浏览已有作品；本轮完成后会自动刷新这里。';tone='info'
    elif new:
        title='新作品已读到，还差归属确认';action='在下方核对账号并点击“确认归属并入库”，不用重新扫描。';tone='warning'
    elif state in ('error','interrupted','stalled'):
        title='本轮更新未完成，已有数据保留';action='展开“任务详情与缺项补采”查看原因，处理后再同步。';tone='warning'
    elif state=='stopped':
        title='本轮已停止，已有数据保留';action='已入库作品可以继续查看；需要继续时再同步或补采。';tone='info'
    elif not stored:
        title='账号已添加，下一步导入作品';action='在下方同步作品；也可到“账号与文件导入”导入CSV或手动添加。';tone='info'
    elif state=='partial':
        title='作品已保存，还有部分数据待补齐';action='可以先看已有表现；需要补齐时展开下方任务详情。';tone='info'
    elif state in ('imported','completed'):
        title='已有作品数据已更新' if automatic else '本轮作品已入库，可以查看分析'
        action='到“看作品”查看最新表现；未读到的指标仍保留原观测时间。'
    return dict(title=title,action=action,tone=tone,stored=stored,pending_new=new,pending_groups=groups,
                last_saved=last_saved,account_id=chosen['id'] if chosen else None,
                account_name=chosen['display_name'] if chosen else '',status=data)


def local_time(value):
    if not value:return '尚未入库'
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except (ValueError,TypeError):return '时间未知'


@st.fragment(run_every='3s')
def panel(db,root,platform):
    from creatorlab.task_ui import task_status
    aid=st.session_state.get('dy_target_account') if platform=='douyin' else None
    if platform=='bilibili':
        uid=st.session_state.get('bili_import_uid')
        try:
            from creatorlab.bilibili_import import parse_uid
            uid=parse_uid(uid)
        except (ValueError,TypeError):uid=None
        aid=next((a['id'] for a in accounts(db) if a['platform']==platform and a['is_self'] and a['handle']==uid),None)
    try:result=summarize(db,platform,aid,task_status(root,platform,db))
    except RuntimeError:
        st.info('正在保存本轮数据，请稍候。已有作品保留，保存结束后这里会自动刷新。')
        return
    automatic={}
    if platform=='douyin' and result['account_id']:
        from creatorlab.auto_update import load
        automatic=load(db).get(str(result['account_id']),{})
        if automatic.get('enabled') and automatic.get('paused') and not result['status'].get('running') and not result['pending_new']:
            result.update(title='自动更新已暂停',action='先手动同步完成登录、验证或归属核对，再保存自动更新设置恢复。',tone='warning')
    with st.container(border=True):
        st.subheader(result['title'])
        if result['account_name']:st.caption('当前账号：'+result['account_name'])
        a,b=st.columns(2)
        a.metric('已入库作品',result['stored']);b.metric('待确认新作品',result['pending_new'])
        st.write('**下一步：'+result['action']+'**')
        st.caption('最近入库更新：'+local_time(result['last_saved'])+' · 本机时间')
        if platform=='douyin':
            label='已暂停' if automatic.get('enabled') and automatic.get('paused') else ('已开启 · '+('每天一次' if automatic.get('hours')==24 else f'每{automatic.get("hours")}小时') if automatic.get('enabled') else '未开启')
            st.caption('自动更新：'+label)
        if result['pending_groups'] and not result['pending_new']:
            st.caption(f'另有 {result["pending_groups"]} 组历史采集记录待核对，已有作品仍可正常查看。')
        data=result['status']
        if not data.get('running') and data.get('cover_targets') and data.get('with_cover',0)<data['cover_targets']:
            st.caption('部分封面暂未缓存，作品数据已保留；下次同步会重试。')
        if data.get('running') and data.get('count') is not None:
            st.caption(f'本轮已读到 {data["count"]} 条；读取进度不等于入库数量。')
        if not result['account_id']:
            if st.button('添加账号',key='task_first_account',type='primary'):
                from creatorlab.workspace import route,SETTINGS
                route(SETTINGS,settings_view='账号与文件导入',settings_import_method='sync')
    signature=json.dumps([result['account_id'],data.get('state'),data.get('running'),result['stored'],result['pending_new'],result['pending_groups'],result['last_saved'],automatic.get('paused'),automatic.get('last_success')])
    key='_task_overview_'+platform
    old=st.session_state.get(key);st.session_state[key]=signature
    if old is not None and old!=signature:st.rerun()
