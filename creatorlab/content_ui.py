"""Interactive comparisons and auditable, track-specific experiment suggestions."""
import pandas as pd
import plotly.express as px
import streamlit as st
from creatorlab.content_analysis import TRACKS, METRICS, TRACK_TESTS, annotate, frame, group_summary, recommendations
from creatorlab.hub import connect


def edit_content(db,row):
    from creatorlab.classification_ui import editor
    editor(db,[row],'work_'+str(row['id']),single=True)


from creatorlab.review import GOALS,NAMES,RATIO,display,pattern_findings,representative_pair,hook_observation,comparison_cohort
from creatorlab.appearance import chart,table

PLATFORMS={'douyin':'抖音','bilibili':'B站'}


def work_link(row):
    if str(row.get('url') or '').startswith('https://'):
        st.link_button('打开这条作品',row['url'])


def evidence(df,metric):
    with st.expander('查看数据范围与判断方法'):
        st.write(f'当前 {len(df)} 条作品，{int(df[metric].notna().sum())} 条有{NAMES[metric]}记录。')
        st.write('典型水平取中间那条作品的数值，减少偶尔爆款的影响。内容结论只在同账号、同平台、相同发布时长范围内比较，两类各需至少5条。')
        st.caption('这里使用采集时的累计数据，不是统一的发布7天数据；发布时间、投流和热点仍可能影响差异。')


def label_editor(rows,key):
    db=rows[0].get('_db') if rows else None
    if not db:return
    with st.expander('统一设置作品赛道与表现形式',expanded=False):
        from creatorlab.classification_ui import editor
        editor(db,rows,key)


def select_scope(rows,key):
    active=st.session_state.get('active_platform')
    rows=[r for r in rows if not active or r['platform']==active]
    accounts={r['account_id']:f"{r['account_name']} · {PLATFORMS.get(r['platform'],r['platform'])}" for r in rows}
    a,b=st.columns([1,1])
    persist = 'session' if key=='assistant' else None
    aid=a.selectbox('看哪个账号',list(accounts),format_func=accounts.get,key=key+'_account',persist_state=persist)
    from creatorlab.platforms import goals
    choices=goals(next(r['platform'] for r in rows if r['account_id']==aid))
    goal=b.selectbox('这次想解决什么',list(choices),key=key+'_goal',persist_state=persist)
    return [r for r in rows if r['account_id']==aid],choices[goal][0]


def overview(df,rows,metric):
    st.markdown('### 这次复盘的重点')
    valid=df.dropna(subset=[metric])
    known=df[~df.category.isin(['未分类',''])]
    a,b,c=st.columns(3)
    a.metric('可复盘作品',f'{len(df)} 条',help='仅包含有可靠正播放记录的作品。')
    b.metric('作品典型'+NAMES[metric],display(valid[metric].median() if len(valid) else None,metric),help='在当前作品中取中间水平；不是平台给出的账号评分。')
    c.metric('已分组作品',f'{len(known)}/{len(df)} 条',help='分组后才能比较内容形式，分类由你确认。')
    findings=pattern_findings(df,metric)
    if findings:
        f=findings[0]
        with st.container(border=True):
            st.markdown(f'**值得继续验证：{f["category"]}**')
            st.write(f'它的典型{NAMES[metric]}是 **{display(f["value"],metric)}**，另一类「{f["other"]}」是 **{display(f["other_value"],metric)}**。')
            st.caption(f'两类分别有 {f["n"]}、{f["other_n"]} 条作品；都在发布后 {f["age"]} 采集。这个差异值得测试，尚不能认定是内容形式造成的。')
            st.write(f'**怎么用：** 下一条可以继续做「{f["category"]}」，保留主题和大致时长，观察它能否再次达到原来的表现。')
    else:
        with st.container(border=True):
            st.markdown('**现在还不能判断哪类内容更值得继续做**')
            if len(known)==0:
                st.write('作品都还没有分组。先把两种常做的内容各选5条标好，例如「变装」和「剧情」。完成后，这里会对比它们的日常表现。')
            else:st.write('已有分组，但同一发布时长范围内，还没有两类各5条的有效记录。可以先对照具体作品，再补充分组。')
            st.caption('在此之前，作品播放高低可以查看，但不会被解释成某类内容更好。')
    hook=hook_observation(df)
    if hook:
        r=hook['row']
        with st.container(border=True):
            st.markdown('**优先回看这条的前2秒**')
            st.write(f'「{r["title"][:65]}」的2秒离开比例是 **{display(r["bounce_rate_2s"],"bounce_rate_2s")}**，同组作品的典型水平是 **{display(hook["typical"],"bounce_rate_2s")}**。')
            st.write('**怎么用：** 打开作品，检查最有吸引力的画面是否出现得太晚。下一条可以只调整开头，保留其他做法再试。')
            work_link(r)
            st.caption(f'参照来自同账号、同平台、同发布时长范围的 {hook["n"]} 条作品；这是复盘线索，不能直接证明开头造成流失。')
    elif metric not in df or not df[metric].notna().any():
        st.info(f'当前没有{NAMES[metric]}记录。先同步对应指标；不会用播放量替代你的目标。')
    else:
        st.caption('目前没有足够的可比开头留存数据；可以先从下一页的两条作品对照开始。')
    st.markdown('#### 作品表现一眼看')
    performance_chart(df,metric,'overview_performance')
    st.caption('更多图表在「📈 图表总览」；按分类交叉比较在「按内容找规律」。')
    label_editor(rows,'analysis')
    evidence(df,metric)


