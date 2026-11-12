"""Local findings first; user-controlled, previewed AI escalation second."""
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
import streamlit as st
from creatorlab.video_inspection import inspect_video,extract_frames,time_label
from creatorlab.workflow_store import put,documents


def report_panel(report,raw=None,key='video_check'):
    st.markdown('#### 先回看这几处')
    st.caption('本次仅在本机检测，没有调用AI，也没有上传到云端。以下是回看候选，不是内容好坏或流失原因的结论。')
    if not report['highlights']:
        st.info('这些规则没有检出明显候选片段。它不能判断剧情、笑点或表达是否吸引人。')
    selected=[]
    for i,event in enumerate(report['highlights']):
        with st.container(border=True):
            st.markdown('##### '+time_label(event['start'])+' — '+time_label(event['end'])+' · '+event['title'])
            st.write(event['observation']);st.markdown('**回看时检查：**'+event['action'])
            if raw is not None and st.button('回看这段',key=f'{key}_watch_{i}'):
                st.session_state[key+'_play']=event['id']
            label=st.radio('这段是有意安排的吗？',['待回看','有意安排，忽略','值得继续检查'],horizontal=True,key=f'{key}_mark_{i}')
            if label!='有意安排，忽略':selected.append(event)
    if raw is not None and report['highlights']:
        chosen=next((e for e in report['highlights'] if e['id']==st.session_state.get(key+'_play')),None)
        if chosen:
            st.video(raw,start_time=max(0,chosen['start']-.5),end_time=min(report['duration'],chosen['end']+.5),
                     alt='回看本地检测候选片段，使用播放器播放；定位精度约一秒')
            st.caption('播放器定位精度约一秒；准确检测区间以上方时间标签为准。')
    with st.expander('检测范围、规则与全部记录'):
        st.write(f"时长{report['duration']:.1f}秒 · {report['width']}×{report['height']} · {report['audio_status']}")
        for line in report['limits']:st.caption(line)
        st.json({'rules':report['rules'],'findings':report['findings'],'scene_changes':report['scene_changes']})
    return selected


def analysis_bundle(report,selected,images,transcript,context):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        summary={k:report[k] for k in ('format','sha256','duration','width','height','audio_status','rules','limits')}
        z.writestr('本地检测与作品数据.json',json.dumps({'report':summary,'selected_findings':selected,
            'transcript':transcript,'work':context,'frames':[label for label,_ in images]},ensure_ascii=False,indent=2))
        for i,(_,data) in enumerate(images):z.writestr(f'关键帧-{i+1}.jpg',data)
        z.writestr('给AI的说明.txt','只根据包内素材复盘。检测项是可疑片段，不是确定问题。逐项列明观察事实、待验证假设、具体改法和素材限制。不能声称看完原视频，不能把相关差异写成因果；没有逐秒留存，不能编造流失时刻。只推荐一个优先改动。')
    return output.getvalue()


