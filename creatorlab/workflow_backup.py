"""Portable account-bound workflow backup; imports only add missing documents."""
import hashlib
import json
import math
from creatorlab.hub import connect,utcnow
from creatorlab.workflow_store import KINDS,check_owner,_connection,store_path


def _identity(db,aid):
    with connect(db) as con:
        account=dict(con.execute('SELECT id,platform,handle FROM hub_accounts WHERE id=?',(aid,)).fetchone())
        posts={str(r['id']):[r['external_id'],r['title']] for r in con.execute('SELECT id,external_id,title FROM hub_posts WHERE account_id=?',(aid,))}
        has=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clab_experiments'").fetchone()
        experiments={str(r['id']):[r['title'],r['hypothesis'],r['metric'],r['created_at']] for r in con.execute('SELECT * FROM clab_experiments WHERE account_id=?',(aid,))} if has else {}
    return account,posts,experiments


def export_account(db,aid,platform):
    check_owner(db,aid,platform)
    account,posts,experiments=_identity(db,aid)
    records=[]
    if store_path(db).exists():
        with _connection(db) as con:
            records=[dict(kind=r['kind'],key=r['record_key'],data=json.loads(r['payload'])) for r in
                     con.execute('SELECT * FROM documents WHERE account_id=? AND platform=? ORDER BY kind,record_key',(aid,platform))]
    payload=dict(format='creatorlab-workflow-1',created_at=utcnow(),account=account,
                 posts=posts,experiments=experiments,records=records)
    body=json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False)
    return json.dumps(dict(payload=payload,sha256=hashlib.sha256(body.encode()).hexdigest()),ensure_ascii=False,indent=2).encode('utf-8')


