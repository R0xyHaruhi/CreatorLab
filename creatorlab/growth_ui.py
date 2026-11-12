"""A creator growth playground: radar, niche map, learning references and experiments."""
import json
import os
from datetime import date
from urllib.parse import quote
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from creatorlab.appearance import chart
from creatorlab.genres import TAXONOMY,init_genres,genre_rows,verticality,set_genre,suggest_title,apply_ai_labels
from creatorlab.growth import AXES,radar_scores,save_experiment,experiments,update_experiment
from creatorlab.peers import save_peer,peer_rows,comparable
from creatorlab.review import display,NAMES
from creatorlab.ai import generate,AIError
from creatorlab.hub import connect


def ai_controls():
    choice=st.selectbox('AI方式',['关闭','本地Ollama','OpenAI'],key='growth_ai_provider')
    if choice=='关闭':st.caption('未启用模型；标题规则建议会明确标注，手动分类与所有图表仍可用。')
    else:st.caption('仅点击AI按钮时发送所列作品标题与赛道标签；不发送视频、封面、Cookie或数据库。AI候选没有实时网页核验。')
    provider={'关闭':'none','本地Ollama':'ollama','OpenAI':'openai'}[choice]
    if provider=='openai':
        st.text_input('API Key（可留空使用本机环境变量）',type='password',key='growth_api_key')
        st.text_input('模型名称',value=os.getenv('OPENAI_MODEL','gpt-4.1-mini'),key='growth_model_openai')
        st.caption('Key仅保存在当前页面会话，不写入作品库或导出文件。模型服务可能收费。')
    elif provider=='ollama':
        st.text_input('本地模型名称',value=os.getenv('OLLAMA_MODEL','qwen2.5:3b'),key='growth_model_ollama')
    return provider


def call_ai(provider,prompt,context):
    return generate(provider,prompt,context,model=st.session_state.get('growth_model_'+provider),api_key=st.session_state.get('growth_api_key') or None)


