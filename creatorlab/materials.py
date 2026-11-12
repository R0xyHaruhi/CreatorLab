"""Evidence-based AI: selected real cover/keyframes/transcript, with explicit viewing scope."""
import base64
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image
from creatorlab.hub import connect,utcnow
from creatorlab.ai import _post,SYSTEM,AIError


def image_bytes(raw):
    if len(raw)>12_000_000:raise ValueError('单张图片最多12MB')
    with Image.open(io.BytesIO(raw)) as im:
        if im.width*im.height>20_000_000:raise ValueError('图片尺寸过大')
        im.thumbnail((768,768));out=io.BytesIO();im.convert('RGB').save(out,format='JPEG',quality=82)
        return out.getvalue()


def video_frames(raw,suffix='.mp4'):
    from creatorlab.video_inspection import ffmpeg_binary,validate,_input
    suffix=validate(raw,suffix)
    binary=ffmpeg_binary()
    if len(raw)>50_000_000:raise ValueError('本地视频最多50MB；更大的视频请上传关键帧')
    result=[]
    with tempfile.TemporaryDirectory(prefix='clab_evidence_') as folder:
        src=Path(folder)/('clip'+suffix);src.write_bytes(raw)
        for second in (0,3,10):
            dst=Path(folder)/f'{second}.jpg'
            proc=subprocess.run(_input(binary,src,suffix)+['-ss',str(second),'-frames:v','1','-vf','scale=768:-2',str(dst)],capture_output=True,timeout=20)
            if proc.returncode==0 and dst.exists():result.append((f'用户本地视频 {second}秒关键帧',image_bytes(dst.read_bytes())))
    return result