def inspect_backup(db,aid,platform,raw):
    check_owner(db,aid,platform)
    if len(raw)>10_000_000:raise ValueError('工作流备份超过10MB')
    try:
        obj=json.loads(raw);p=obj['payload']
        body=json.dumps(p,ensure_ascii=False,sort_keys=True,allow_nan=False)
        if p['format']!='creatorlab-workflow-1' or hashlib.sha256(body.encode()).hexdigest()!=obj['sha256']:
            raise ValueError('工作流备份校验失败')
        if not isinstance(p['posts'],dict) or not isinstance(p['experiments'],dict):raise ValueError('作品与实验清单无效')
        account,posts,experiments=_identity(db,aid)
        if p['account']!=account:raise ValueError('请先恢复配套的作品数据库；备份账号ID、平台或账号标识不匹配')
        for key,value in p['posts'].items():
            if posts.get(key)!=value:raise ValueError('作品标识或标题不匹配，请使用配套的作品备份')
        for key,value in p['experiments'].items():
            if experiments.get(key)!=value:raise ValueError('实验标识不匹配，请使用配套的作品备份')
        if not isinstance(p['records'],list) or len(p['records'])>10000:raise ValueError('备份记录数量无效')
        from creatorlab.weekly_reference import load_dataset
        from creatorlab.genres import valid_genre
        allowed_bvids={r['bvid'] for r in load_dataset()[1]};seen=set()
        for record in p['records']:
            kind=record['kind'];key=record['key'];data=record['data']
            if kind not in KINDS or not isinstance(key,str) or not key or not isinstance(data,dict):raise ValueError('工作流记录格式无效')
            if len(key)>150 or len(json.dumps(data,ensure_ascii=False,allow_nan=False))>2_000_000:raise ValueError('单条工作流记录过大')
            if (kind,key) in seen:raise ValueError('备份存在重复记录')
            seen.add((kind,key))
            if kind=='inspection':
                from creatorlab.video_inspection import DESCRIPTIONS,MAX_SECONDS
                if str(data['post_id']) not in posts or not isinstance(data['report'],dict):raise ValueError('视频体检归属无效')
                report=data['report']
                if report['format']!='creatorlab-video-check-1' or not isinstance(report['sha256'],str) or len(report['sha256'])!=64 or any(c not in '0123456789abcdef' for c in report['sha256']):raise ValueError('视频体检指纹无效')
                if not isinstance(report['duration'],(int,float)) or not 0<report['duration']<=MAX_SECONDS:raise ValueError('视频体检时长无效')
                if not isinstance(report['rules'],dict) or not isinstance(report['audio_status'],str) or not isinstance(report['limits'],list):raise ValueError('视频体检规则无效')
                for field in ('findings','highlights'):
                    if not isinstance(report[field],list) or len(report[field])>10000:raise ValueError('视频体检片段无效')
                    for e in report[field]:
                        if e['kind'] not in DESCRIPTIONS or not 0<=float(e['start'])<float(e['end'])<=report['duration'] or not all(isinstance(e[f],str) for f in ('id','title','observation','action')):raise ValueError('视频体检片段无效')
                if not isinstance(report['width'],int) or not isinstance(report['height'],int) or not isinstance(report['scene_changes'],list):raise ValueError('视频体检元信息无效')
            if kind in ('reference','scope') and platform!='bilibili':raise ValueError('不能将B站精选参照导入抖音')
            if kind=='reference':
                fields={'title','observed_at','source_url','precision','tags','views','likes','comments','favorites','shares','coins','danmaku'}
                if key not in allowed_bvids or set(data)-fields or not isinstance(data['title'],str) or not isinstance(data['tags'],list) or not isinstance(data['observed_at'],str) or not isinstance(data['precision'],dict):raise ValueError('公开样本格式无效')
                if data['source_url']!='https://www.bilibili.com/video/'+key:raise ValueError('公开样本来源不匹配')
                for m in ('views','likes','comments','favorites','shares','coins','danmaku'):
                    value=data.get(m)
                    if value is not None and (isinstance(value,bool) or not isinstance(value,int) or value<0):raise ValueError('公开样本计数无效')
                if not all(isinstance(t,str) for t in data['tags']):raise ValueError('样本标签无效')
            if kind=='scope':
                if not isinstance(data['name'],str) or not data['name'].strip() or not isinstance(data['filters'],dict):raise ValueError('参照名称或筛选条件无效')
                if not valid_genre(platform,data['major'],data['minor']) or not isinstance(data['bvids'],list) or not data['bvids'] or not set(data['bvids'])<=allowed_bvids:raise ValueError('参照赛道或BV号无效')
            if kind=='plan':
                if data['account_id']!=aid or data['platform']!=platform or str(data['target_id']) not in posts:raise ValueError('方案归属不匹配')
                if not isinstance(data['cards'],list) or len(data['cards'])!=5 or not isinstance(data['evidence'],list):raise ValueError('方案内容不完整')
                from creatorlab.creative_brief import KINDS as CARD_KINDS
                if not isinstance(data['title'],str) or not isinstance(data['metric'],str) or data['experiment_window'] not in ('24小时','7天','30天'):raise ValueError('方案标题、目标或观察窗口无效')
                sources=set()
                for item in data['evidence']:
                    if not isinstance(item,dict) or not isinstance(item['id'],str) or not isinstance(item['title'],str) or not isinstance(item['values'],dict):raise ValueError('方案证据结构无效')
                    sources.add(item['id'])
                seen_kinds=set()
                for card in data['cards']:
                    if not isinstance(card,dict) or card['kind'] not in CARD_KINDS or card['kind'] in seen_kinds:raise ValueError('方案建议分类无效')
                    if not all(isinstance(card[f],str) and card[f].strip() for f in ('change','hypothesis')):raise ValueError('方案建议正文无效')
                    if not isinstance(card['evidence_ids'],list) or not card['evidence_ids'] or not set(card['evidence_ids'])<=sources:raise ValueError('方案引用不存在的证据')
                    seen_kinds.add(card['kind'])
                fingerprint=hashlib.sha256(json.dumps(data['evidence'],ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
                if fingerprint!=data['evidence_hash']:raise ValueError('方案证据校验失败')
            if kind in ('lesson','experiment_detail') and key not in experiments:raise ValueError('复盘记录找不到配套实验')
            if kind=='experiment_detail':
                if 'kind' in data and data['kind'] not in ('选题','标题','封面','内容结构','跨平台复用','发布时间'):raise ValueError('实验类型无效')
                if 'suggested_window' in data and data['suggested_window'] not in ('24小时','7天','30天'):raise ValueError('实验建议窗口无效')
                if any(f in data and not isinstance(data[f],str) for f in ('goal','change','conclusion','next_action','confounders','source_plan')):raise ValueError('实验复盘正文无效')
        return p
    except (KeyError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('工作流备份结构不完整或不兼容') from None


def import_account(db,aid,platform,raw):
    p=inspect_backup(db,aid,platform,raw);added=0;skipped=0
    with _connection(db,True) as con:
        for record in p['records']:
            data=dict(record['data'])
            if record['kind']=='lesson':data['inactive']=True  # re-review before automatic use
            changed=con.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?,?)',
                (record['kind'],aid,platform,record['key'],json.dumps(data,ensure_ascii=False,allow_nan=False),utcnow())).rowcount
            added+=changed;skipped+=not changed
    return dict(added=added,skipped=skipped)


def backup_panel(db,aid,platform,key):
    import streamlit as st
    with st.expander('创作工作流记录备份与恢复'):
        st.caption('新参照、方案与经验保存在同目录的 *.workflow.sqlite3，不在原作品DB备份ZIP内。请同时备份作品DB和这里的工作流记录。恢复仅补入缺少的记录，不覆盖已有记录；导入经验需重新复盘确认。')
        if st.button('准备当前账号的工作流备份',key=key+'_prepare'):
            st.session_state[key+'_bytes']=export_account(db,aid,platform)
        if key+'_bytes' in st.session_state:
            st.download_button('下载工作流备份',st.session_state[key+'_bytes'],'CreatorLab-工作流备份.json',
                               'application/json',key=key+'_download')
        upload=st.file_uploader('选择配套的工作流备份',type=['json'],key=key+'_upload')
        if upload:
            try:
                p=inspect_backup(db,aid,platform,upload.getvalue())
                st.caption(f"已核对配套账号与作品／实验标识，备份含{len(p['records'])}条工作流记录。")
                agreed=st.checkbox('确认只补入缺少的记录，保留已有记录',key=key+'_confirm')
                if st.button('恢复缺少的工作流记录',disabled=not agreed,key=key+'_restore'):
                    result=import_account(db,aid,platform,upload.getvalue())
                    st.success(f"已补入{result['added']}条，保留已有{result['skipped']}条。导入经验需在创作实验中重新确认。")
            except (ValueError,OSError) as exc:st.error(str(exc))
