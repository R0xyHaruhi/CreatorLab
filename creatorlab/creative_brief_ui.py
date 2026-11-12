"""Local-first planning: inspect evidence, optionally call a model, save one experiment."""
import hashlib
import json
import os
from pathlib import Path
import pandas as pd
import streamlit as st
from creatorlab.ai import generate,AIError,TEXT_PROVIDERS
from creatorlab.creative_brief import build_brief,apply_model_draft,save_plan,plan_experiment,KINDS,confirmed_track
from creatorlab.workflow_store import documents,get
from creatorlab.reference_workflow import selected_scope
from creatorlab.learning_workflow import lessons_for
from creatorlab.review import display,NAMES


def _key(provider):
    env=TEXT_PROVIDERS.get(provider,{}).get('key','OPENAI_API_KEY')
    value=os.getenv(env)
    if value:return value
    try:return st.secrets.get(env)
    except (FileNotFoundError,KeyError):return None


def model_controls(brief,context_hash):
    key='assistant_workflow'
    choices={'仅本地规则':'none','DeepSeek':'deepseek','豆包（火山方舟）':'doubao','本地Ollama':'ollama','OpenAI':'openai'}
    with st.expander('可选模型与中文配置教程'):
        choice=st.selectbox('创作建议生成方式',list(choices),key=key+'_provider')
        provider=choices[choice]
        guide=Path(__file__).resolve().parents[1]/'docs'/'AI_CN.md'
        if st.checkbox('展开中文配置教程',key=key+'_guide'):
            st.markdown(guide.read_text(encoding='utf-8'))
        if provider=='none':
            st.caption('未调用模型。下方本地方案照常可用，事实与待验证做法分开展示。')
            return None
        config=TEXT_PROVIDERS.get(provider,{})
        model_default=os.getenv(config.get('model_env','OLLAMA_MODEL' if provider=='ollama' else 'OPENAI_MODEL')) or config.get('model') or ('qwen2.5:3b' if provider=='ollama' else 'gpt-4.1-mini')
        model=st.text_input('文字模型名称或方舟接入点ID',value=model_default,key=key+'_model_'+provider)
        token=None
        if provider!='ollama':
            token=st.text_input('API Key（仅当前会话；留空读取本机配置）',type='password',key=key+'_key_'+provider)
            st.caption('密钥不写入方案、作品库或导出文件。模型服务可能收费。')
        context={k:brief[k] for k in ('observations','evidence','lessons','limits','cards')}
        st.caption('仅点击下方按钮后发送这份文字摘要；不发送封面、视频、Cookie、数据库文件或登录配置。')
        st.json(context)
        consent_key=key+'_consent'
        destination=context_hash+':'+provider+':'+model
        if st.session_state.get(key+'_consent_context')!=destination:
            st.session_state[consent_key]=False
            st.session_state[key+'_consent_context']=destination
        consent=st.checkbox('同意将上方证据摘要发送给所选模型',key=consent_key)
        if st.button('用所选模型补充待验证建议',key=key+'_generate',disabled=not consent):
            task=('请用中文，只返回JSON对象cards，包含且仅包含选题、标题、封面、内容结构、跨平台复用五类。'
                  '每项格式为{kind,change,hypothesis,evidence_ids}。change是一处具体改动，hypothesis明确为推测，'
                  'evidence_ids只能引用已给的证据id，至少一个。不增加观测事实，不编造看过素材，不把相关当因果，'
                  '不承诺增长或全站排名。使用已有复盘经验时仍要求重复验证。')
            try:
                with st.spinner('根据已列出的证据生成假设…'):
                    text=generate(provider,task,context,model=model,api_key=token or (_key(provider) if provider!='ollama' else None))
                    return apply_model_draft(brief,text)
            except (AIError,ValueError,KeyError,TypeError) as exc:st.error(str(exc))
    return None