def compare_works(df,metric):
    st.markdown('### 对照两条，找一个可以复用的做法')
    pair=representative_pair(df,metric)
    if not pair:
        st.info('需要同平台、同发布时长范围内至少3条有目标指标的作品，且表现有差异，才能推荐一组对照。');return
    first,second,n=pair
    pool=df[(df.account_id==first['account_id'])&(df.platform==first['platform'])]
    if first.get('analysis_window','当前累计')=='当前累计':pool=pool[pool.age_band==first['age_band']]
    a,b=st.columns(2)
    options=list(pool.id)
    selected=[]
    for col,initial,name,key in [(a,first,'表现较高的作品','compare_a'),(b,second,'日常水平的参照作品','compare_b')]:
        with col:
            pid=st.selectbox(name,options,index=options.index(initial['id']),format_func=lambda i:pool.loc[pool.id==i,'title'].iloc[0][:65],key=key)
            row=pool[pool.id==pid].iloc[0].to_dict();selected.append(row)
            from creatorlab.creator_ui import cover
            cover(row,100)
            st.write('**'+row['title']+'**');st.metric(NAMES[metric],display(row.get(metric),metric));work_link(row)
    if selected[0]['id']==selected[1]['id']:st.info('选择两条不同的作品，才能看出差异。');return
    entries=[]
    from creatorlab.platforms import FEEDBACK
    for m in ['views']+FEEDBACK[first['platform']]:
        values=[r.get(m) for r in selected]
        if all(pd.isna(v) for v in values):continue
        entries.append({'看什么':NAMES[m],'作品 A':display(values[0],m),'作品 B':display(values[1],m)})
    st.table(pd.DataFrame(entries))
    st.write('**看完只回答一个问题：** A 和 B 的选题、前2秒、节奏或结尾，哪一处差别最明显？选一处放进下一条作品，不要同时全改。')
    st.caption(f'推荐对照来自 {n} 条相同范围的作品（发布后 {first["age_band"]} 采集）。指标是累计值，不能当成严格实验。')