def ai_panel(db,row,report,raw,suffix,selected,key):
    st.markdown('#### 要不要再让AI帮你细看？')
    choice=st.radio('下一步由你选择',['先自己回看，不使用AI','在这里选择模型分析','导出给自己的AI或agent'],key=key+'_next')
    if choice=='先自己回看，不使用AI':return
    if not selected:
        st.info('目前没有待检查片段。可把需要细看的候选改为“待回看”或“值得继续检查”；也可使用下方手动素材复盘。');return
    if st.button('准备所选片段的关键帧',key=key+'_prepare'):
        try:
            with st.spinner('只在本地提取关键帧…'):
                frames=extract_frames(raw,suffix,selected)
            st.session_state[key+'_prepared']={'ids':[e['id'] for e in selected],'frames':frames}
        except (ValueError,OSError) as exc:st.error(str(exc))
    prepared=st.session_state.get(key+'_prepared',{})
    if prepared.get('ids')!=[e['id'] for e in selected]:
        st.caption('准备关键帧后，先核对实际画面，再决定是否发送。');return
    images=prepared['frames']
    if not images:st.warning('没有取得可用关键帧，未发起AI请求。');return
    for label,data in images:st.image(data,caption=label,alt=label,width=300)
    transcript=st.text_area('可选：补充这些片段的真实台词或字幕',key=key+'_transcript')
    from creatorlab.reporting import metric_value
    context={'title':row['title'],'platform':row['platform'],
             'metrics':{k:metric_value(row,k) for k in ('views','likes','comments','favorites','shares','completion_rate')}}
    evidence={'findings':selected,'work':context,'limits':report['limits']}
    st.caption('范围仅限上方关键帧、所选检测记录、以下作品指标和你填写的文字；不发送整段视频或登录信息。')
    st.json(evidence)
    if choice=='导出给自己的AI或agent':
        st.download_button('下载分析材料包',analysis_bundle(report,selected,images,transcript,context),
            'CreatorLab-视频复盘材料.zip','application/zip',key=key+'_bundle')
        st.caption('下载不会调用模型。你可以自行把材料交给所选AI或agent。');return
    providers={'DeepSeek':'deepseek','豆包（火山方舟）':'doubao','本地Ollama视觉模型':'ollama','OpenAI视觉模型':'openai'}
    label=st.selectbox('选择你要使用的模型服务',list(providers),key=key+'_provider');provider=providers[label]
    from creatorlab.ai import TEXT_PROVIDERS,AIError
    config=TEXT_PROVIDERS.get(provider,{})
    default={'deepseek':'deepseek-flash','doubao':'doubao-seed-2-1-pro-260915','ollama':'llava','openai':'gpt-4.1-mini'}[provider]
    model=st.text_input('支持图片的模型名称或接入点ID',value=default,key=key+'_model_'+provider)
    token=st.text_input('API Key（仅当前会话，留空读取本机配置）',type='password',key=key+'_token_'+provider) if provider!='ollama' else None
    digest=hashlib.sha256(json.dumps([evidence,transcript,provider,model,[hashlib.sha256(b).hexdigest() for _,b in images]],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    consent_key=key+'_consent'
    if st.session_state.get(key+'_consent_digest')!=digest:
        st.session_state[consent_key]=False;st.session_state[key+'_consent_digest']=digest
    agreed=st.checkbox('同意把上方素材和文字发送给所选模型（云端服务可能收费）',key=consent_key)
    if st.button('让所选AI分析这些片段',disabled=not agreed,key=key+'_send'):
        try:
            from creatorlab.materials import analyze,save_review
            env=config.get('key','OPENAI_API_KEY')
            secret=(token or os.getenv(env)) if provider!='ollama' else None
            if not secret and provider!='ollama':
                try:secret=st.secrets.get(env)
                except (FileNotFoundError,KeyError):pass
            with st.spinner('根据已确认素材分析…'):
                result=analyze(provider,model,secret,row['title'],transcript,images,inspection=evidence)
            save_review(db,row['id'],result)
            st.session_state[key+'_ai_result']={'digest':digest,'result':result}
        except (AIError,ValueError,OSError,KeyError,TypeError) as exc:st.error(str(exc))
    saved=st.session_state.get(key+'_ai_result',{})
    if saved.get('digest')==digest:
        analysis=saved['result']['analysis']
        st.markdown('**AI看到了什么**');st.write(analysis['observed'])
        st.markdown('**还需要验证的解释**');st.write(analysis['hypotheses'])
        st.markdown('**下一条优先试这一处**');st.write(analysis['next_test'])
        st.caption('实际素材范围：'+'、'.join(saved['result']['scope']))
        for line in analysis['limits']:st.caption(line)
        if st.button('把这个改动记为创作实验',key=key+'_experiment'):
            from creatorlab.growth import experiments,save_experiment
            title='视频复盘 · '+report['sha256'][:12]+' · '+str(row['id'])
            existing=next((e for e in experiments(db,row['account_id']) if e['title']==title),None)
            eid=existing['id'] if existing else save_experiment(db,row['account_id'],title,analysis['next_test'],'views')
            st.success(f'已准备实验 #{eid}，到创作实验中关联作品并按相同窗口复盘。')


def local_panel(db,row):
    st.markdown('#### 第一步：本地视频体检')
    st.write('先找出几处值得回看的位置，再由你决定是否需要AI。')
    if row.get('media_format')=='image':
        st.info('这条作品已确认为图文，不套用视频检测；仍可使用下方手动素材复盘。');return
    owner=f"video_check_{row['platform']}_{row['account_id']}_{row['id']}"
    video=st.file_uploader('选择这条作品的原视频（MP4／MOV／WebM，≤200MB、≤10分钟）',type=['mp4','mov','webm'],key=owner+'_file',max_upload_size=200)
    if video:
        raw=video.getvalue();digest=hashlib.sha256(raw).hexdigest();key=owner+'_'+digest[:16]
        confirmed=st.checkbox('我已核对：这个视频对应上方所选作品',key=key+'_bound')
        if st.button('开始本地检测，不使用AI',disabled=not confirmed,key=key+'_run'):
            try:
                with st.spinner('正在本机检测画面和声音，请稍候…'):
                    report=inspect_video(raw,Path(video.name).suffix)
                st.session_state[key+'_report']=report
            except (ValueError,OSError) as exc:st.error(str(exc))
        report=st.session_state.get(key+'_report')
        if report and not confirmed:
            st.session_state[key+'_consent']=False
            st.session_state.pop(key+'_prepared',None)
            st.info('请先重新确认视频与作品的对应关系，再查看、保存或发送这次结果。');return
        if report:
            selected=report_panel(report,raw,key)
            if st.button('保存这次本地体检记录',key=key+'_save'):
                try:
                    put(db,'inspection',row['account_id'],row['platform'],str(row['id'])+':'+digest[:16],{'post_id':row['id'],'report':report})
                    st.success('仅保存检测记录；未保存原视频或上传到云端。')
                except (ValueError,OSError) as exc:st.error(str(exc))
            st.download_button('导出本地体检记录',json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8'),
                               'CreatorLab-本地视频体检.json','application/json',key=key+'_json')
            ai_panel(db,row,report,raw,Path(video.name).suffix,selected,key)
    else:st.caption('仅靠标题和平台统计不能检测视频片段，请提供本地原视频。')
    history=[d for d in documents(db,'inspection',row['account_id'],row['platform']) if d['data']['post_id']==row['id']]
    if history:
        with st.expander('已保存的本地体检记录'):
            for d in history[:10]:
                st.caption(d['updated_at']+' · 视频指纹 '+d['data']['report']['sha256'][:12]);st.json(d['data']['report'])
