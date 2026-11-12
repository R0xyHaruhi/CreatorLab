"""The default path: three observations -> one change -> linked work -> measured review."""
import json
import pandas as pd
import plotly.express as px
import streamlit as st
from creatorlab.hub import latest_posts
from creatorlab.review import NAMES,display
from creatorlab.review_loop import starter_observations,freeze,baselines,init_loop,link_experiment,evaluate_experiment
from creatorlab.growth import save_experiment,experiments,update_experiment
from creatorlab.measurements import due_windows


def next_actions(rows,metric,due_rows=None):
    st.markdown('### 今天先做这三件事')
    for i,(title,detail) in enumerate(starter_observations(rows),1):
        with st.container(border=True):st.markdown(f'**{i}. {title}**');st.write(detail)
    if not rows:return
    due=due_windows(rows[0]['_db'],due_rows or rows)
    if due:
        st.warning(f'{len(due)} 个固定窗口正处于补采时间。到“同步与设置 → 同步与进度”补齐缺失 / 到期窗口，不需要重新填表。')
        with st.expander('到期窗口清单'):st.table(pd.DataFrame(due).drop(columns=['post_id']))
    st.caption('1–4条作品也可以开始复盘；这些是可观察事实与实验方向，不是统计胜负或增长保证。')


def baseline_controls(df,rows):
    db=rows[0]['_db'];aid=rows[0]['account_id'];window=str(df.analysis_window.iloc[0]) if 'analysis_window' in df else '当前累计'
    options=[r for r in baselines(db,aid) if r['window_name']==window]
    with st.expander('固定我的成长参照，避免历史排名来回变化'):
        name=st.text_input('这组参照的名称',value='我的第一组'+window,key='baseline_name')
        if st.button('保存当前组为固定成长参照',key='baseline_save',disabled=not df.age_band.ne('未知').any()):
            freeze(db,aid,name,window,df);st.rerun()
        chosen=st.selectbox('画像参照',[None]+[r['id'] for r in options],format_func=lambda i:'当前历史分布（会变化）' if i is None else next(r['name']+' · '+r['created_at'][:10] for r in options if r['id']==i),key='baseline_pick')
        st.caption('固定参照保存当时的数值，不会被后来的同步改写。固定窗口优先；累计值参照仍受作品年龄差异影响。')
    if chosen is None:return df
    return pd.DataFrame(json.loads(next(r['rows_json'] for r in options if r['id']==chosen)))