def patterns(df,rows,metric):
    st.markdown('### 哪类内容值得继续做？')
    known=df[~df.category.isin(['未分类',''])]
    if known.category.nunique()<2:
        st.info('先分出至少两类作品，才有比较意义。这里暂不画「未分类」图。')
        label_editor(rows,'patterns');return
    fixed='analysis_window' in known and known.analysis_window.iloc[0]!='当前累计'
    if fixed:scoped=known;st.caption('本页已限定同一固定观察窗口。')
    else:
        bands=list(known.age_band.unique())
        band=st.selectbox('让作品有相近的积累时间',bands,key='pattern_age')
        scoped=known[known.age_band==band]
    summary=group_summary(scoped.dropna(subset=[metric]),'category',metric)
    if summary.empty:st.info('这些分类还没有所选目标的数据。');return
    summary=summary.sort_values('median',ascending=metric=='bounce_rate_2s')
    summary['典型表现']=summary['median'].map(lambda v:display(v,metric))
    summary['样本说明']=summary.n.map(lambda n:f'{n}条'+(' · 待积累' if n<5 else ''))
    summary['plot_value']=summary['median']*(100 if metric in RATIO else 1)
    axis=NAMES[metric]+('（%）' if metric in RATIO else '')
    fig=px.bar(summary,x='plot_value',y='category',orientation='h',text='典型表现',custom_data=['样本说明'],labels={'category':'','plot_value':axis},color_discrete_sequence=['#80B9AC'])
    fig.update_traces(hovertemplate='%{y}<br>%{text}<br>%{customdata[0]}<extra></extra>',textposition='outside',cliponaxis=False)
    fig.update_layout(height=max(280,len(summary)*55),showlegend=False)
    chart(fig)
    st.write('**怎么用：** 看哪类的日常表现更好，而不是只看最高的一条；少于5条的分类先继续积累，不急着下结论。')
    st.table(summary[['category','典型表现','样本说明']].rename(columns={'category':'内容分类'}))
    with st.expander('进一步看：时长、发布时间、角色是否有差别？'):
        st.caption('只有同一条件下有足够作品时才着色；数据不够就保持空白。')
        dimension=st.selectbox('想进一步比较什么',['duration_band','publish_hour','topic'],format_func=lambda x:{'duration_band':'视频长短','publish_hour':'发布的时间段','topic':'角色 / 主题'}[x])
        cross=scoped[(scoped[dimension]!='未知') & (scoped[dimension]!='')].groupby(['category',dimension])[metric].agg(n='count',median='median').reset_index()
        if not cross.empty:
            cross['shown']=cross['median'].where(cross.n>=3)*(100 if metric in RATIO else 1)
            matrix=cross.pivot(index='category',columns=dimension,values='shown')
            counts=cross.pivot(index='category',columns=dimension,values='n').reindex(index=matrix.index,columns=matrix.columns)
            if matrix.notna().any().any():
                fig=px.imshow(matrix,color_continuous_scale=['#2D3741','#80B9AC'],aspect='auto',labels={'color':axis})
                fig.update_traces(customdata=counts.to_numpy(),hovertemplate='%{y} · %{x}<br>典型表现=%{z:.2f}<br>%{customdata}条作品<extra></extra>');chart(fig)
                st.write('**怎么用：** 找到同一分类在不同条件下的差异，选一个条件做下一轮测试。每格至少3条，仅作探索。')
            else:st.info('每个组合还不足3条，不生成颜色差异。')
        else:st.info('暂时缺少这些标签。时长和角色可在作品详情补充。')
    with st.expander('进一步看：播放高，观众反馈也好吗？'):
        from creatorlab.platforms import FEEDBACK
        quality=st.selectbox('观众反馈',FEEDBACK[rows[0]['platform']],format_func=NAMES.get)
        points=scoped.dropna(subset=[quality]).copy()
        if len(points)>=3:
            points['feedback']=points[quality]*100
            fig=px.scatter(points,x='views',y='feedback',color='category',hover_name='title',labels={'views':'播放量','feedback':NAMES[quality]+'（%）','category':'内容分类'})
            fig.add_hline(y=float(points.feedback.median()),line_dash='dot');fig.add_vline(x=float(points.views.median()),line_dash='dot');chart(fig)
            st.write('**怎么用：** 右上角是播放和反馈都较好的作品，值得复盘；左上角的作品反馈好但播放低，可以先检查标题、封面和开头。图表本身不能证明问题出在哪里。')
        else:st.info('至少需要3条有观众反馈的作品。')
    with st.expander('原始数据与统计明细'):
        table(summary.drop(columns=['plot_value']),hide_index=True,use_container_width=True)


