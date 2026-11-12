import hashlib
import io
import json
import subprocess
import zipfile
from types import SimpleNamespace
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.video_inspection import ffmpeg_binary,inspect_video,extract_frames,parse_findings,metadata
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.workflow_store import documents


@pytest.fixture(scope='module')
def clip(tmp_path_factory):
    folder=tmp_path_factory.mktemp('video-signals');path=folder/'signals.mp4'
    args=[ffmpeg_binary(),'-y','-v','error','-f','lavfi','-i','color=black:s=160x90:r=24:d=1',
          '-f','lavfi','-i','testsrc2=s=160x90:r=24:d=3','-f','lavfi','-i','color=red:s=160x90:r=24:d=4',
          '-f','lavfi','-i','sine=frequency=440:duration=7','-filter_complex',
          '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];[3:a]adelay=1000[a]',
          '-map','[v]','-map','[a]','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)]
    subprocess.run(args,check=True,capture_output=True,timeout=30)
    return path.read_bytes()


def test_real_local_signal_detection_and_selected_frame_extraction(clip):
    report=inspect_video(clip)
    assert report['duration']==8 and report['has_audio']
    assert report['sha256']==hashlib.sha256(clip).hexdigest()
    events={e['kind']:e for e in report['findings']}
    assert events['black']['start']==0 and events['black']['end']==pytest.approx(1,abs=.15)
    assert events['silence']['end']==pytest.approx(1,abs=.15)
    assert events['freeze']['start']==pytest.approx(4,abs=.15) and events['freeze']['end']==8
    assert report['scene_changes']==pytest.approx([1,4],abs=.15)
    assert len(report['highlights'])<=3
    images=extract_frames(clip,'.mp4',report['highlights'])
    assert 1<=len(images)<=4 and all(b.startswith(b'\xff\xd8') for _,b in images)


def test_no_audio_is_not_invented_silence_and_invalid_files_fail(tmp_path):
    dst=tmp_path/'silent-track-absent.mp4'
    subprocess.run([ffmpeg_binary(),'-y','-v','error','-f','lavfi','-i','testsrc2=s=160x90:r=24:d=2',
        '-an','-c:v','libx264','-pix_fmt','yuv420p',str(dst)],check=True,capture_output=True,timeout=30)
    report=inspect_video(dst.read_bytes())
    assert not report['has_audio'] and '没有音轨' in report['audio_status']
    assert not any(e['kind']=='silence' for e in report['findings'])
    with pytest.raises(ValueError):inspect_video(b'not a video')
    with pytest.raises(ValueError):metadata('Duration: 01:00:00.00\nVideo: h264, 100x100')
    with pytest.raises(ValueError):inspect_video(b'#EXTM3U\nhttp://example.com/test','.m3u8')


def test_open_intervals_clamped_and_long_shot_is_only_a_review_candidate():
    events,highlights,cuts=parse_findings('freeze_start: 2\npts_time:1\npts_time:50','silence_start: 6',10)
    assert next(e for e in events if e['kind']=='freeze')['end']==10
    assert next(e for e in events if e['kind']=='silence')['end']==10
    assert cuts==[1] and any(e['kind']=='long_shot' for e in events)
    assert all(e['end']<=10 for e in events)
    assert all('回看' in e['action'] for e in highlights)


def test_local_ui_requires_binding_and_ai_opt_in_then_resets_consent(tmp_path,clip,monkeypatch):
    import streamlit as st
    import creatorlab.materials as materials
    monkeypatch.setattr(st,'file_uploader',lambda *args,**kwargs:SimpleNamespace(name='test.mp4',getvalue=lambda:clip))
    monkeypatch.setattr(materials,'_post',lambda *args,**kwargs:pytest.fail('local flow must not call any model'))
    db=tmp_path/'personal.db';init_hub(db);aid=add_account(db,'bilibili','123')
    pid=upsert_post(db,aid,'合成验收作品','fixture',metrics={'views':1000,'likes':10})
    code='from creatorlab.hub import latest_posts\nfrom creatorlab.video_inspection_ui import local_panel\nlocal_panel('+repr(str(db))+',latest_posts('+repr(str(db))+')[0])'
    app=AppTest.from_string(code,default_timeout=30).run()
    key=f'video_check_bilibili_{aid}_{pid}_'+hashlib.sha256(clip).hexdigest()[:16]
    assert not app.exception and app.button(key=key+'_run').disabled
    app.checkbox(key=key+'_bound').check().run();app.button(key=key+'_run').click().run()
    assert not app.exception,[e.message for e in app.exception]
    assert app.radio(key=key+'_next').value=='先自己回看，不使用AI'
    app.button(key=key+'_watch_1').click().run()
    assert app.get('video') and app.get('video')[0].proto.start_time==3
    app.button(key=key+'_save').click().run()
    assert len(documents(db,'inspection',aid,'bilibili'))==1
    from creatorlab.workflow_backup import export_account,inspect_backup,import_account
    backup=export_account(db,aid,'bilibili')
    assert inspect_backup(db,aid,'bilibili',backup)['records'][0]['kind']=='inspection'
    assert import_account(db,aid,'bilibili',backup)=={'added':0,'skipped':1}
    app.radio(key=key+'_mark_0').set_value('有意安排，忽略').run()
    app.radio(key=key+'_next').set_value('在这里选择模型分析').run()
    app.button(key=key+'_prepare').click().run()
    assert not app.exception
    assert app.button(key=key+'_send').disabled
    app.checkbox(key=key+'_consent').check().run()
    assert not app.button(key=key+'_send').disabled
    app.text_area(key=key+'_transcript').set_value('补充真实台词').run()
    assert not app.checkbox(key=key+'_consent').value and app.button(key=key+'_send').disabled


def test_external_bundle_contains_only_previewed_materials(clip):
    from creatorlab.video_inspection_ui import analysis_bundle
    report=inspect_video(clip);selected=report['highlights'][1:]
    images=extract_frames(clip,'.mp4',selected)
    raw=analysis_bundle(report,selected,images,'用户填写的台词',{'title':'验收'})
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert not any(name.endswith('.mp4') for name in z.namelist())
        data=json.loads(z.read('本地检测与作品数据.json'))
        assert data['selected_findings']==selected and len(data['frames'])==len(images)
        assert 'api_key' not in json.dumps(data).lower()


@pytest.mark.parametrize('provider',['deepseek','doubao'])
def test_selected_visual_providers_receive_only_frame_and_explicit_context(monkeypatch,provider):
    from creatorlab import materials
    requests=[]
    def fake(url,payload,*args,**kwargs):
        requests.append((url,payload));return {'choices':[{'message':{'content':json.dumps(dict(observed=['画面为静态'],hypotheses=['可能值得缩短'],next_test='只缩短静止片段',limits=['只看了所选关键帧']))}}]}
    monkeypatch.setattr(materials,'_post',fake)
    result=materials.analyze(provider,'vision-model','test-key','作品','',[('关键帧4秒',b'frame')],inspection={'findings':[{'start':4,'end':8}]})
    assert result['scope']==['关键帧4秒']
    payload=requests[0][1]
    assert len(payload['messages'][1]['content'])==2
    assert 'test-key' not in json.dumps(payload) and 'test-key' not in json.dumps(result)
