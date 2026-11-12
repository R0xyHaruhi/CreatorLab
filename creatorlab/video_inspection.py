"""Offline signal checks. Findings are review candidates, never content verdicts."""
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_BYTES=200_000_000
MAX_SECONDS=600
RULES={'black_seconds':.5,'freeze_seconds':2.,'silence_seconds':.7,'silence_db':-40,'analysis_fps':8}
DESCRIPTIONS={
 'black':('画面接近黑色','回看是否为有意转场；若不是，可检查黑场或素材缺失。'),
 'freeze':('画面长时间变化很小','回看是否为刻意停顿；若无必要，可尝试缩短这一段。'),
 'silence':('声音接近静音','回看是否需要留白；若并非有意，可检查音轨或缩短空白。'),
 'long_shot':('较长时间没有明显切换','长镜头不一定有问题；回看这段是否仍有足够的信息变化。'),
}


def ffmpeg_binary():
    found=shutil.which('ffmpeg')
    if found:return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError):
        raise ValueError('本地视频检测组件未安装，请运行 repair_windows.bat 更新项目依赖。') from None


def validate(raw,suffix):
    if not raw or len(raw)>MAX_BYTES:raise ValueError('请选择不超过200MB的本地视频')
    suffix=suffix.lower()
    if suffix not in ('.mp4','.mov','.webm'):raise ValueError('支持MP4、MOV或WebM视频')
    return suffix


def _input(binary,src,suffix):
    # Force a local media container; disguised playlists cannot fetch remote URLs.
    return [binary,'-nostdin','-hide_banner','-threads','2','-filter_threads','1',
            '-protocol_whitelist','file,pipe','-f','matroska' if suffix=='.webm' else 'mov','-i',str(src)]


def _run(args,timeout=90):
    try:
        p=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=timeout)
    except subprocess.TimeoutExpired:raise ValueError('本次检测超过时间限制，请提供较短的视频；未生成完整结果。') from None
    log=p.stderr.decode('utf-8',errors='replace')
    if p.returncode:raise ValueError('视频未能完整解码，请检查文件或转为常规MP4后重试。')
    return log


def metadata(log):
    match=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',log)
    if not match:raise ValueError('无法确认视频时长，请提供完整的本地视频文件')
    h,m,s=map(float,match.groups());duration=h*3600+m*60+s
    if not math.isfinite(duration) or duration<=0 or duration>MAX_SECONDS:
        raise ValueError('第一版支持时长不超过10分钟的视频，不截断后冒充完整检测')
    line=next((line for line in log.splitlines() if 'Video:' in line),'')
    dims=re.search(r'\b(\d{2,5})x(\d{2,5})\b',line)
    if not dims:raise ValueError('文件中未识别到可检测的视频画面')
    return dict(duration=duration,width=int(dims[1]),height=int(dims[2]),has_audio='Audio:' in log)