def cross_platform(rows,aid,window="当前累计"):
    st.markdown('### 同一内容，在哪个平台更值得复用？')
    if window!='当前累计':
        from creatorlab.measurements import window_rows
        rows,_=window_rows(rows[0]['_db'],rows,window)
    df=frame(rows)
    if df.empty:st.info('双方尚无这个固定窗口的实测记录。');return
    linked=df[df.project_id.notna() & (df.baseline_n>=5)&(df.age_band.isin(['7–29天','30–89天','90天以上']) if window=='当前累计' else True)].copy()
    project_ids=linked.loc[linked.account_id==aid,'project_id'].unique()
    groups=linked[linked.project_id.isin(project_ids)].groupby('project_id').filter(lambda g:g.platform.nunique()>=2)
    if groups.empty:
        st.info('先在「内容关联」中把同一内容的抖音和B站版本连起来。每个平台还需要至少5条相近发布时长的历史作品，才能比较。')
        st.caption('准备好后，这里会显示它在各自账号上，比平时表现好多少。');return
    groups['内容']=groups.project_name.fillna(groups.project_id.astype(str));groups['平台']=groups.platform.map(PLATFORMS)
    fig=px.bar(groups,x='内容',y='relative_views',color='平台',barmode='group',labels={'relative_views':'相当于平时的几倍'},color_discrete_sequence=['#80B9AC','#9DAFD0'])
    fig.add_hline(y=1,line_dash='dot');chart(fig)
    st.write('**怎么用：** 1倍表示这个账号的日常水平。某条内容在B站达到2倍、在抖音只有0.8倍，值得先研究B站版本的做法。')
    st.caption('各平台分别与自己的历史比较，不直接用绝对播放量给平台排名。各版本的作品年龄仍可能不同。')


def analysis_dashboard(rows):
    st.subheader('作品分析 · 找到下一步')
    st.caption('先看重点，再按需要打开作品对照和详细图表。')
    active=st.session_state.get('active_platform')
    if not any(not active or r['platform']==active for r in rows):st.info('这个平台还没有作品，请先在「账号与同步」导入。');return
    scoped,metric=select_scope(rows,'analysis')
    analysis_window=st.radio('观察口径',['当前累计','24小时','7天','30天'],horizontal=True,key='analysis_window')
    original_scoped=scoped
    unknown_time=sum(r.get('views') is not None and not r.get('metric_recorded_at') for r in scoped)
    if unknown_time:st.info(f'{unknown_time}条作品保留了累计数字，但原始观测时刻未确认。图表仍可查看；固定窗口与画像判断需要重新同步真实字段。')
    if analysis_window!='当前累计':
        from creatorlab.measurements import window_rows
        scoped,window_status=window_rows(original_scoped[0]['_db'],original_scoped,analysis_window)
        with st.expander('固定窗口数据覆盖与待办'):
            st.table(pd.DataFrame(window_status))
            st.caption('旧的混合快照不会自动当成固定窗口数据；已错过的窗口不能从今天的累计值回推。')
        if not scoped:st.info('当前没有这个窗口的实测记录，先用当前累计探索；新作品到期时再同步或导入真实历史观测。');return
    timezone='Asia/Shanghai'
    with st.expander('调整分析范围（可选）'):
        timezone=st.selectbox('发布时间按哪个时区看',['Asia/Shanghai','America/Los_Angeles','UTC'])
        full=frame(scoped,timezone)
        if full.empty:st.info('这个账号还没有可靠的播放记录。');return
        ages=list(full.age_band.unique())
        selected=st.multiselect('发布到采集经过多久',ages,default=ages)
        st.caption('默认保留全部历史有效作品；只有你主动调整时才按积累时长缩小范围。')
    df=full[full.age_band.isin(selected)].copy()
    if df.empty:
        st.info('所选范围没有作品。先展示这个账号全部作品的已知指标；刚发布或发布时间未知的作品仅供查看，不用于分类优劣结论。')
        df=full.copy()
    df['analysis_window']=analysis_window
    if metric not in df:df[metric]=None
    st.caption(f'本次查看 {len(df)} 条作品 · {analysis_window}观测 · 时间按{timezone}显示')
    tabs=st.tabs(['🎮 成长面板','先看重点','📈 图表总览','对照两条作品','按内容找规律','跨平台复用'])
    with tabs[0]:
        from creatorlab.loop_ui import next_actions
        next_actions(scoped,metric,due_rows=original_scoped)
        from creatorlab.growth_ui import growth_dashboard
        growth_dashboard(df,scoped,metric)
    with tabs[1]:overview(df,scoped,metric)
    with tabs[2]:visual_overview(df,metric)
    with tabs[3]:compare_works(df,metric)
    with tabs[4]:patterns(df,scoped,metric)
    with tabs[5]:cross_platform(rows,scoped[0]['account_id'],analysis_window)