def radar_panel(df,rows):
    st.markdown('### 🛡️ 作品表现画像')
    st.caption('六个维度帮你看清一条作品的优势；50表示落在同组历史的中间，不是行业及格线。')
    from creatorlab.loop_ui import baseline_controls
    baseline_df=baseline_controls(df,rows)
    exploratory=st.checkbox('小样本探索（至少3条，仅观察不判胜负）',value=len(df)<5,key='radar_exploratory')
    minimum=3 if exploratory else 5
    ids=list(df.id)
    chosen=st.selectbox('拿哪条作品来看看',ids,format_func=lambda i:df.loc[df.id==i,'title'].iloc[0][:70],key='radar_work')
    row=df[df.id==chosen].iloc[0].to_dict()
    from creatorlab.creator_ui import cover
    a,b=st.columns([1,3])
    with a:
        cover(row,145);st.write(row['title']);st.caption('发布至采集：'+row['age_band'])
    with b:
        series=[('这条作品',radar_scores(baseline_df,row,min_n=minimum),'#80B9AC')]
        other=st.selectbox('叠加另一条作品',[None]+[i for i in ids if i!=chosen],format_func=lambda i:'不叠加' if i is None else df.loc[df.id==i,'title'].iloc[0][:50],key='radar_compare')
        if other is not None:
            other_row=df[df.id==other].iloc[0].to_dict()
            series.append(('对照作品',radar_scores(baseline_df,other_row,min_n=minimum),'#9DAFD0'))
        ready=sum(s['score'] is not None for s in series[0][1])
        if ready>=3:
            fig=go.Figure()
            labels=[x['axis'] for x in series[0][1]]
            fig.add_trace(go.Scatterpolar(r=[50]*7,theta=labels+[labels[0]],name='同组中间位置',line=dict(dash='dot',color='#87919C'),mode='lines',hoverinfo='skip'))
            for name,scores,color in series:
                values=[x['score'] for x in scores]
                fig.add_trace(go.Scatterpolar(r=values+[values[0]],theta=labels+[labels[0]],name=name,
                    fill='toself' if all(v is not None for v in values) else 'none',connectgaps=False,
                    line=dict(color=color,width=3),mode='lines+markers',hovertemplate='%{theta}：历史位置%{r:.0f}/100<extra>%{fullData.name}</extra>'))
            fig.update_layout(polar=dict(gridshape='linear',radialaxis=dict(range=[0,100],tickvals=[25,50,75,100])),height=430,legend=dict(orientation='h'))
            chart(fig,key='growth_radar')
            if ready<6:st.info(f'已绘制 {ready}/6 个可用维度；其余保留缺口，补采后自动补全。')
        else:
            st.warning('当前数据不足，暂时无法生成作品画像。')
            absent=[s['axis'] for s in series[0][1] if s['value'] is None]
            if absent:st.write('尚未取得可比指标：'+'、'.join(absent)+'。')
            if not absent:st.write('当前范围有效作品不足；至少3条才能开始小样本探索。')
            if row['platform']=='bilibili':
                from creatorlab.bilibili_ui import repair_panel
                repair_panel(row.get('_db'),str(row.get('handle','')))
    available=[k for _,k in AXES[row['platform']] if k in df and df[k].notna().sum()>=5]
    if len(available)>=2:
        corr=df[available].corr(method='spearman')
        coupled=[(a,b) for i,a in enumerate(available) for b in available[i+1:] if pd.notna(corr.loc[a,b]) and abs(corr.loc[a,b])>=.8]
        if coupled:st.caption('当前数据中部分维度高度相关：'+ '；'.join(NAMES.get(a,a)+'与'+NAMES.get(b,b) for a,b in coupled[:3])+'。它们不代表独立能力，不合成总分。')
    scores=series[0][1]
    for start in (0,3):
        cols=st.columns(3)
        for col,s in zip(cols,scores[start:start+3]):
            col.metric(s['axis'],display(s['value'],s['metric']))
            col.caption(('同组历史位置 '+f'{s["score"]:.0f}/100' if s['score'] is not None else '相对位置未知')+f' · 样本{s["n"]}')
    usable=[s for s in scores if s['score'] is not None]
    if not usable:st.info('补齐真实指标、发布时间和同组样本后自动计算；当前没有生成作品得分。')
    if usable:
        strongest=max(usable,key=lambda s:s['score']);lowest=min(usable,key=lambda s:s['score'])
        st.write(f'**这条的亮点：{strongest["axis"]}。** 可以优先回看它在这一点上用了什么做法。')
        if strongest['score']!=lowest['score']:st.write(f'**下一次可测试：{lowest["axis"]}。** 这只是相对位置较低，不能据此断定内容有问题。')
    st.caption('常规每轴至少5条；探索模式允许3–4条并明确标注。参照限定账号、平台与观察窗口；缺失轴不补0、不填满多边形。B站用投币支持，抖音用留住观众。')
    with st.expander('看原始数值与六维算法'):
        st.table(pd.DataFrame([{'维度':s['axis'],'原始数值':display(s['value'],s['metric']),'历史位置':f'{s["score"]:.0f}/100' if s['score'] is not None else '样本不足 / 未采集','参照作品数':s['n']} for s in scores]))
        st.write('历史位置 =（低于当前值的作品数 + 一半并列作品数）÷ 有效作品数。没有总分，不把粉丝规模当内容质量。默认参照随入库变化；可保存并选择固定参照组跟踪进步。')