def planning_panel(rows,metric,guided=False):
    if not rows or not rows[0].get('_db'):return
    from creatorlab.genres import genre_rows
    from creatorlab.hub import latest_posts,eligible
    from creatorlab.feedback import scoped_selectbox
    from creatorlab.personal_ui import dated_label
    db=rows[0]['_db'];aid=rows[0]['account_id'];platform=rows[0]['platform']
    labelled=genre_rows(db,[r for r in eligible(rows) if not r.get('demo')]);lookup={r['id']:r for r in labelled}
    if not lookup:st.info('当前账号没有可作为创作依据的公开作品。');return
    if not guided:st.markdown('### 创作方案 · 从证据到下一次实验')
    selected=scoped_selectbox('这次围绕哪条作品创作',list(lookup),format_func=lambda i:dated_label(lookup[i]),key='assistant_workflow_target')
    target=lookup[selected];track=confirmed_track(target)
    with st.expander('调整参照范围（可选）') if guided else st.container():
        personal_range=st.radio('个人历史参照范围',['全部历史有效作品','同赛道（按已确认分类）'],horizontal=True,key='assistant_workflow_personal_scope')
        personal_scope='all' if personal_range=='全部历史有效作品' else 'track'
        st.caption('默认使用当前账号、当前平台的全部历史有效作品，不按年龄、赛道或体裁自动分组；每项指标只统计有真实有效值的作品。')
        if personal_scope=='track':
            with st.expander('自选作品并标注分类'):
                from creatorlab.classification_ui import editor
                editor(db,labelled,'assistant_workflow_classify')
        scope=None;samples=[];manual_peer=None
        if platform=='bilibili':
            saved_scopes=[d for d in documents(db,'scope',aid,platform)
                          if (d['data']['major'],d['data']['minor'])==track]
            options={d['key']:d['data']['name'] for d in saved_scopes}
            scope_key='assistant_workflow_reference'
            if st.session_state.get(scope_key) not in (None,*options):st.session_state[scope_key]=None
            chosen=st.selectbox('外部赛道参照（可选）',[None]+list(options),
                format_func=lambda k:'暂不使用外部参照' if k is None else options[k],key=scope_key)
            if chosen:scope,samples=selected_scope(db,aid,chosen)
            if not options:st.caption('先确认当前作品赛道，再到「看作品 → 每周必看」保存已核对的同赛道参照。')
        else:
            st.caption('可引用「看作品 → 外部参照」中同平台、同赛道的人工核验参照。')
        if track[0]:
            from creatorlab.peers import peer_rows,comparable
            from creatorlab.content_analysis import frame
            from urllib.parse import urlparse
            frame_target=frame([target]);age=frame_target.iloc[0]['age_band'] if not frame_target.empty else '未知'
            hosts={'bilibili':{'www.bilibili.com','space.bilibili.com','bilibili.com'},'douyin':{'www.douyin.com','douyin.com'}}
            peers=[p for p in peer_rows(db,platform,*track) if comparable(p,age,window=target.get('analysis_window') or '当前累计',min_n=1)
                   and urlparse(p['data'].get('source_url','')).hostname in hosts[platform]]
            peer_options={p['id']:p for p in peers};peer_key='assistant_workflow_manual_peer'
            if st.session_state.get(peer_key) not in (None,*peer_options):st.session_state[peer_key]=None
            picked_peer=st.selectbox('人工核验的同行参照（可选）',[None]+list(peer_options),
                format_func=lambda i:'暂不引用人工参照' if i is None else peer_options[i]['name'],key=peer_key)
            if picked_peer is not None:manual_peer=peer_options[picked_peer]
    lessons=lessons_for(db,aid,platform,target,metric)
    linked=[r for r in latest_posts(db) if target.get('project_id') and r.get('project_id')==target['project_id'] and r['platform']!=platform]
    try:brief=build_brief(labelled,target,metric,scope,samples,lessons,linked,manual_peer,personal_scope)
    except ValueError as exc:st.warning(str(exc));return
    proposal = st.session_state.get('assistant_workflow_handoff') if guided else None
    if proposal and proposal['post_id'] != selected:
        proposal = None
    if proposal:
        brief['cards'] = [dict(card, change=proposal['change'],
                              hypothesis='保持其他做法尽量相近，观察这项改动后的'+NAMES.get(metric,metric),
                              evidence_ids=[f'P:{selected}']) if card['kind']==proposal['kind'] else card
                          for card in brief['cards']]
    context_hash=hashlib.sha256(json.dumps({k:brief[k] for k in ('evidence','lessons','observations','metric','track','cards')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    draft_key='assistant_workflow_draft'
    old=st.session_state.get(draft_key)
    if old and old['context']!=context_hash:st.session_state.pop(draft_key,None)
    generated=model_controls(brief,context_hash)
    if generated:st.session_state[draft_key]={'context':context_hash,'brief':generated}
    shown=st.session_state.get(draft_key,{}).get('brief',brief)
    obs=shown['observations']
    if not guided:
        st.caption(shown['origin'])
        a,b,c=st.columns(3)
        a.metric('同范围历史有效作品',str(obs['personal_n']))
        b.metric('当前'+NAMES.get(metric,metric),display(obs['target_value'],metric))
        c.metric('历史中位数',display(obs['personal_median'],metric))
    with st.expander('观察事实、来源与样本限制',expanded=False):
        st.caption(f"外部参照{obs['external_n']}条；已关联的另一平台版本{obs['linked_versions']}条。各平台分别展示，不混合评分。")
        if obs.get('manual_peer_sample_n'):st.caption(f"人工参照覆盖作品数：{obs['manual_peer_sample_n']}（由用户核对录入）")
        for item in shown['evidence']:
            st.text(item['id']+' · '+item['title'])
            st.caption(item['type']+' · 观测于 '+str(item['observed_at'] or '未知'))
            if str(item['url']).startswith('https://'):st.link_button('查看来源 '+item['id'],item['url'])
            st.json(item['values'])
        for line in shown['limits']:st.caption(line)
    focus=st.selectbox('这次先改哪一处',list(KINDS),key='assistant_workflow_focus',persist_state='session') if guided else None
    edited_change = None
    for card in shown['cards']:
        if guided and card['kind']!=focus:continue
        with st.container(border=True):
            st.markdown('#### '+card['kind'])
            if proposal and focus==proposal['kind']:
                st.caption('从战力图带入的改动，可按需要编辑。')
                change_key = hashlib.sha256(card['change'].encode()).hexdigest()[:12]
                edited_change = st.text_area('下一条具体改什么', value=card['change'], max_chars=500,
                                             key=f'assistant_workflow_change_{selected}_{change_key}',persist_state='session')
            else:
                st.text(card['change'])
            st.caption('待验证假设：'+card['hypothesis'])
            st.caption('依据：'+'、'.join(card['evidence_ids']))
            if card.get('prior_experiment_id'):st.caption('继续验证已复盘实验 #'+str(card['prior_experiment_id']))
    if shown['lessons']:
        with st.expander('本账号已有复盘经验'):
            for lesson in shown['lessons']:
                st.text(lesson['conclusion']);st.caption(lesson['limitation'])
                st.caption(f"实验窗口{lesson['window']} · 原做法{lesson['result']['n_baseline']}条、改动后{lesson['result']['n_variant']}条")
                st.caption('下一轮：'+lesson['next_action'])
    if st.button('保存并开始验证' if guided else '保存这份创作方案与证据',key='assistant_workflow_save',type='primary' if guided else 'secondary'):
        try:
            if edited_change is not None:
                if not edited_change.strip():
                    raise ValueError('请填写这次要验证的改动')
                shown = dict(shown, cards=[dict(c, change=edited_change.strip()) if c['kind']==focus else c
                                          for c in shown['cards']])
            active_digest=hashlib.sha256((context_hash+json.dumps(shown['cards'],ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
            active=st.session_state.get('assistant_workflow_active_plan',{})
            plan=active.get('plan') if guided and active.get('digest')==active_digest and get(db,'plan',aid,platform,active.get('plan')) else save_plan(db,shown)
            st.session_state['assistant_workflow_active_plan']={'digest':active_digest,'plan':plan}
            st.session_state['assistant_workflow_saved']=plan
            if guided:
                eid=plan_experiment(db,aid,platform,plan,focus)
                from creatorlab.feedback import notify
                notify('方案已保存。发布后选择实施改动的新作品，按相同窗口复盘。')
                from creatorlab.workspace import route,CREATE
                route(CREATE,create_step='记录与复盘',review_task=eid,review_account=aid)
            st.success('方案与证据已保存，刷新后仍可在下方查看和转为实验。')
        except ValueError as exc:st.error(str(exc))
    with st.expander('历史方案、导出与备份') if guided else st.container():
        from creatorlab.workflow_backup import backup_panel
        backup_panel(db,aid,platform,'assistant_workflow_backup_'+str(aid))
        plans=documents(db,'plan',aid,platform)
        if not plans:return
        st.markdown('#### 已保存方案与实验')
        choices={d['key']:d for d in plans};pick_key='assistant_workflow_saved_pick'
        if st.session_state.get(pick_key) not in (None,*choices):st.session_state.pop(pick_key,None)
        picked=st.selectbox('历史创作方案（最近200份）',list(choices),
            format_func=lambda k:choices[k]['updated_at'][:16]+' · '+choices[k]['data']['title'],key=pick_key)
        plan=choices[picked]['data']
        kind=st.selectbox('这次只检验一种改动',list(KINDS),key='assistant_workflow_experiment_kind')
        if st.button('转为一次创作实验',key='assistant_workflow_to_experiment'):
            try:
                eid=plan_experiment(db,aid,platform,picked,kind)
                st.success(f'实验 #{eid} 已准备好；在「做下一条 → 记录与复盘」关联原做法和新作品，按相同窗口复盘。重复点击不会重复创建。')
            except ValueError as exc:st.error(str(exc))
        st.download_button('导出方案、证据与经验',json.dumps(plan,ensure_ascii=False,indent=2).encode('utf-8'),
                           'CreatorLab-创作方案.json','application/json',key='assistant_workflow_export')