def analyze(provider,model,key,title,transcript,images,taxonomy=None,inspection=None):
    if not images and not transcript.strip():raise ValueError('请先提供真实封面、关键帧或字幕，避免只按标题判断')
    scope=[label for label,_ in images]
    task=('只基于已提供的素材分析，不能声称看完视频或听过未提供的音轨；没有逐秒留存曲线，不能编造观众离开的时刻。返回JSON：'
      '{"observed":["素材中可见/文字明确的信息"],"hypotheses":["需要实验验证的猜想"],'
      '"next_test":"下一条只改变一处的具体实验","limits":["缺失素材导致的限制"]}。'
      '区分观察与推测，不捏造留存原因。\n标题：'+title+'\n素材范围：'+json.dumps(scope,ensure_ascii=False)+'\n用户提供的字幕/脚本：'+transcript[:12000])
    if taxonomy:task+='\n可选增加genre_suggestion={major,minor,reason}，只从以下赛道选择；含糊则省略：'+json.dumps(taxonomy,ensure_ascii=False)
    if inspection:task+='\n本地信号检测与实际作品指标（检测项不等于内容问题，不可据此推断流失原因）：'+json.dumps(inspection,ensure_ascii=False)
    from creatorlab.ai import TEXT_PROVIDERS
    if provider=='openai' or provider in TEXT_PROVIDERS:
        import os
        config=TEXT_PROVIDERS.get(provider,{})
        key=key or os.getenv(config.get('key','OPENAI_API_KEY'))
        if not key:raise AIError('请先配置API Key')
        content=[{'type':'text','text':task}]+[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(raw).decode()}} for _,raw in images[:4]]
        payload={'model':model or os.getenv(config.get('model_env','OPENAI_MODEL')) or config.get('model','gpt-4.1-mini'),
                 'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':content}]}
        if provider in TEXT_PROVIDERS:payload['thinking']={'type':'disabled'}
        data=_post(config.get('url','https://api.openai.com/v1/chat/completions'),payload,{'Authorization':'Bearer '+key},timeout=60)
        text=data['choices'][0]['message']['content']
    elif provider=='ollama':
        data=_post('http://127.0.0.1:11434/api/chat',{'model':model or 'llava','stream':False,'messages':[{'role':'user','content':task,'images':[base64.b64encode(raw).decode() for _,raw in images[:4]]}]},timeout=60)
        text=data['message']['content']
    else:raise AIError('请先启用支持图像的AI模型；本地文字模型不一定支持图片')
    result=json.loads(text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
    if not isinstance(result,dict) or not all(k in result for k in ('observed','hypotheses','next_test','limits')):raise ValueError('模型没有返回完整的观察/假设结构')
    if any(not isinstance(result[k],list) or len(result[k])>30 or any(not isinstance(v,str) or len(v)>2000 for v in result[k]) for k in ('observed','hypotheses','limits')):raise ValueError('模型返回的观察、假设或限制格式无效')
    if not isinstance(result['next_test'],str) or not result['next_test'].strip() or len(result['next_test'])>2000:raise ValueError('模型没有返回有效的下一步改动')
    import hashlib
    return dict(scope=scope,transcript_provided=bool(transcript.strip()),model=model,provider=provider,
       evidence_hashes=[hashlib.sha256(raw).hexdigest() for _,raw in images],analysis=result)


def save_review(db,pid,result):
    with connect(db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS clab_material_reviews(id INTEGER PRIMARY KEY,post_id INTEGER,created_at TEXT,result_json TEXT)')
        con.execute('INSERT INTO clab_material_reviews(post_id,created_at,result_json) VALUES(?,?,?)',(pid,utcnow(),json.dumps(result,ensure_ascii=False)))


def panel(db,rows,provider):
    import streamlit as st
    from creatorlab.covers import cached_cover
    st.markdown('### 视频体检与素材复盘')
    from creatorlab.feedback import scoped_selectbox
    pid=scoped_selectbox('复盘哪条作品',[r['id'] for r in rows],format_func=lambda i:next(r['title'][:70] for r in rows if r['id']==i),key='material_post')
    row=next(r for r in rows if r['id']==pid)
    from creatorlab.video_inspection_ui import local_panel
    local_panel(db,row)
    if not st.toggle('手动提供封面、关键帧或字幕（原素材复盘）',key='material_manual_mode'):return
    manual_choice=st.selectbox('手动素材复盘方式',['暂不使用AI','本地Ollama','OpenAI'],key='material_manual_provider')
    provider={'暂不使用AI':'none','本地Ollama':'ollama','OpenAI':'openai'}[manual_choice]
    model=st.text_input('手动复盘视觉模型',value='llava' if provider=='ollama' else 'gpt-4.1-mini',key='material_manual_model_'+provider) if provider!='none' else None
    token=st.text_input('手动复盘API Key（仅当前会话，留空读取环境变量）',type='password',key='material_manual_key') if provider=='openai' else None
    images=[]
    cover=cached_cover(db,row['platform'],row.get('external_id'))
    if cover:
        st.image(cover,width=150)
        if st.checkbox('把这张真实封面作为素材',value=True,key='material_use_cover'):images.append(('已缓存的作品封面',image_bytes(cover)))
    uploads=st.file_uploader('添加最多3张关键帧（可选）',type=['png','jpg','jpeg','webp'],accept_multiple_files=True,key='material_frames')
    try:
        for f in uploads[:3]:images.append(('用户上传关键帧：'+f.name,image_bytes(f.getvalue())))
    except (ValueError,OSError) as exc:st.error(str(exc))
    with st.expander('从本地视频抽取0、3、10秒关键帧（可选，需FFmpeg）'):
        video=st.file_uploader('本地视频，最大50MB',type=['mp4','mov','webm'],key='material_video')
        if video and st.button('只在本地抽帧'):
            try:st.session_state['frames_'+str(pid)]=video_frames(video.getvalue(),Path(video.name).suffix)
            except (ValueError,OSError,subprocess.TimeoutExpired) as exc:st.error(str(exc))
        images.extend(st.session_state.get('frames_'+str(pid),[])[:3])
    images=images[:4]
    transcript=st.text_area('字幕、脚本或开头实际台词（可选）',key='material_script',placeholder='填写真实内容；没有提供时，AI不能判断完整叙事和节奏。')
    import hashlib
    context_hash=hashlib.sha256(json.dumps([pid,provider,model,transcript,[(label,hashlib.sha256(data).hexdigest()) for label,data in images]],ensure_ascii=False).encode()).hexdigest()
    if st.session_state.get('material_consent_context')!=context_hash:
        st.session_state.material_consent=False;st.session_state.material_consent_context=context_hash
    consent=st.checkbox('同意仅将以上最多4张素材和文字发送给当前模型',key='material_consent')
    if st.button('分析这些素材，给一个可验证改动',disabled=provider=='none' or not consent):
        try:
            with st.spinner('根据实际提供的素材分析…'):
                from creatorlab.genres import TAXONOMY
                result=analyze(provider,model,token,row['title'],transcript,images,TAXONOMY[row['platform']])
                save_review(db,pid,result);st.session_state['material_result_'+str(pid)]=result
                st.session_state['material_result_context_'+str(pid)]=context_hash
        except (AIError,ValueError,KeyError,TypeError) as exc:st.error(str(exc))
    result=st.session_state.get('material_result_'+str(pid))
    if result and st.session_state.get('material_result_context_'+str(pid))==context_hash:
        st.caption('实际观看范围：'+'、'.join(result['scope'])+('；另有用户提供文字' if result['transcript_provided'] else '；没有完整字幕'))
        st.markdown('**AI素材观察（仍可能判断错误）**');st.write(result['analysis']['observed'])
        st.markdown('**待验证假设**');st.write(result['analysis']['hypotheses'])
        st.markdown('**下一条只试这一处**');st.write(result['analysis']['next_test'])
        st.caption('限制：'+str(result['analysis']['limits']))
        suggestion=result['analysis'].get('genre_suggestion')
        from creatorlab.genres import valid_genre,set_genre
        if isinstance(suggestion,dict) and valid_genre(row['platform'],suggestion.get('major'),suggestion.get('minor')):
            st.write('基于本次素材的赛道建议：'+suggestion['major']+' → '+suggestion['minor'])
            if st.button('我确认这个素材赛道'):
                set_genre(db,pid,suggestion['major'],suggestion['minor'],'manual',1.,'用户确认素材分析建议');st.success('已同步到统一分类。')
        if st.button('把这个改动存为创作实验'):
            from creatorlab.growth import save_experiment
            save_experiment(db,row['account_id'],'素材复盘：'+row['title'][:40],str(result['analysis']['next_test']),'views');st.success('已保存，到「创作实验」关联新作品。')