def assistant_dashboard(rows):
    st.subheader('创作助手 · 这次只做一件事')
    st.caption('选一条具体作品，做一个小改动，再用下一条的表现验证。')
    if not rows:st.info('导入作品后，我会帮你选出值得先复盘的一条。');return
    scoped,metric=select_scope(rows,'assistant')
    df=frame(scoped)
    if df.empty:st.info('先同步可靠的作品数据，才能开始复盘。');return
    from creatorlab.creative_brief_ui import planning_panel
    planning_panel(scoped,metric)
    st.markdown('### 历史复盘线索')
    known_tracks=[t for t in TRACKS if t in df.track.unique()]
    track=known_tracks[0] if known_tracks else '暂不指定'
    st.caption('建议按已确认的作品分类生成；修改赛道请用统一分类入口。')
    findings=pattern_findings(df[df.track==track],metric) if track!='暂不指定' else []
    hook=hook_observation(df) if metric=='completion_rate' else None
    pair=representative_pair(df,metric)
    title='先找出一个值得复用的做法'
    if findings:
        f=findings[0];title=f'下一条，继续验证「{f["category"]}」'
        because=f'同一发布时长范围内，「{f["category"]}」的典型{NAMES[metric]}为{display(f["value"],metric)}，「{f["other"]}」为{display(f["other_value"],metric)}。两类分别有{f["n"]}和{f["other_n"]}条。'
        pool=df[(df.category==f['category'])&(df.age_band==f['age'])]
        reference=pool.sort_values(metric,ascending=False).iloc[0].to_dict()
    elif hook:
        reference=hook['row'];title='下一条，先测试更直接的开头'
        because=f'这条作品的2秒离开比例为{display(reference["bounce_rate_2s"],"bounce_rate_2s")}，同组{hook["n"]}条作品的典型水平为{display(hook["typical"],"bounce_rate_2s")}。'
    elif pair:
        reference,other,n=pair
        because=f'这条作品的{NAMES[metric]}为{display(reference[metric],metric)}，同范围的参照作品「{other["title"][:35]}」为{display(other[metric],metric)}。先看它们最明显的做法差异。'
    else:
        reference=None;because='现在还没有足够的可比记录，暂时不推荐具体作品。先补充分组或目标指标，再生成复盘任务。'
    with st.container(border=True):
        st.markdown('### '+title)
        st.write('**为什么先做这个**');st.write(because)
        if reference:
            st.write('**先打开这条**');st.write('「'+reference['title']+'」');work_link(reference)
            st.write('**下一条具体怎么做**')
            if track in TRACK_TESTS:st.write(TRACK_TESTS[track])
            else:st.write('先对照选题、前2秒、节奏和结尾，选出一处明显差异。下一条只尝试复用这一处，保持其余做法尽量相近。')
            if not findings:st.caption('上面是待测试的做法，不是已经证明有效的账号结论。')
            st.write(f'**怎么知道有没有帮助**：发布后第7天记录{NAMES[metric]}，连续做3条相近作品再复盘；已有累计数据仅供参照，不能直接当成固定7天基准。')
            with st.expander('查看依据与限制'):
                st.write('对照来自同账号、同平台和相同发布时长范围。投流、热点和受众差异没有被控制，因此这是一项实验建议，不保证增长。')
                st.caption('分享、收藏、点赞比例分别是次数除以播放，不是独立观众转化率。')
        else:st.write('**现在可以做：** 给两类常做的内容各标5条，或者重新同步所选目标的数据。')
    if reference:
        st.markdown('#### 开拍前，留一句给自己')
        st.text_area('下一条我只改什么？',placeholder='例如：把成片画面放在第一秒，其余保持相近',key=f'assistant_note_{scoped[0]["account_id"]}')
        st.caption('这段笔记仅在本次页面会话保留。')
    label_editor(scoped,'assistant')


