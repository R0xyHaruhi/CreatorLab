"""Visual-first personal space: one card, one comparison, one next move."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from creatorlab.feedback import scoped_selectbox
from creatorlab.content_analysis import frame
from creatorlab.battlecard import profile,profiles,render_card
from creatorlab.appearance import chart
from creatorlab.review import display


def chronological_ids(df):
    """Publication order; import IDs are only a tie-breaker, unknown dates last."""
    dated=df.assign(_published_order=pd.to_datetime(df['published_at'],format='mixed',utc=True,errors='coerce'))
    return dated.sort_values(['_published_order','id'],ascending=[False,False],na_position='last',kind='stable').id.tolist()


def publication_label(raw, *, show_time=False):
    at=pd.to_datetime(raw,utc=True,errors='coerce')
    if pd.isna(at):return '发布时间待确认' if raw else '发布时间未知'
    if show_time and ('T' in str(raw) or ':' in str(raw)):
        return at.tz_convert('Asia/Shanghai').strftime('%Y-%m-%d %H:%M')
    return str(raw)[:10]


def dated_label(row,limit=70):
    return publication_label(row.get('published_at'),show_time=True)+' · '+str(row['title'])


def scope(rows,key):
    if not rows:return []
    accounts={r['account_id']:r['account_name']+' · '+('B站' if r['platform']=='bilibili' else '抖音') for r in rows}
    if len(accounts)>1:
        aid=scoped_selectbox('创作者账号',list(accounts),format_func=accounts.get,key=key+'_account')
        rows=[r for r in rows if r['account_id']==aid]
    return rows


def hero(rows,db=None,platform=None,compact=False):
    from creatorlab.challenge_ui import intro,result_panel,share
    if compact:
        from creatorlab.challenge_ui import skin
        skin()
    else:intro()
    is_demo=False
    if not rows and db is not None and platform and st.session_state.get('demo_platform')==platform:
        from creatorlab.sample_data import sample_rows
        rows=sample_rows(platform);is_demo=True
        st.info('示例预览：以下数值为演示数据，不写入账号、作品或实验。')
        if st.button('退出示例，导入我的作品',key='demo_exit'):
            st.session_state.pop('demo_platform',None);st.rerun()
    rows=scope(rows,'hero')
    if not rows:
        if db is not None and platform:
            from creatorlab.usability_ui import first_import
            first_import(db,platform)
            if st.button('先看可视化示例',key='demo_start'):
                st.session_state.demo_platform=platform;st.rerun()
            return
        with st.container(border=True):
            st.markdown('### 还没有作品')
            st.write('导入当前平台的作品，查看六维表现。')
            st.caption('打开侧栏平台导入，或在“设置”添加作品。')
        return
    challenge_db=db or rows[0].get('_db')
    if is_demo:st.session_state.battle_mode='作品战力'
    choices=['作品战力','同行挑战']+(['精选样本'] if rows[0]['platform']=='bilibili' else [])
    if st.session_state.get('battle_mode') not in (None,*choices):st.session_state.pop('battle_mode',None)
    if compact:
        mode='作品战力'
        with st.sidebar.expander('调整参照与图表口径'):
            scope_control,media_control,shape_control=st.columns([1,1.35,1.2],gap='medium')
    else:
        with st.container(key='battle-filters'):
            mode_control,scope_control,media_control,shape_control=st.columns([1.1,1,1.35,1.2],gap='medium')
        mode=mode_control.radio('选择挑战',choices,horizontal=True,key='battle_mode',disabled=is_demo)
    if mode=='精选样本':
        from creatorlab.optional_ui import weekly_panel
        weekly_panel(rows,key='weekly_hero');return
    if mode=='同行挑战' and challenge_db:
        from creatorlab.challenge_ui import peer_panel
        peer_panel(rows,challenge_db);return
    if challenge_db and not is_demo:
        from creatorlab.genres import genre_rows
        rows=genre_rows(challenge_db,rows)
    classification_rows=rows
    comparison_scope=scope_control.radio('自己的作品参照范围',['全部作品','同赛道'],horizontal=True,key='hero_own_scope')
    own_scope='track' if comparison_scope=='同赛道' else 'all'
    df=frame(rows)
    if df.empty:st.info('先导入作品的播放与互动数据，战力卡会在这里出现。');return
    from creatorlab.workspace_overview import headline,distribution,lower_panels
    from creatorlab.battlecard import history_profiles
    media=media_control.radio('参照作品类型',['全部类型','仅视频','仅图文'],horizontal=True,key='hero_media_scope')
    if media!='全部类型':
        wanted='image' if media=='仅图文' else 'video'
        rows=[r for r in rows if r.get('media_format')==wanted]
        df=frame(rows)
        if df.empty:st.info('所选类型暂无公开有效作品，请先同步或选择全部类型。');return
    shape=shape_control.radio('战力画像口径',['数量战力','互动效率'],horizontal=True,key='hero_shape')
    efficiency=shape=='互动效率'
    candidates=history_profiles(rows,efficiency=efficiency,scope=own_scope)
    alternates=history_profiles(rows,efficiency=not efficiency,scope=own_scope)
    def classification_controls():
        if compact and own_scope!='track':return
        if challenge_db and not is_demo:
            with st.expander('给作品分类 / 批量调整赛道'):
                from creatorlab.classification_ui import editor
                editor(challenge_db,classification_rows,'hero_classify')
    if own_scope=='track':classification_controls()
    ids=chronological_ids(df)
    if st.session_state.get('hero_work') is not None and st.session_state.hero_work not in ids:st.session_state.pop('hero_work',None)
    if 'hero_next_work' in st.session_state:
        requested=st.session_state.pop('hero_next_work')
        if requested in ids:st.session_state.hero_work=requested
    if 'hero_work' not in st.session_state and st.session_state.get('_battle_selected_work') in ids:
        st.session_state.hero_work=st.session_state._battle_selected_work
    choice,shortcut=st.columns([3.3,1],vertical_alignment='bottom')
    chosen=scoped_selectbox('作品',ids,host=choice,format_func=lambda i:dated_label(df.loc[df.id==i].iloc[0]),key='hero_work')
    st.session_state._battle_selected_work=chosen
    following=ids[ids.index(chosen)+1:]+ids[:ids.index(chosen)]
    unlocked=[i for i in following if candidates[i]['ready']]
    if shortcut.button('换一条已解锁作品',key='battle_next_ready',disabled=not unlocked,width='stretch'):
        st.session_state.hero_next_work=unlocked[0];st.rerun()
    row=df[df.id==chosen].iloc[0].to_dict();model=candidates[chosen]
    from creatorlab.engagement import attach_context,like_diagnosis
    model=attach_context(model,alternates.get(chosen),like_diagnosis(rows,row,scope=own_scope))
    if is_demo:model=dict(model,demo=True)
    applicable=model.get('applicable',6)
    if row.get('media_format')=='image':
        from creatorlab.reporting import metric_value
        total=metric_value(row,'image_count');average=metric_value(row,'avg_image_views');depth=metric_value(row,'image_depth')
        st.caption('图片总数：'+('待采集' if total is None else f'{total:g}张')+' · 平均浏览：'+('待采集' if average is None else f'{average:g}张')+' · 阅读深度指数：'+('待采集' if depth is None else f'{depth:.1%}'))
        from creatorlab.engagement import axis_value
        from creatorlab.image_reading import readiness,save
        readiness_state=readiness(row)
        if readiness_state['state']!='ready':
            st.warning(readiness_state['message'])
            if challenge_db and not is_demo:
                from creatorlab.douyin_ui import launch,ROOT
                from creatorlab.bilibili_import import job_running
                if st.button('补采图文阅读数据',key='image_reading_retry',disabled=job_running(ROOT,'douyin')):
                    try:launch(challenge_db,repair=True,account_id=row['account_id']);st.toast('正在补采，入库后自动刷新指标')
                    except (OSError,ValueError) as exc:st.error(str(exc))
                if readiness_state['state']=='count_missing':
                    with st.expander('核对原作品并确认总图片数'):
                        if row.get('url'):st.link_button('打开这条原作品',row['url'])
                        confirmed=st.number_input('原作品总图片数（按作品页计数填写）',min_value=1,max_value=1000,value=1,step=1,key='image_count_'+str(chosen))
                        checked=st.checkbox('已在原作品页核对图片计数',key='image_count_checked_'+str(chosen))
                        if st.button('保存已核对的图片总数',key='image_count_save_'+str(chosen),disabled=not checked):
                            save(challenge_db,chosen,{'image_count':confirmed});st.rerun()
    elif any(s['metric']=='completion_rate' and s.get('status')=='missing' for s in model['scores']):
        st.info('这条视频尚无有效完播率观测。平台后台也显示—时属于来源未提供；后台有数值时才需要补采，缺失不记0分。')
    if not compact:st.caption('参照范围：'+model['own_scope_label']+' · 同账号、同平台，非全站或内容质量评级。')
    from creatorlab.own_scope import references
    reference_count=len(references(rows,row,own_scope))
    if not compact:st.caption(f'当前范围共{reference_count}条其他历史有效作品；每轴只采用该指标有有效值的作品，因此各轴参照数可能不同。')
    if own_scope=='track':
        st.caption('此范围由你主动选择：在上方勾选作品并确认分类后，仅对比相同分区与细分赛道；未分类作品不自动归组。')
    if not model['ready']:
        from creatorlab.own_scope import scope_key
        selected_scope=scope_key(row,own_scope)
        reference_df=df[df.apply(lambda r:scope_key(r.to_dict(),own_scope)==selected_scope,axis=1)]
        left,right=st.columns([1.6,1],gap='large')
        with left:
            st.markdown('### 播放表现分布')
            chart(distribution(reference_df,chosen),key='overview_distribution')
            st.caption('高亮为当前作品所在区间。已有原始指标继续显示；画像需要更多有效参照。')
        with right:
            st.markdown('### 当前作品')
            st.write(row['title'])
            a,b=st.columns(2)
            a.metric('累计播放',display(row['views'],'views'))
            position=int(reference_df.views.rank(ascending=False,method='min')[reference_df.id==chosen].iloc[0])
            b.metric('当前范围累计排序',f'{position} / {len(reference_df)}')
            known=sum(item['value'] is not None for item in model['scores'])
            st.caption(f'原始指标 {known}/6 项；'+'其他有效参照不足，暂不绘图。')
            st.caption(f"可评分维度 {model['available']}/{applicable}；每个维度至少需要3条其他有效参照，达到3个可评分维度才绘图。")
            if row['platform']=='douyin':
                from creatorlab.douyin_ui import launch,ROOT,read_status,LABELS
                from creatorlab.bilibili_import import job_running
                if st.button('补齐互动数据',key='dy_hero_start',type='primary',disabled=job_running(ROOT,'douyin')):
                    try:launch(row['_db'],repair=True,account_id=row['account_id']);st.toast('采集窗口即将打开')
                    except (OSError,ValueError) as exc:st.error(str(exc))
                status=read_status(ROOT)
                if status:st.caption(LABELS.get(status.get('state'),'等待同步'))
            else:
                from creatorlab.bilibili_ui import launch_import
                from creatorlab.bilibili_import import job_running
                from pathlib import Path
                root=Path(__file__).resolve().parents[1]
                if st.button('补齐B站数据',key='hero_repair',type='primary',disabled=job_running(root)):
                    try:launch_import(row['_db'],root,str(row['handle']),details=-1,retry_only=True,budget=900);st.toast('补采窗口即将打开')
                    except (OSError,ValueError) as exc:st.error(str(exc))
            with st.expander('缺少哪些数据？'):
                st.caption('参照指当前所选范围内、同账号同平台的其他公开有效作品，累计与固定窗口分开，不强制按作品年龄分组。')
                for item in model['scores']:st.caption(item['axis']+'：'+display(item['value'],item['metric'])+f" · 同组有效参照{item['n']}条")
                if row['age_band']=='未知':st.caption('发布时间待确认，但不因年龄未知阻止累计数量比较。')
                st.caption('至少3条其他有效作品、3个可比维度才能绘制画像。公开页没有的完播率不作估算。')
        with st.expander('展开作品数据与分布'):
            headline(rows,df);lower_panels(rows,df,chosen)
        if own_scope!='track':classification_controls()
        if row.get('media_format')=='image':reading_details(row)
        return
    from creatorlab.challenge import work_result
    ranked=df.copy()
    # A deliberate user-facing age policy, while fixed-window labels stay separate.
    ranked['age_band']='不限年龄'
    ranked['_baseline_scope']=ranked.get('analysis_window',pd.Series('当前累计',index=ranked.index)).fillna('当前累计')
    result=work_result(ranked,ranked[ranked.id==chosen].iloc[0].to_dict(),candidates)
    result['shape_label']='互动效率综合位置' if efficiency else '数量综合位置'

    if result['ready']:
        model=dict(model,comparison='efficiency' if efficiency else 'counts',overall=result['percent'],comparison_n=result['n'],
                   comparison_axes=result['axes'],comparison_tied=result['tied'])
    with st.container(key='battle-stage'):
        left,right=st.columns([2.1,1],gap='large')
        with left:
            if not compact:
                st.caption(('B站' if row['platform']=='bilibili' else '抖音')+' · 作品战力图')
                st.markdown('### '+str(row['title']).replace('\n',' '))
            completion=next((s for s in model['scores'] if s['metric']=='completion_rate'),None)
            if completion:
                from creatorlab.engagement import axis_value
                st.markdown('实际完播率 **'+axis_value(completion)+'**')
                if completion['score'] is not None:
                    lower=round(completion['score']*completion['n']/100)
                    if not compact:st.caption(f"完播率高于 {lower}/{completion['n']} 条其他有效历史作品；只比较有完播数据的记录，不表示100%观众看完。")
            chart(radar_figure(model),key='hero_radar',surface='panel')
            scope_text=model['own_scope_label']+(' · 小样本探索' if model['exploratory'] else ' · 历史分布')
            st.caption(f'{scope_text} · 不限作品年龄 · {model["available"]}/{applicable}个适用维度已解锁')
        with right:
            result_panel(model,result)
            if compact and not is_demo:
                if st.button('为下一条做个计划',key='hero_plan_next',type='primary',width='stretch'):
                    from creatorlab.challenge_ui import plan_from_takeaway
                    from creatorlab.platforms import goals
                    from creatorlab.workspace import route,CREATE
                    proposal = plan_from_takeaway(model, chosen)
                    goal = next(label for label, item in goals(row['platform']).items() if item[0] == proposal['metric'])
                    st.session_state.pop('assistant_workflow_draft', None)
                    route(CREATE,create_step='准备创作',assistant_workflow_target=chosen,assistant_account=row['account_id'],
                          assistant_goal=goal,assistant_workflow_focus=proposal['kind'],assistant_workflow_handoff=proposal)
            share(row,model,demo=is_demo,primary=not compact)
            if not compact and not is_demo and row.get('media_format')!='image':
                if st.button('检查视频片段',key='hero_video_check',width='stretch'):
                    st.session_state['_open_video_check']={'post_id':row['id'],'account_id':row['account_id']};st.rerun()
    if not compact:st.caption('已解锁维度 '+str(model['available'])+'/'+str(applicable)+'个适用维度 · '+('演示数据' if is_demo else '真实导入数据')+' · 缺失维度保留空缺')
    if own_scope!='track':classification_controls()
    if row.get('media_format')=='image':reading_details(row)
    with st.expander('下一条，试一个新招') if not compact else st.container():
        if not compact:
            st.write(model['next_test'])
        if not compact and st.button('记录为实验',key='hero_accept',disabled=is_demo):
            from creatorlab.growth import save_experiment,experiments
            hypothesis=model['next_test'];metric=model['low']['metric'] if model['low'] else 'views'
            if not any(e['hypothesis']==hypothesis for e in experiments(row['_db'],row['account_id'])):
                save_experiment(row['_db'],row['account_id'],'作品复盘',hypothesis,metric)
            st.toast('已保存到“做下一条 → 记录与复盘”')
    with st.expander('比较口径与数据来源',expanded=False):
        from creatorlab.engagement import axis_value
        st.caption('图中同时显示数量位置与互动转化位置。切换口径只改变主画像与综合位置；播放多不等于点赞转化高，默认不限制作品年龄。')
        st.caption('点赞等互动转化位置仅使用播放≥1000的记录，这是本工具的样本稳定性门槛，并非平台规则；小样本仍显示原始比例。')
        st.caption('图上100表示历史位置100/100，不是实际完播率100%；真实完播率、播放量和每轴参照数见下表或悬浮提示。')
        st.caption('全部作品不按体裁或年龄自动分组；同赛道仅采用已确认的相同分类。参照限定同账号、平台与观察口径。当前作品排除在参照外。每轴至少3条其他有效记录，不限作品年龄；缺失不补零。')
        st.table(pd.DataFrame([{'维度':item['axis'],'真实数值':axis_value(item),'参照作品数':item['n'],'状态':{'not_applicable':'图文不适用','missing':'当前作品缺少观测','insufficient':'有效参照不足或未达转化门槛','ready':'可比较'}.get(item.get('status'),'可比较')} for item in model['scores']]))
        st.caption('图文阅读轴只参照其他图文。视频和图文混合的综合位置只采用共有前五轴；纯图文范围数据足够时才采用第六轴。')
        st.caption('各轴表示数值严格更低的参照占比，并列不计超过。综合位置为共同维度排名等权平均后的相对位置，只描述当前所选口径，不是内容质量总分。')
    if compact:return
    with st.expander('展开作品数据与分布'):
        headline(rows,df);lower_panels(rows,df,chosen)


def reading_details(row):
    from creatorlab.reporting import metric_value
    from creatorlab.engagement import axis_value
    with st.expander('图文阅读口径与辅助指标'):
        st.info('图文使用独立的阅读深度轴：数量线比较平均浏览图片数，转化线比较平均浏览图片数÷总图片数。阅读深度不是观众看完的比例，源数据可能经过取整。')
        st.caption('辅助指标：划走率 '+axis_value(dict(metric='swipe_away_rate',value=metric_value(row,'swipe_away_rate')))+' · 文案展开率 '+axis_value(dict(metric='text_expand_rate',value=metric_value(row,'text_expand_rate')))+'；不计入战力综合排名。')


def radar_figure(model):
    from creatorlab.appearance import PALETTES
    from creatorlab.engagement import AXIS_NAMES,axis_value
    p=PALETTES[st.session_state.get('clab_appearance','柔和深色')]
    scores=model['scores'];dual=model.get('dual_scores')
    labels=[AXIS_NAMES.get(item['axis'],item['axis']) if dual else item['axis'] for item in scores];values=[item['score'] for item in scores]
    fig=go.Figure()
    fig.add_trace(go.Scatterpolar(r=[50]*7,theta=labels+[labels[0]],mode='lines',line=dict(color=p['muted'],width=1,dash='dot'),hoverinfo='skip',showlegend=False))
    details=[[axis_value(item),item['n']] for item in scores]
    primary_efficiency=model.get('comparison')=='efficiency'
    primary_name='互动转化位置' if primary_efficiency else '数量位置'
    primary_color=p['conversion'] if dual and primary_efficiency else p['accent']
    fig.add_trace(go.Scatterpolar(r=values+[values[0]],theta=labels+[labels[0]],customdata=details+[details[0]],
        name=primary_name if dual else '这条作品',mode='lines+markers',connectgaps=False,showlegend=bool(dual),
        fill='toself' if all(v is not None for v in values) else 'none',
        fillcolor='rgba(151,96,31,.10)' if dual and primary_efficiency else 'rgba(57,124,98,.14)',
        line=dict(color=primary_color,width=3,dash='dash' if dual and primary_efficiency else 'solid'),marker=dict(size=6,color=primary_color),
        hovertemplate='%{theta}<br>'+('精选样本位置' if model.get('comparison')=='weekly' else '样本位置' if model.get('comparison')=='peer' else '历史位置')+' %{r:.0f}/100<br>原始值 %{customdata[0]}<br>参照 %{customdata[1]} '+('位' if model.get('comparison')=='peer' else '条')+'<extra></extra>'))
    if dual:
        other_values=[s['score'] for s in dual];other_details=[[axis_value(s),s['n']] for s in dual]
        fig.add_trace(go.Scatterpolar(r=other_values+[other_values[0]],theta=labels+[labels[0]],customdata=other_details+[other_details[0]],
            name='数量位置' if primary_efficiency else '互动转化位置',mode='lines+markers',connectgaps=False,showlegend=True,
            line=dict(color=p['accent'] if primary_efficiency else p['conversion'],width=2.5,dash='solid' if primary_efficiency else 'dash'),
            hovertemplate='%{theta}<br>历史位置 %{r:.0f}/100<br>原始值 %{customdata[0]}<br>参照 %{customdata[1]}条<extra></extra>'))
        def number(v):return '—' if v is None else str(round(v))
        pairs=[(b,a) if primary_efficiency else (a,b) for a,b in zip(values,other_values)]
        ticks=[label+('<br>图文不适用' if item.get('status')=='not_applicable' else f'<br>数量{number(a)} · 转化{number(b)}') for label,(a,b),item in zip(labels,pairs,scores)]
    else:ticks=[label+'<br>'+('图文不适用' if item.get('status')=='not_applicable' else '—' if value is None else '位置'+str(round(value))+'/100') for label,value,item in zip(labels,values,scores)]
    # Completion is itself a percentage; never leave its relative score as a bare 100.
    if model.get('comparison') not in ('peer','weekly'):
        for i,item in enumerate(scores):
            if item['metric']=='completion_rate':
                position='有效参照不足' if item['score'] is None else f"高于{round(item['score']*item['n']/100)}/{item['n']}条"
                ticks[i]=labels[i]+'<br>实测 '+axis_value(item)+'<br>'+position
    fig.update_layout(height=448 if dual else 420,margin=dict(l=88,r=88,t=52,b=60),
      legend=dict(orientation='h',y=-.12,x=.5,xanchor='center',font=dict(size=13)),
      polar=dict(gridshape='linear',radialaxis=dict(range=[0,100],tickvals=[25,50,75,100],showticklabels=False,ticks='',showline=False),
      angularaxis=dict(rotation=90,direction='clockwise',tickmode='array',tickvals=labels,ticktext=ticks,tickfont=dict(size=13),linecolor=p['border'])))
    return fig


def quick_compare(rows):
    from creatorlab.report_ui import overall,formatted
    from creatorlab.reporting import comparison_table,metric_value,positions,filter_library
    st.markdown('## 作品对比')
    if len(rows)<2:st.info('导入至少两条作品，就能在这里对比。');return
    ordered=filter_library(rows);ids=[r['id'] for r in ordered];by_id={r['id']:r for r in ordered}
    fmt=lambda i:dated_label(by_id[i],60)
    for key in ('quick_a','quick_b','quick_c'):
        if st.session_state.get(key) not in (None,*ids):st.session_state.pop(key,None)
    a,b,c=st.columns(3)
    first=scoped_selectbox('作品 A',ids,host=a,format_func=fmt,key='quick_a')
    second=scoped_selectbox('作品 B',ids,host=b,index=1,format_func=fmt,key='quick_b')
    third=scoped_selectbox('作品 C（选填）',[None]+ids,host=c,format_func=lambda i:'不添加第三条' if i is None else fmt(i),key='quick_c')
    selected=[first,second]+([third] if third is not None else [])
    if len(set(selected))!=len(selected):st.info('请选择不同的作品。');return
    chosen=[by_id[i] for i in selected]
    data=comparison_table(chosen)
    choices={'Overall · 全指标':None,**{r['label']:r['metric'] for r in data}}
    if st.session_state.get('quick_metric') not in (None,*choices):st.session_state.pop('quick_metric',None)
    label=scoped_selectbox('对比指标',list(choices),key='quick_metric')
    metric=choices[label]
    if metric is None:overall(chosen,key='quick_overall')
    else:
        unit=next(r['unit'] for r in data if r['metric']==metric)
        records=[(chr(65+i),metric_value(r,metric)) for i,r in enumerate(chosen)]
        valid=[(name,value) for name,value in records if value is not None]
        if valid:
            fig=go.Figure(go.Bar(x=[v*(100 if unit=='rate' else 1) for _,v in valid],y=[n for n,_ in valid],orientation='h',
                     text=[formatted(v,unit) for _,v in valid],textposition='auto'))
            fig.update_layout(height=240,xaxis_title=label+('（%）' if unit=='rate' else '（秒）' if unit=='seconds' else ''),yaxis=dict(autorange='reversed'))
            chart(fig,key='quick_bars')
        if len(valid)!=len(records):st.info('部分作品缺少这项有效数据，缺失值未作为0画入图表。')
    if metric is None:
        fig=go.Figure(go.Bar(x=[r.get('views') for r in chosen],y=[chr(65+i) for i in range(len(chosen))],orientation='h',
                 text=[display(r.get('views'),'views') for r in chosen],textposition='auto'))
        fig.update_layout(height=240,xaxis_title='已知累计播放',yaxis=dict(autorange='reversed'))
        chart(fig,key='quick_scale_bars')
    st.markdown('### 数量表现形状（非综合质量分）')
    fig=go.Figure();traces=0
    for i,row in enumerate(chosen):
        raw=[v for v in positions(rows,row) if v['unit']=='count']
        if sum(v['percent'] is not None for v in raw)<3:continue
        labels=[v['label'] for v in raw];values=[v['percent'] for v in raw]
        fig.add_trace(go.Scatterpolar(r=values+[values[0]],theta=labels+[labels[0]],name='作品 '+chr(65+i),mode='lines+markers',
                          connectgaps=False,fill='toself' if all(v is not None for v in values) else 'none'))
        traces+=1
    if traces:
        fig.update_layout(height=380,polar=dict(radialaxis=dict(range=[0,100],ticksuffix='%')),legend=dict(orientation='h'))
        chart(fig,key='quick_radar')
        st.caption('各轴是相对各自账号、当前平台全部其他历史有效作品的数量位置；每轴至少3条有效参照。不同账号的轴不能解释为同一绝对规模，实际差异请看上表。不按体裁、赛道或作品年龄自动分组。')
    else:st.caption('历史参照不足，暂不叠加雷达图；overall与已有原始数值仍可使用。')
    st.caption('累计数据受发布时长与采集时间影响。这里展示观察差异，不推断选题、剪辑或平台推荐的因果。')