def experiment_panel(db,rows,metric,compact=False):
    init_loop(db);aid=rows[0]['account_id'];all_rows=[r for r in latest_posts(db) if r['account_id']==aid]
    st.markdown('### 记录与复盘' if compact else '### 🎯 一次改动，关联作品，按时复盘')
    tasks=experiments(db,aid)
    with st.expander('自己新建一次改动') if compact and tasks else st.container():
        with st.form('growth_new_challenge'):
            title=st.text_input('挑战名称',placeholder='第一秒先展示结果')
            hypothesis=st.text_area('这次只改什么，为什么？')
            if st.form_submit_button('接受这个挑战'):
                try:save_experiment(db,aid,title,hypothesis,metric);st.rerun()
                except ValueError as exc:st.error(str(exc))
    if compact and tasks:
        options={t['id']:t for t in tasks}
        from creatorlab.feedback import scoped_selectbox
        chosen=scoped_selectbox('这次复盘哪次改动',list(options),format_func=lambda i:options[i]['stage']+' · '+options[i]['hypothesis'][:42],key='review_task')
        tasks=[options[chosen]]
    for task in tasks[:15]:
        with st.container(border=True) if compact else st.expander(task['stage']+' · '+task['title']):
            from creatorlab.learning_workflow import experiment_detail,save_review
            platform=rows[0]['platform']
            detail=experiment_detail(db,aid,platform,task['id'])
            st.write(task['hypothesis']);st.caption('目标：'+NAMES.get(task['metric'],task['metric']))
            if detail.get('source_plan'):st.caption('来自已保存创作方案 '+detail['source_plan'][:8]+' · '+detail.get('kind',''))
            ids=[r['id'] for r in all_rows];fmt=lambda i:next(r['title'][:70] for r in all_rows if r['id']==i)
            saved_baseline = task.get('baseline_ids')
            baseline_ids = json.loads(saved_baseline) if saved_baseline else []
            if not saved_baseline and detail.get('source_plan'):
                from creatorlab.workflow_store import get
                source_plan = get(db,'plan',aid,platform,detail['source_plan']) or {}
                baseline_ids = [source_plan.get('target_id')]
            baseline=st.multiselect('原做法 / 参照作品',ids,default=[i for i in baseline_ids if i in ids],format_func=fmt,key=f'exp_before_{task["id"]}')
            variant=st.multiselect('实施改动后的作品',ids,default=[i for i in json.loads(task.get('variant_ids') or '[]') if i in ids],format_func=fmt,key=f'exp_after_{task["id"]}')
            windows=['24小时','7天','30天'];window=st.selectbox('双方使用相同窗口',windows,index=windows.index(task.get('window_name') or detail.get('suggested_window') or '7天'),key=f'exp_window_{task["id"]}')
            if st.button('关联并检查窗口',key=f'exp_link_{task["id"]}'):
                try:link_experiment(db,task['id'],aid,baseline,variant,window);st.rerun()
                except ValueError as exc:st.error(str(exc))
            result=evaluate_experiment(db,task,all_rows)
            st.write('**'+result['status']+'**')
            if result.get('pending'):
                for line in result['pending']:st.caption(line)
                st.caption('窗口已错过时，不能用今天累计值补算。可以导入当时真实保存的观测，或等待下一轮新作品。')
            if result['status']=='可以复盘':
                a,b=st.columns(2);a.metric('原做法典型值',display(result['baseline'],task['metric']));b.metric('改动后典型值',display(result['result'],task['metric']))
                st.write(result['direction']+'；'+('小样本探索，不能证明改动有效。' if result['exploratory'] else '仍是观察比较，未控制投流与热点。'))
                st.caption(f'参照 {result["n_baseline"]} 条，实验 {result["n_variant"]} 条。首次可复盘时冻结参照值，避免后来数据改写。')
                with st.expander('实际观测时间与依据'):st.json(result['evidence'])
                for limitation in result.get('limitations',[]):st.caption(limitation)
            stage=st.selectbox('挑战进度',['计划中','制作中','已发布待复盘','已复盘'],index=['计划中','制作中','已发布待复盘','已复盘'].index(task['stage']),key=f'challenge_stage_{task["id"]}')
            with st.expander('目标、改动与干扰因素') if compact else st.container():
                note=st.text_area('结果、干扰因素与下一步',value=task['note'],key=f'challenge_note_{task["id"]}')
                goal=st.text_input('本次目标',value=detail.get('goal',NAMES.get(task['metric'],task['metric'])),key=f'challenge_goal_{task["id"]}')
                kinds=['选题','标题','封面','内容结构','跨平台复用','发布时间']
                kind=st.selectbox('实际改动类型',kinds,index=kinds.index(detail.get('kind','内容结构')),key=f'challenge_kind_{task["id"]}')
                change=st.text_area('实际只改了什么',value=detail.get('change',task['hypothesis']),key=f'challenge_change_{task["id"]}')
                confounders=st.text_area('干扰因素与样本限制',value=detail.get('confounders',''),placeholder='例如：热点变化、投流、时长或题材不同；未知也要说明',key=f'challenge_confounders_{task["id"]}')
            with st.expander('复盘经验与下一步',expanded=result['status']=='可以复盘') if compact else st.container():
                conclusion=st.text_area('本账号的探索性经验',value=detail.get('conclusion',''),placeholder='描述观察到什么，不写成改动必然导致结果',key=f'challenge_conclusion_{task["id"]}')
                next_action=st.text_area('下一轮继续验证什么',value=detail.get('next_action',''),key=f'challenge_next_{task["id"]}')
                from creatorlab.workflow_store import get
                saved_lesson=get(db,'lesson',aid,platform,task['id']) or {}
                feedback=st.checkbox('将这条已复盘经验反馈到下一轮创作建议',value=bool(saved_lesson) and not saved_lesson.get('inactive',False),key=f'challenge_feedback_{task["id"]}')
                st.caption('仅在有可比固定窗口数据、状态为已复盘时纳入反馈；只用于相同账号、平台、体裁、赛道和目标指标。取消勾选后保存可撤回该经验。')
            if st.button('保存复盘',key=f'challenge_save_{task["id"]}'):
                try:
                    save_review(db,aid,platform,task['id'],stage,note,goal,change,confounders,conclusion,next_action,feedback,kind)
                    if compact:
                        from creatorlab.feedback import notify
                        notify('复盘已保存；启用反馈的有效经验会用于下一轮建议。')
                    st.rerun()
                except ValueError as exc:st.error(str(exc))
