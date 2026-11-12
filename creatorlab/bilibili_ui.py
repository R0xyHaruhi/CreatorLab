"""One entry point, no tokens or CSV required for browser-assisted public import."""
import json
import subprocess
import sys
from pathlib import Path
import streamlit as st
from creatorlab.hub import accounts
from creatorlab.bilibili_import import parse_uid,job_running
from creatorlab.sync_browser import status_write


def launch_import(db,root,uid,details=10,retry_only=False,creator=False,budget=300):
    import os
    if os.getenv('CREATORLAB_ANALYSIS_ONLY')=='1':raise ValueError('容器模式只支持分析与文件导入；请在本机运行采集窗口')
    root=Path(root);uid=parse_uid(uid);local=root/'local';local.mkdir(exist_ok=True)
    if job_running(root):raise ValueError('已有采集任务在运行，完成后刷新即可。')
    status_write(local/'bilibili_sync_status.json',state='starting',database=str(Path(db).resolve()),uid=uid,count=0,total=None,info='正在启动B站导入窗口。')
    with open(local/'bilibili_import.log','a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,'-m','creatorlab.bilibili_import','--db',str(db),
           '--root',str(root),'--uid',uid,'--details',str(details),'--budget-seconds',str(budget)]+(['--creator'] if creator else [])+(['--retry-missing'] if retry_only else []),cwd=str(root),
           creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0),stdin=subprocess.DEVNULL,stdout=log,stderr=log)


def repair_panel(db,uid,prefix='radar'):
    root=Path(__file__).resolve().parent.parent
    from creatorlab.sync_jobs import retry_rows
    pending=retry_rows(db,uid)
    st.caption(f'UID {uid} · {len(pending)} 条待补齐。会打开实际视频页，补取发布时间、点赞、评论、收藏、分享、投币、弹幕及封面。')
    if st.button('一键补齐B站数据并重建画像',key=prefix+'_repair',disabled=job_running(root),type='primary'):
        try:
            launch_import(db,root,uid,details=-1,retry_only=True,budget=900)
            st.info('补采已启动。遇到验证请在采集窗口完成；结束后点击下方刷新。')
        except (ValueError,OSError) as exc:st.error(str(exc))
    if st.button('刷新画像数据',key=prefix+'_refresh'):st.rerun()


def import_panel(db,root,host=None,show_status=True):
    root=Path(root);local=root/'local';local.mkdir(exist_ok=True)
    known=[a for a in accounts(db) if a['platform']=='bilibili' and a['is_self'] and a['handle'].isdigit()]
    with (host or st.sidebar).expander('B站导入',expanded=host is not None):
        st.caption('填写自己的UID或空间链接，自动采集粉丝等账号统计，并逐页导入公开作品。遇到登录或验证时，请在新窗口完成。')
        default=None if 'bili_import_uid' in st.session_state else known[0]['handle'] if known else ''
        value=st.text_input('B站UID / 空间链接',value=default,placeholder='https://space.bilibili.com/123456',key='bili_import_uid')
        detail_scope=st.selectbox('导入模式',['快速补全：10条详情（缺项优先）','补齐缺失 / 到期窗口','完整同步：全部（较慢）'],key='bili_detail_scope')
        retry_only=detail_scope=='补齐缺失 / 到期窗口'
        details=10 if detail_scope.startswith('快速') else -1
        budget=900 if detail_scope.startswith('完整') else 300
        st.caption('快速模式先建立可用结果；定向补采只处理缺失项和当前到期窗口。预算不保证网络耗时，随时可停止。')
        creator=st.checkbox('采集本人创作中心概览（需登录）',value=False,key='bili_creator_overview')
        running=job_running(root)
        if st.button('一键导入B站作品',key='bili_start',disabled=running,use_container_width=True,type='primary'):
            try:
                uid=parse_uid(value)
                launch_import(db,root,uid,details,retry_only,creator,budget)
                st.success('导入窗口即将打开。完成后点击「刷新作品库」。')
            except (ValueError,OSError) as exc:st.error(str(exc))
        status={};path=local/'bilibili_sync_status.json'
        try:
            if path.exists():status=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
        if status and show_status:
            states={'starting':'启动中','waiting_login':'等待页面加载 / 登录或验证','collecting':'导入中','details':'补充互动指标','creator':'等待创作中心数据','covers':'保存作品封面','completed':'本轮公开指标已读取','partial':'作品已保存，指标尚未补齐','empty':'没有公开投稿','stopped':'已停止','error':'需要处理'}
            st.write('状态：'+states.get(status.get('state'),'等待导入'))
            if status.get('uid'):st.caption('目标UID：'+str(status['uid']))
            if status.get('private_count'):st.caption(f"其中 {status['private_count']} 条为页面确认的仅自己可见作品，保留清单，不参加公开表现评分。")
            total=status.get('total')
            st.metric('本次已识别作品',f"{status.get('count',0)} / {total if total is not None else '总数待确认'}")
            st.caption(f"其中 {status.get('with_views',0)} 条有播放量（含已有记录）；已访问 {status.get('details',0)} 个作品页补充指标。")
            st.caption(f"真实封面已缓存：{status.get('with_cover',0)} / {status.get('count',0)} 条")
            st.caption(f"本轮取得完整互动字段及发布时间：{status.get('radar_ready',0)} / {status.get('count',0)} 条；至少3条同组记录可开始探索画像。")
            fields=status.get('account_fields',[])
            st.caption('粉丝量：'+('已采集' if 'followers' in fields else '未取得')+' · 创作中心：'+('已采集' if status.get('creator_saved') else '未取得'))
            coverage=status.get('coverage',{})
            if coverage:
                with st.expander('查看采集完整度'):
                    for field,label in [('views','播放'),('likes','点赞'),('comments','评论'),('danmaku','弹幕'),('coins','投币'),('favorites','收藏'),('shares','分享')]:
                        st.write(f'{label}：库中可用 {coverage.get(field,0)} / {status.get("count",0)} 条，本轮实际取得 {status.get("fresh_coverage",{}).get(field,0)} 条')
            if status.get('phase_total'):
                st.progress(min(1,status.get('details',0)/status['phase_total']),text=f'详情补全 {status.get("details",0)}/{status["phase_total"]}')
                if status.get('remaining_seconds') is not None:st.caption(f'按本轮已完成速度估算剩余约 {status["remaining_seconds"]//60} 分钟，网络变化时会调整。')
            st.caption(status.get('info',''))
            from creatorlab.sync_jobs import failures
            pending=failures(db,str(status.get('uid','')))
            if pending:
                with st.expander('哪些作品没补齐，为什么？'):
                    import pandas as pd
                    st.table(pd.DataFrame([{'BV号':r['external_id'],'缺失':', '.join(r['missing']),'原因':r['error'],'尝试次数':r['attempts']} for r in pending[:30]]))
                    st.caption('再次选择“补齐缺失 / 到期窗口”即可继续，不需要重导全部作品。')

            if status.get('warning'):st.warning(status['warning'])
            if status.get('state')=='error':st.error('请处理提示后重试；已保存的数据不会丢失。')
        a,b=st.columns(2)
        if a.button('刷新作品库',key='bili_refresh',use_container_width=True):st.rerun()
        if b.button('停止导入',key='bili_stop',disabled=not running,use_container_width=True):
            (local/'bilibili_sync_stop').touch();st.info('已请求停止，已导入作品会保留。')
        st.caption('同账号按BV号更新，不重复建作品。公开空间不提供的完播率、收入等数据不会推算。')