def genres_panel(db,rows,provider):
    platform=rows[0]['platform'];aid=rows[0]['account_id'];taxonomy=TAXONOMY[platform]
    labelled=genre_rows(db,rows);v=verticality(labelled)
    st.markdown('### 🧭 赛道地图')
    st.caption('这是CLab的内容分析标签体系，不声称与平台官方分区完全相同；分区 → 细分赛道，与“变装/教程”等表现形式标签并存。')
    with st.expander('查看这个平台的分区与细分赛道'):
        st.table(pd.DataFrame([{'分区':m,'细分赛道':'、'.join(items)} for m,items in taxonomy.items()]))
    a,b=st.columns(2)
    a.metric('作品识别覆盖率',f'{v["coverage"]:.0%}')
    b.metric('已识别作品中，同一赛道占比',f'{v["share"]:.0%}' if v['share'] is not None else '待识别')
    if v['minor']:st.write(f'目前已识别部分主要集中在 **{v["major"]} → {v["minor"]}**。')
    if v['counts']:
        data=[{'赛道':m+' / '+s,'作品数':n} for (m,s),n in v['counts'].items()]
        if v['total']>v['labelled']:data.append({'赛道':'尚未识别','作品数':v['total']-v['labelled']})
        chart(px.pie(pd.DataFrame(data),names='赛道',values='作品数',hole=.6,color_discrete_sequence=['#80B9AC','#9DAFD0','#C7A17C','#6F7D87']),key='growth_verticality')
    st.caption('覆盖率低时不能把这一比例解释为整个账号的垂直度。垂直只是内容一致性，不是越高越值得追求。')
    a,b=st.columns(2)
    if a.button('用标题关键词先给建议',key='genre_rules'):
        n=0
        for r in rows:
            guess=suggest_title(platform,r['title'])
            if guess:n+=bool(set_genre(db,r['id'],guess['major'],guess['minor'],'title_rule',guess['confidence'],guess['evidence']))
        st.success(f'保存了 {n} 条规则建议；含糊或跨赛道的标题保持未知。');st.rerun()
    if b.button('AI分析作品赛道',disabled=provider=='none',key='genre_ai'):
        sample=rows[:60]
        try:
            answer=call_ai(provider,'只返回JSON对象 {"labels":[{"id":整数,"major":"合法分区","minor":"合法细分","confidence":0到1,"evidence":"标题中的原文短片段"}]}。仅按标题判断，含糊时省略。禁止虚构已观看画面。',{'taxonomy':taxonomy,'titles':[{'id':r['id'],'title':r['title']} for r in sample]})
            n=apply_ai_labels(db,platform,sample,answer);st.success(f'保存 {n} 条AI建议。');st.rerun()
        except (AIError,ValueError,TypeError,KeyError) as exc:st.error(str(exc))
    st.caption('AI每次最多分析60条当前作品；规则结果与AI结果均可纠正，模型自报置信度不是正确率，手动确认不会被覆盖。')
    from creatorlab.classification_ui import editor
    editor(db,rows,'genre')
    with st.expander('逐条检查识别依据'):
        st.table(pd.DataFrame([{'作品':r['title'],'赛道':r['genre']['major']+' / '+r['genre']['minor'] if r.get('genre') else '未知','来源':r['genre']['origin'] if r.get('genre') else '未分析','依据':r['genre']['evidence'] if r.get('genre') else ''} for r in labelled]))
    return v