def parse_findings(video_log,audio_log,duration):
    events=[]
    def add(kind,start,end):
        start=max(0.,float(start));end=min(duration,float(end))
        if end-start>=.1:events.append(dict(kind=kind,start=round(start,3),end=round(end,3)))
    for start,end in re.findall(r'black_start:([\d.]+)\s+black_end:([\d.]+)',video_log):add('black',start,end)
    # Some FFmpeg builds report a final open black interval only as a start.
    for kind,log,start_token,end_token in (
        ('freeze',video_log,'freeze_start','freeze_end'),
        ('silence',audio_log,'silence_start','silence_end')):
        opened=None
        for token,value in re.findall(r'('+start_token+'|'+end_token+r'):\s*([\d.]+)',log):
            if token==start_token:opened=float(value)
            elif opened is not None:add(kind,opened,value);opened=None
        if opened is not None:add(kind,opened,duration)
    cuts=sorted({float(t) for t in re.findall(r'pts_time:([\d.]+)',video_log) if 0<float(t)<duration})
    boundaries=[0.]+cuts+[duration]
    threshold=max(8.,duration*.2)
    for a,b in zip(boundaries,boundaries[1:]):
        if b-a>=threshold:add('long_shot',a,b)
    # Merge duplicate/adjacent observations of the same signal.
    merged=[]
    for e in sorted(events,key=lambda e:(e['kind'],e['start'])):
        if merged and merged[-1]['kind']==e['kind'] and e['start']<=merged[-1]['end']+.25:
            merged[-1]['end']=max(merged[-1]['end'],e['end'])
        else:merged.append(e.copy())
    for e in merged:
        title,action=DESCRIPTIONS[e['kind']]
        e.update(id=f"{e['kind']}:{e['start']:.3f}:{e['end']:.3f}",title=title,action=action,
                 observation=f"按本地规则检测到约{e['end']-e['start']:.1f}秒的「{title}」。",
                 priority=(3 if e['kind']=='black' else 1 if e['kind']=='long_shot' else 2)+(2 if e['start']<3 else 0))
    # Avoid spending all three recommendations on overlapping flags.
    chosen=[]
    for e in sorted(merged,key=lambda e:(-e['priority'],e['start'])):
        if not any(min(e['end'],c['end'])-max(e['start'],c['start'])>min(e['end']-e['start'],c['end']-c['start'])*.7 for c in chosen):chosen.append(e)
        if len(chosen)==3:break
    return sorted(merged,key=lambda e:e['start']),sorted(chosen,key=lambda e:e['start']),cuts


def inspect_video(raw,suffix='.mp4'):
    suffix=validate(raw,suffix);binary=ffmpeg_binary()
    with tempfile.TemporaryDirectory(prefix='clab_video_check_') as folder:
        src=Path(folder)/('input'+suffix);src.write_bytes(raw)
        args=_input(binary,src,suffix)
        meta=metadata(_run(args+['-map','0:v:0','-t','0','-f','null','-'],20))
        filters='scale=640:360:force_original_aspect_ratio=decrease,fps=8,blackdetect=d=0.5:pix_th=0.10:pic_th=0.98,freezedetect=n=-50dB:d=2,select=gt(scene\\,0.30),showinfo'
        video_log=_run(args+['-map','0:v:0','-an','-vf',filters,'-f','null','-'])
        audio_log=_run(args+['-map','0:a:0','-vn','-af','silencedetect=noise=-40dB:d=0.7','-f','null','-']) if meta['has_audio'] else ''
        events,highlights,cuts=parse_findings(video_log,audio_log,meta['duration'])
    return dict(format='creatorlab-video-check-1',sha256=hashlib.sha256(raw).hexdigest(),
        **meta,rules=dict(RULES),findings=events,highlights=highlights,scene_changes=cuts,
        audio_status='已检测' if meta['has_audio'] else '没有音轨，未进行静音检测',
        limits=['这只是按阈值筛出的回看候选，不表示片段一定有问题，也不解释播放或留存的原因。',
                '画面按8帧/秒缩小后检测，时间为近似定位；短于采样间隔的现象可能漏检。',
                '没有识别剧情、笑点、语义或画面内字幕；未提供逐秒留存曲线。'])


def extract_frames(raw,suffix,findings):
    suffix=validate(raw,suffix);binary=ffmpeg_binary();images=[]
    times=[]
    for e in findings:
        for t in (max(0,e['start']-.5),(e['start']+e['end'])/2):
            if not any(abs(t-old)<.2 for old in times):times.append(t)
    with tempfile.TemporaryDirectory(prefix='clab_video_frames_') as folder:
        src=Path(folder)/('input'+suffix);src.write_bytes(raw)
        for i,t in enumerate(times[:4]):
            dst=Path(folder)/f'{i}.jpg'
            _run(_input(binary,src,suffix)+['-ss',str(t),'-frames:v','1','-vf','scale=768:-2','-y',str(dst)],20)
            if dst.exists():images.append((f'回看候选关键帧 {t:.2f}秒',dst.read_bytes()))
    return images


def time_label(seconds):
    return f'{int(seconds)//60:02d}:{seconds%60:05.2f}'
