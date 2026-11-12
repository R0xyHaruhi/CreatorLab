"""One monitor for user-started local collection tasks, backed by disk status."""
import json
from pathlib import Path
from datetime import datetime, timezone
import streamlit as st
from creatorlab.bilibili_import import job_running

ACTIVE = {'starting','waiting_login','collecting','recovering','details','creator','covers'}
ACTIVE.update({'navigating','waiting_verification','navigation_needed'})
LABELS = {'starting':'正在启动','waiting_login':'等待登录、验证或页面加载','collecting':'正在读取作品',
          'recovering':'正在恢复翻页','details':'正在补齐指标','creator':'等待创作中心','covers':'正在缓存封面',
          'review':'待核对归属','imported':'已确认入库','completed':'本轮完成','partial':'部分完成',
          'empty':'未取得作品','stopped':'已停止','stalled':'翻页暂停','error':'需要处理','interrupted':'任务已中断'}
LABELS.update(navigating='正在自动进入作品管理',waiting_verification='等待用户完成验证',navigation_needed='需要手动进入一次作品管理')


def task_status(root, platform, db=None):
    name = 'bilibili_sync_status.json' if platform=='bilibili' else 'sync_status.json'
    try:
        data = json.loads((Path(root)/'local'/name).read_text(encoding='utf-8'))
        if not isinstance(data,dict):return {}
    except (ValueError,OSError):return {}
    if db and data.get('database') and str(Path(db).resolve())!=data['database']:return {}
    running = job_running(root, platform)
    try:recent=(datetime.now(timezone.utc)-datetime.fromisoformat(data['updated_at'])).total_seconds()<15
    except (ValueError,KeyError,TypeError):recent=False
    paused_auto=data.get('sync_mode')=='existing' and data.get('state') in ('waiting_login','waiting_verification')
    if not paused_auto and data.get('state') in ACTIVE and not running and not (data.get('state')=='starting' and recent):
        data=dict(data,state='interrupted',info='进程已退出。已保存的数据保留，可核对入库或补采缺项。')
    return dict(data,running=running)


@st.fragment(run_every='3s')
def task_center(db, root, platform,show_review=True):
    from creatorlab.hub import accounts
    from creatorlab.feedback import notify
    st.subheader('采集任务中心')
    data=task_status(root,platform,db)
    if not data:
        st.info('当前平台暂无采集任务。在“同步与设置”启动同步后，可在这里查看进度。')
    else:
        from creatorlab.integrity import inventory_audit
        recent=data.get('sync_mode')=='recent'
        automatic=data.get('sync_mode')=='existing'
        label=LABELS.get(data.get('state'),'状态待确认')
        if automatic and data.get('state') in ('waiting_login','waiting_verification'):label='自动更新已暂停 · 请先登录或验证'
        if not recent and not automatic and data.get('state') in ('imported','completed') and inventory_audit(data)['external_gap']:label='已入库，完整性仍待核实'
        st.write('状态：'+label)
        st.caption('更新于 '+str(data.get('updated_at') or '未知'))
        a,b,c=st.columns(3)
        count=data.get('count',0);total=data.get('total')
        if automatic:a.metric('本轮读取到的已入库作品',f'{data.get("refreshed_count",0)} / {data.get("target_count",0)}')
        else:a.metric('本次首页作品' if recent else '已识别作品',str(count) if recent else f'{count} / {total if total is not None else "总数未知"}')
        b.metric('已访问详情页',data.get('details',0))
        c.metric('已缓存封面',data.get('with_cover',0))
        if automatic:st.caption('后台仅更新已核对的已有作品；未读取到的指标保留原观测时间，不宣称全量刷新。')
        elif recent:st.caption(f'新作品 {data.get("new_count",0)} 条 · 本轮未扫描全部历史，不代表全量采齐。')
        elif isinstance(total,(int,float)) and total>0:st.progress(min(1,count/total),text='作品清单进度（不代表全部字段已齐）')
        if data.get('phase_total'):st.caption(f"详情补全：{data.get('details',0)} / {data['phase_total']}")
        st.caption(data.get('info',''))
        if data.get('private_count'):
            from creatorlab.integrity import privacy_notice
            st.info(privacy_notice(data['private_count'],platform))
        from creatorlab.integrity import inventory_audit
        audit=inventory_audit(data)
        if not recent and not automatic and audit['visible_verified']:
            st.caption(f"源页面可见清单已核对：{audit['count']} 条，页面已显示到底。")
            if audit['external_gap']:st.warning(f"平台标称总数与可见清单相差 {audit['external_gap']} 条，原因未确认。这是待核对的数量差异，不能当作已经采齐。")
        if data.get('warning'):st.warning(data['warning'])
        if data.get('state')=='waiting_login':st.info('请在采集窗口完成登录或验证码，CLab不会代填。')
        if data.get('state')=='waiting_verification':st.info('请在采集窗口完成验证，完成后自动继续。')
        if data.get('state')=='navigation_needed':st.info('未识别到管理入口。请手动进入一次作品管理；成功后将记住该页面。')
        with st.expander('数据覆盖与缺项'):
            st.caption('以下统计不含已确认私密、删除或不可公开作品。字段有值不代表整条作品可评分。')
            st.table([{'字段':k,'有效条数':v} for k,v in data.get('coverage',{}).items()])
            st.caption('缺失字段保持空白；停止不会删除已保存的作品。重新补采会重新检查缺项，不保证从原翻页位置恢复。')
        if st.button('保存进度并停止',disabled=not data['running'],key='task_stop_'+platform):
            local=Path(root)/'local';local.mkdir(exist_ok=True)
            (local/('bilibili_sync_stop' if platform=='bilibili' else 'sync_stop')).touch()
            st.info('已请求停止，等待当前读取结束并保存。')
    if platform=='douyin':
        from creatorlab.hub import latest_posts,eligible
        from creatorlab.image_reading import readiness
        images=[r for r in eligible(latest_posts(db)) if r['platform']==platform and r.get('media_format')=='image']
        missing=[r for r in images if readiness(r)['state']!='ready']
        if images:
            st.caption(f'图文阅读数据：{len(images)-len(missing)} / {len(images)}条就绪；不含私密作品。')
        if missing:
            st.warning(f'{len(missing)}条图文阅读数据待补齐，展开查看具体缺项，或点击下方继续补采。')
            with st.expander('查看图文阅读缺项'):
                st.table([{'作品':r['title'],'缺项说明':readiness(r)['message']} for r in missing])
    own=[a for a in accounts(db) if a['is_self'] and a['platform']==platform]
    if own:
        ids=[a['id'] for a in own];key='task_account_'+platform
        if st.session_state.get(key) not in (None,*ids):st.session_state.pop(key,None)
        aid=st.selectbox('补采目标账号',ids,format_func=lambda i:next(a['display_name'] for a in own if a['id']==i),key=key)
        if st.button('继续补采缺失数据',key='task_retry_'+platform,disabled=job_running(root,platform)):
            try:
                if platform=='bilibili':
                    from creatorlab.bilibili_ui import launch_import
                    launch_import(db,root,next(a['handle'] for a in own if a['id']==aid),details=-1,retry_only=True,budget=900)
                else:
                    from creatorlab.douyin_ui import launch
                    launch(db,root,repair=True,account_id=aid)
                notify('补采已启动，可继续浏览其他页面。');st.rerun(scope='app')
            except (ValueError,OSError) as exc:st.error(str(exc))
    if platform=='douyin' and show_review:
        from creatorlab.douyin_ui import review_captures
        review_captures(db,root)
    if st.button('刷新作品与任务',key='task_refresh_'+platform):st.rerun(scope='app')