def learning_panel(db,rows,df,provider,v):
    from creatorlab.hub import connect,fmt_count
    from creatorlab.bilibili_account import latest_fields
    platform=rows[0]['platform'];aid=rows[0]['account_id'];taxonomy=TAXONOMY[platform]
    with connect(db) as con:manual=con.execute('SELECT major,minor FROM hub_account_genres WHERE account_id=?',(aid,)).fetchone()
    pairs=[(m,s) for m,items in taxonomy.items() for s in items]
    inferred=(manual['major'],manual['minor']) if manual else (v.get('major'),v.get('minor'))
    if inferred not in pairs:
        from collections import Counter
        guesses=[suggest_title(platform,r['title']) for r in rows]
        ranked=Counter((g['major'],g['minor']) for g in guesses if g)
        inferred=ranked.most_common(1)[0][0] if ranked and ranked.most_common(1)[0][1]>=2 else None
    choices=[None]+pairs
    pair=st.selectbox('当前学习对标赛道',choices,index=choices.index(inferred) if inferred in choices else 0,format_func=lambda p:'先确认内容赛道' if p is None else p[0]+' / '+p[1],key='peer_genre')
    st.markdown('### 🔭 找学习对象，比较做法')
    st.caption('先按细分赛道筛选。AI给候选，用户可更换；数值比较只用注明来源、样本数与观察窗口的数据。')
    if pair is None:
        st.info('现有作品信息不足，暂不推荐无关博主。确认上方赛道，或先在“统一分类”中分析作品。')
        return
    if not manual and not v.get('minor'):st.info('这是按标题关键词给出的初步赛道建议，可修改；未把它当成已确认的账号定位。')
    from creatorlab.discovery import search_url,query_for
    keyword=st.text_input('按什么作品内容寻找同类创作者',value=query_for(pair[1],rows),key='peer_keyword',max_chars=80).strip()
    st.caption('搜索相关视频，再从视频作者中找参照；匹配作品会展示出来，不按用户名包含赛道词来推荐。')
    st.link_button('查看相关视频与作者',search_url(platform,keyword or pair[1]))
    from pathlib import Path
    import subprocess,sys
    from creatorlab.bilibili_import import job_running
    root=Path(__file__).resolve().parent.parent
    (root/'local').mkdir(exist_ok=True)
    if st.button('实时发现这个赛道的学习对象',key='peer_discover',disabled=job_running(root)):
        with open(root/'local'/'discovery.log','a',encoding='utf-8') as log:
            subprocess.Popen([sys.executable,'-m','creatorlab.discovery','--db',str(db),'--root',str(root),'--platform',platform,'--major',pair[0],'--minor',pair[1],'--keyword',keyword or pair[1]],cwd=str(root),stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
        st.info('已打开平台实时搜索。验证完成后刷新此页；搜索候选仍需确认赛道。')
    status_file=root/'local'/'discovery_status.json'
    if status_file.exists():
        try:
            status=json.loads(status_file.read_text(encoding='utf-8'));st.caption('实时发现：'+status.get('info',''))
        except (ValueError,OSError):pass

    if st.button('AI建议学习对象候选',disabled=provider=='none',key='peer_ai'):
        try:
            answer=call_ai(provider,'建议最多3个你有把握真实存在且匹配该细分赛道的学习对象。仅返回 {"candidates":[{"name":"名称","url":"官方个人主页HTTPS链接","why":"选题/表达/制作上可学习的具体差别"}]}。不提供粉丝和表现数字，不编排名，没有把握则返回空列表；你的记忆不等于当前核验。',{'platform':platform,'major':pair[0],'minor':pair[1],'my_titles':[r['title'] for r in rows[:12]]})
            payload=json.loads(answer.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip());n=0
            for candidate in payload.get('candidates',[])[:3]:
                try:n+=bool(save_peer(db,platform,candidate['name'],candidate['url'],*pair,'ai_unverified',candidate.get('why','')))
                except (ValueError,KeyError,TypeError):continue
            st.success(f'保存 {n} 个待核验候选；它们不是经过实时验证的头部排行。')
        except (AIError,ValueError,TypeError,KeyError) as exc:st.error(str(exc))
    with st.expander('手动指定学习对象 / 填写真实参照数据'):
        with st.form('peer_manual'):
            name=st.text_input('创作者名称');url=st.text_input('官方个人主页链接');why=st.text_area('我想学什么 / 已观察到的做法差别')
            followers=st.text_input('粉丝数（未知留空）');sample_n=st.number_input('作品参照样本数',0,5000,0)
            ref_window=st.selectbox('参照数据观察口径',['当前累计','24小时','7天','30天'],key='ref_window')
            age_band=st.selectbox('这些作品在什么发布时长采集',['0–6天','7–29天','30–89天','90天以上'])
            observed=st.date_input('数据观察日期',date.today());source=st.text_input('这些数值的来源链接（数值比较必填）')
            raw={}
            for key,label in AXES[platform]:
                raw[label]=st.text_input('每条作品'+NAMES[label]+('的中位数（填写0–100百分数）' if label.endswith('_ratio') or label=='completion_rate' else '的中位数'),key='ref_'+label)
            if st.form_submit_button('保存这个参照'):
                try:
                    data={'sample_n':sample_n,'age_band':age_band,'window_name':ref_window,'observed_at':observed.isoformat(),'source_url':source}
                    if followers.strip():data['followers']=int(followers)
                    for key,text in raw.items():
                        if text.strip():data[key]=float(text)/(100 if key.endswith('_ratio') or key=='completion_rate' else 1)
                    save_peer(db,platform,name,url,*pair,'manual',why,data);st.success('已保存用户录入的参照。')
                except ValueError as exc:st.error(str(exc))
    refs=peer_rows(db,platform,*pair)
    if not refs:st.info('还没有学习参照。可以启用AI推荐候选，或手动指定你认可的博主。');return
    own=latest_fields(db,aid).get('followers',{}).get('value') if platform=='bilibili' else None
    from creatorlab.discovery import segment
    priority={'同量级':0,'稍领先':1,'规模未知':2,'较大账号参考':3,'更小规模':4}
    refs.sort(key=lambda r:(priority[segment(r['data'].get('followers'),own)],-r['data'].get('matched_videos',0)))
    for ref in refs:
        with st.container(border=True):
            status={'ai_unverified':'AI候选 · 尚待核验','public_search':'平台实时搜索发现 · 赛道待确认','manual':'用户指定 · 数值由用户录入'}[ref['origin']]
            status+=' · '+segment(ref['data'].get('followers'),own)
            st.markdown('**'+ref['name']+'**');st.caption(status);st.link_button('打开主页核对',ref['url'])
            if st.button('忽略这个学习对象',key=f'peer_remove_{ref["id"]}'):
                with connect(db) as con:con.execute('DELETE FROM clab_learning_refs WHERE id=?',(ref['id'],))
                st.rerun()
            if ref['why']:st.write(('待核对的学习方向：' if ref['origin']=='ai_unverified' else '')+ref['why'])
            if ref['data'].get('matched_titles'):
                st.caption(f'匹配依据：当前搜索发现 {ref["data"].get("matched_videos",0)} 条相关作品，并非账号全部作品。')
                for title,link in zip(ref['data']['matched_titles'][:3],ref['data'].get('evidence_urls',[])[:3]):
                    if link.startswith('https://www.bilibili.com/video/BV'):st.link_button(title,link)
            fans=ref['data'].get('followers')
            if fans is not None:
                st.caption('参照粉丝数：'+fmt_count(fans))
                if own and fans>=own*10:st.caption('按录入规模属于较大账号参考；规模差距本身不说明内容质量。')
            if platform=='bilibili':reference_live_panel(db,ref,rows,df,pair)
            age=st.selectbox('用哪一组自己的作品比较',['0–6天','7–29天','30–89天','90天以上'],key=f'peer_age_{ref["id"]}')
            window=str(df.analysis_window.iloc[0]) if 'analysis_window' in df else '当前累计'
            if not comparable(ref,age,window=window,min_n=1):st.caption('尚不能进行数值对标：需要近期来源、实际样本及一致的观察窗口与发布时长。');continue
            cohort=df if window!='当前累计' else df[df.age_band==age]
            labelled_ids=[r['id'] for r in genre_rows(db,rows) if r.get('genre') and (r['genre']['major'],r['genre']['minor'])==pair]
            cohort=cohort[cohort.id.isin(labelled_ids)]
            if not len(cohort):st.caption('你还没有这个细分赛道与观察范围的记录。');continue
            if min(len(cohort),ref['data'].get('sample_n',0))<5:st.warning('少样本事实对照，只展示数值，不判断谁更好。')
            values=[]
            for axis,key in AXES[platform]:
                own_vals=cohort[key].dropna() if key in cohort else pd.Series(dtype=float)
                target=ref['data'].get(key)
                if len(own_vals)>=1 and target is not None:values.append({'维度':axis,'我的典型值':display(own_vals.median(),key),'参照典型值':display(target,key)})
            if values:st.table(pd.DataFrame(values));st.caption('同平台、同细分赛道和同发布时长的用户录入参照，仍未控制热点、投流和粉丝规模。')
            else:st.caption('双方暂时没有足够的共同指标。')


def challenge_panel(db,rows,metric):
    from creatorlab.loop_ui import experiment_panel
    experiment_panel(db,rows,metric)


def growth_dashboard(df,rows,metric):
    db=rows[0].get('_db')
    if not db:st.info('需要本地作品库才能保存分类与挑战。');return
    init_genres(db)
    provider=ai_controls()
    tabs=st.tabs(['作品画像','统一分类','学习对象','创作实验','素材复盘'])
    labelled=genre_rows(db,rows);v=verticality(labelled)
    with tabs[0]:radar_panel(df,rows)
    with tabs[1]:genres_panel(db,rows,provider)
    with tabs[2]:learning_panel(db,rows,df,provider,v)
    with tabs[3]:challenge_panel(db,rows,metric)
    with tabs[4]:
        st.info('视频体检与原素材复盘已集中到「创作进阶 → 视频体检」。先做本地检测，再自行选择是否接入AI。')
        if st.button('打开视频体检',key='material_open_from_growth'):
            st.session_state['_open_video_check']={'post_id':rows[0]['id'],'account_id':rows[0]['account_id']};st.rerun()


def reference_live_panel(db,ref,rows,own_df,pair):
    """Selected public reference import; never merges the reference into your score."""
    from pathlib import Path
    import subprocess,sys
    from creatorlab.bilibili_import import job_running
    from creatorlab.hub import latest_posts,connect
    from creatorlab.content_analysis import frame
    uid=ref['url'].split('/')[-1] or ref['url'].split('/')[-2]
    root=Path(__file__).resolve().parent.parent
    if st.button('采集这个B站参照的真实公开作品',key=f'ref_import_{ref["id"]}',disabled=job_running(root)):
        with connect(db) as con:own=con.execute("SELECT is_self FROM hub_accounts WHERE platform='bilibili' AND handle=?",(uid,)).fetchone()
        if own and own['is_self']:st.error('这个UID已经是个人账号，不作为外部参照导入。')
        else:
            root.joinpath('local').mkdir(exist_ok=True)
            with open(root/'local'/'reference_import.log','a',encoding='utf-8') as log:
                subprocess.Popen([sys.executable,'-m','creatorlab.reference_import','--db',str(db),'--root',str(root),'--uid',uid],cwd=str(root),stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
            st.info('已启动参照采集窗口：收集公开列表及最近50条详情。刷新本页后可选择同赛道作品对比。')
    imported=[r for r in latest_posts(db,include_references=True) if r['platform']=='bilibili' and r['handle']==uid and r['account_id']!=rows[0]['account_id']]
    if not imported:return
    st.caption(f'已采到该UID的 {len(imported)} 条公开作品；先确认哪些属于当前细分赛道。采集不等于已核实它是头部。')
    from creatorlab.bilibili_account import latest_fields
    followers=latest_fields(db,imported[0]['account_id']).get('followers')
    if followers:st.caption(f'参照UID实际采到的粉丝量：{followers["value"]:,} · 采集时间：{followers["recorded_at"]}')
    with st.expander('选择同赛道参照作品，建立真实数据对照'):
        ids=st.multiselect('确认这些参照作品属于 '+pair[1],[r['id'] for r in imported],format_func=lambda i:next(r['title'][:70] for r in imported if r['id']==i),key=f'ref_posts_{ref["id"]}')
        if st.button('确认这些参照作品',key=f'ref_confirm_{ref["id"]}'):
            for i in ids:set_genre(db,i,*pair)
            st.rerun()
        band=st.selectbox('参照与自己使用同一发布时长',['0–6天','7–29天','30–89天','90天以上'],key=f'ref_live_age_{ref["id"]}')
        def selected(data):
            result=[r['id'] for r in genre_rows(db,data) if r.get('genre') and (r['genre']['major'],r['genre']['minor'])==pair]
            f=frame(data)
            return f[f.id.isin(result)&((f.age_band==band) if window=='当前累计' else True)] if not f.empty else f
        window=str(own_df.analysis_window.iloc[0]) if 'analysis_window' in own_df else '当前累计'
        if window!='当前累计':
            from creatorlab.measurements import window_rows
            imported,_=window_rows(db,imported,window)
        mine=selected(rows);theirs=selected(imported)
        if not len(mine) or not len(theirs):st.info(f'自己 {len(mine)} 条 / 参照 {len(theirs)} 条，还没有双方同口径记录。');return
        if min(len(mine),len(theirs))<5:st.warning('少样本事实对照，不排名、不判优劣。')
        comparison=[]
        for axis,key in AXES['bilibili']:
            left=mine[key].dropna();right=theirs[key].dropna()
            if len(left)>=1 and len(right)>=1:comparison.append({'维度':axis,'我的典型值':display(left.median(),key),'参照典型值':display(right.median(),key),'有效样本':f'{len(left)} / {len(right)}'})
        if comparison:st.table(pd.DataFrame(comparison));st.caption('真实公开记录的中位数比较；没有控制投流、受众和热点，不把粉丝规模差异当作你的失败。')