def performance_chart(df,metric,key):
    usable=df.dropna(subset=[metric])
    if usable.empty:
        st.info(f'暂时缺少{NAMES[metric]}。以下仅展示已知播放量，不代表所选目标的表现。')
        metric='views';usable=df.dropna(subset=[metric])
    if usable.empty:return
    top=usable.sort_values(metric,ascending=metric!='bounce_rate_2s').tail(8).copy()
    top['作品']=[f'{i+1}. '+str(title)[:28] for i,title in enumerate(top.title)]
    top['显示值']=top[metric].map(lambda v:display(v,metric))
    top['图表数值']=top[metric]*(100 if metric in RATIO else 1)
    fig=px.bar(top,x='图表数值',y='作品',orientation='h',text='显示值',hover_name='title',
      labels={'图表数值':NAMES[metric]+('（%）' if metric in RATIO else '')},color_discrete_sequence=['#80B9AC'])
    fig.update_traces(textposition='outside',cliponaxis=False,hovertemplate='%{hovertext}<br>%{text}<extra></extra>')
    fig.update_layout(height=max(260,len(top)*42),showlegend=False)
    chart(fig,key=key)
    st.caption('每根横条是一条作品；这是当前累计记录的对照，不代表表现差异由某种内容形式造成。')


def visual_overview(df,metric):
    st.markdown('### 图表总览 · 不分组也能看')
    st.write('**先定位值得复盘的作品，再看播放和观众反馈能否同时做好。**')
    performance_chart(df,metric,'visual_performance')
    bands=pd.cut(df.views,bins=[0,500,1000,3000,10000,100000,float('inf')],right=False,
       labels=['500以下','500–999','1000–2999','3000–9999','1万–10万','10万以上'])
    counts=bands.value_counts(sort=False).rename_axis('播放区间').reset_index(name='作品数')
    st.markdown('#### 你的作品大多处在哪个播放区间？')
    fig=px.bar(counts,x='播放区间',y='作品数',text='作品数',color_discrete_sequence=['#9DAFD0'])
    fig.update_yaxes(dtick=1);chart(fig,key='visual_distribution')
    st.caption('用来认识账号日常水平，避免只盯着最高的一条；不拿它与其他平台的绝对播放量直接排名。')
    from creatorlab.platforms import FEEDBACK
    options=[m for m in FEEDBACK[df.platform.iloc[0]] if m in df and df[m].notna().sum()>=3]
    st.markdown('#### 播放高，观众反馈也好吗？')
    if not options:st.info('还缺少至少3条观众反馈记录；同步留存或互动指标后，这里会显示交叉散点图。');return
    quality=st.selectbox('看哪种反馈',options,format_func=NAMES.get,key='visual_feedback')
    points=df.dropna(subset=[quality]).copy();points['反馈比例']=points[quality]*100
    fig=px.scatter(points,x='views',y='反馈比例',hover_name='title',labels={'views':'累计播放量','反馈比例':NAMES[quality]+'（%）'},color_discrete_sequence=['#80B9AC'])
    fig.add_hline(y=float(points['反馈比例'].median()),line_dash='dot');fig.add_vline(x=float(points.views.median()),line_dash='dot')
    chart(fig,key='visual_scatter')
    st.write('**怎么用：** 右上角的作品播放与反馈都较好；左上角的作品反馈好但播放低，值得回看包装和选题。接着去「对照两条作品」找一处可验证的差异。')
