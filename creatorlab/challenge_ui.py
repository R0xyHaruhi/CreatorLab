"""Challenge-first presentation; evidence and power tools stay one level deeper."""
from html import escape
import pandas as pd
import streamlit as st
from creatorlab.appearance import PALETTES,chart


def skin():
    p=PALETTES[st.session_state.get('clab_appearance','柔和深色')]
    st.html('''<style>
    .clab-intro{padding:0 0 16px;border-bottom:1px solid BORDER;margin-bottom:8px}
    .clab-kicker{font-size:13px;letter-spacing:0;color:MUTED;font-weight:500}
    .clab-intro h2{font-size:24px!important;line-height:1.4;letter-spacing:0;margin:8px 0}
    .clab-intro .clab-sub{color:MUTED;font-size:14px}
    .clab-result{padding:20px;border:1px solid BORDER;border-radius:12px;background:PANEL;margin:4px 0 16px}
    .clab-result .clab-number{font-size:44px;font-weight:500;letter-spacing:0;line-height:1.2;color:TEXT;margin:8px 0;font-variant-numeric:tabular-nums}
    .clab-number small{font-size:20px;margin-left:4px}
    .clab-result .clab-label{font-size:14px;color:MUTED;line-height:1.6}
    .clab-result .clab-name{font-size:20px;letter-spacing:0;font-weight:500;margin:8px 0}
    .clab-track{height:4px;border-radius:4px;background:BORDER;margin:16px 0;overflow:hidden}
    .clab-track i{display:block;height:100%;background:ACCENT}
    .clab-note{font-size:13px;color:MUTED;line-height:1.6}
    .clab-strip{display:flex;gap:20px;justify-content:space-between;flex-wrap:wrap;border-top:1px solid BORDER;padding:16px 0;margin-top:18px}
    .clab-strip span{font-size:12px;color:MUTED}.clab-strip b{font-size:19px;color:TEXT;margin-right:6px}
    .clab-readout{padding:4px 0 16px;color:TEXT;}
    .clab-verdict{font-size:32px;font-weight:700;line-height:1.35;margin:8px 0 12px;overflow-wrap:anywhere;}
    .clab-readout[data-tone="caution"] .clab-verdict{color:CONVERSION;}
    .clab-readout[data-tone="positive"] .clab-verdict{color:ACCENT;}
    .clab-support{font-size:17px;line-height:1.7;margin:0;color:TEXT;}
    .clab-facts{display:flex;flex-wrap:wrap;gap:16px 24px;margin:24px 0;}
    .clab-fact{display:flex;flex-direction:column;gap:4px;}
    .clab-fact span{font-size:14px;color:MUTED;}
    .clab-fact strong{font-size:24px;line-height:1.3;font-weight:650;font-variant-numeric:tabular-nums;}
    .clab-fact--focus strong{color:CONVERSION;}
    .clab-readout[data-tone="positive"] .clab-fact--focus strong{color:ACCENT;}
    .clab-next{border-top:1px solid BORDER;padding-top:16px;margin-top:16px;}
    .clab-next strong{display:block;font-size:20px;font-weight:650;line-height:1.6;margin-top:8px;color:TEXT;}
    .clab-hypothesis{font-size:14px;line-height:1.6;color:MUTED;margin-top:12px;}
    .st-key-battle-stage{border:1px solid BORDER;border-radius:16px;padding:24px;background:PANEL}
    .st-key-battle-stage [data-testid="stPlotlyChart"]{border-radius:12px;overflow:hidden}
    .st-key-battle-stage [data-testid="stAlert"]>div{background:transparent!important;color:TEXT!important;}
    .st-key-battle-stage [data-testid="stMarkdownContainer"] h3{font-size:20px!important;font-weight:500!important;line-height:1.6!important}
    .st-key-battle-filters [data-testid="stRadio"]{margin-bottom:0}
    @media(max-width:1000px){
      .st-key-battle-stage [data-testid="stHorizontalBlock"]{flex-direction:column;}
      .st-key-battle-stage [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{width:100%!important;flex:1 1 100%!important;min-width:0!important;}
    }
    @media(max-width:640px){.st-key-battle-stage{padding:16px}.clab-result{padding:16px}.clab-intro{padding-top:0}}
    </style>'''.replace('BORDER',p['border']).replace('ACCENT',p['accent']).replace('CONVERSION',p['conversion']).replace('PANEL',p['panel']).replace('MUTED',p['muted']).replace('TEXT',p['text']))


def intro():
    skin()
    st.html('<div class="clab-intro"><h2>作品战力</h2><div class="clab-sub">把播放规模与互动转化分开看，找到下一条作品的改进线索</div></div>')


def takeaway(model):
    """Plain-language reading of existing observations; never adds a causal claim."""
    d=model.get('diagnosis') or {}
    choices={
        'reach_like_gap':('播放不错，点赞还没跟上','这条播放较高，但每次播放带来的点赞偏少。','保留题材，只把开头的结果或亮点往前放。'),
        'low_conversion':('点赞转化偏低','这条每次播放带来的点赞，比你平时偏少。','只调整开头，让观众更早看到这条内容的看点。'),
        'at_or_above':('点赞表现跟得上','这条点赞比例达到或高于你平时的水平。','保留这次的题材或表达方式，再做一条相近作品验证。'),
        'small':('播放还少，先别下结论','目前看到的人还不多，点赞比例容易波动。','先积累更多播放，再决定要不要调整内容方向。'),
        'insufficient':('先积累，再判断强弱','可用的历史数据还少，暂时不能判断点赞表现好坏。','继续记录下一条作品，不急着凭一次结果改方向。'),
        'missing':('先补数据，再判断','播放或点赞数据还不完整，现在不宜下结论。','补齐这条作品的播放和点赞，再来复盘。'),
    }
    if d:
        title,body,action=choices.get(d.get('state'),choices['missing'])
        if d.get('state')=='at_or_above' and d.get('rate')==0:
            title,body='还没出现点赞反馈','目前点赞为0，暂时没有积极反馈可供复用。'
            action='再观察一条相近作品，先积累反馈。'
        if d.get('median_rate') is not None and d.get('n',0)<5:body+=' 目前样本较少，先当作线索。'
        return title,body,action
    high=model.get('high')
    if high and high['score']>=50:
        return '这条的亮点是'+high['axis'],'这个维度在你的历史作品里相对突出。',model['next_test']
    return '先从一处改动开始','这条还没有明显突出的维度，已有数据可以继续作为参照。',model['next_test']


def plan_from_takeaway(model, post_id):
    """Carry the displayed action and a measurable goal into the plan."""
    _, _, action = takeaway(model)
    diagnosis = (model.get('diagnosis') or {}).get('state')
    if diagnosis in ('reach_like_gap', 'low_conversion'):
        focus, metric = '内容结构', 'like_ratio'
    elif diagnosis == 'at_or_above':
        focus, metric = '选题', 'like_ratio'
    else:
        from creatorlab.battlecard import TESTS
        axis = (model.get('low') or {}).get('metric')
        focus, metric = '选题', 'views'
        if action == TESTS.get(axis):
            if axis == 'views':
                focus = '封面'
            elif axis == 'share_ratio':
                metric = axis
            else:
                focus = '内容结构'
                metric = {'avg_image_views': 'share_ratio', 'image_depth': 'favorite_ratio'}.get(axis, axis)
    return dict(post_id=post_id, kind=focus, metric=metric, change=action)


def result_panel(model,result):
    if model.get('comparison') in ('peer','weekly'):
        _result_evidence(model,result);return
    title,body,action=takeaway(model)
    d=model.get('diagnosis')
    state=(d or {}).get('state')
    tone='caution' if state in ('low_conversion','reach_like_gap') else 'positive' if state=='at_or_above' and (d.get('rate') or 0)>0 else 'neutral'
    facts=''
    if d:
        from creatorlab.hub import fmt_count
        from creatorlab.engagement import axis_value
        rate=axis_value(dict(metric='like_ratio',value=d['rate']))
        facts='<div class="clab-facts">'+''.join(
            f'<div class="clab-fact{focus}"><span>{label}</span><strong>{escape(value)}</strong></div>'
            for label,value,focus in [('播放',fmt_count(d['views']),''),('点赞',fmt_count(d['likes']),''),('点赞率',rate,' clab-fact--focus')])+'</div>'
    st.html(f'<div class="clab-readout" data-tone="{tone}"><div class="clab-kicker">这条怎么看</div><div class="clab-verdict">{escape(title)}</div><div class="clab-support">{escape(body)}</div>{facts}<div class="clab-next"><div class="clab-kicker">下一条 · 只试一处改动</div><strong>{escape(action)}</strong><div class="clab-hypothesis">这是待验证的尝试，数据尚不能确定原因。</div></div></div>')
    with st.expander('查看判断依据与历史位置'):
        _result_evidence(model,result,show_summary=False)


def _result_evidence(model,result,show_summary=True):
    diagnosis=model.get('diagnosis')
    if diagnosis:
        from creatorlab.hub import fmt_count
        from creatorlab.engagement import axis_value
        rate=axis_value(dict(metric='like_ratio',value=diagnosis['rate']))
        if show_summary:
            st.markdown(f"**播放 {fmt_count(diagnosis['views'])} · 点赞 {fmt_count(diagnosis['likes'])} · 点赞率 {rate}**")
            if diagnosis['state'] in ('reach_like_gap','low_conversion'):st.warning(diagnosis['message'])
            else:st.info(diagnosis['message'])
        else:st.caption(diagnosis['message'])
        if diagnosis['median_rate'] is not None:
            typical=axis_value(dict(metric='like_ratio',value=diagnosis['median_rate']))
            relative=f" · 当前为中位数的 {diagnosis['relative']:.0%}" if diagnosis['relative'] is not None else ''
            st.caption(f"同组点赞率中位数 {typical}{relative}；{diagnosis['n']}条其他作品，播放均≥{diagnosis['min_views']}。")
        with st.expander('如何理解点赞转化'):
            st.caption('点赞率=点赞÷播放，是行为转化指标，不是所有观众的喜爱比例。图中播放轴共用播放量。'+('图文第六轴为阅读深度，不是视频完播率。' if model.get('media_format')=='image' else '抖音完播轴共用完播率。'))
    title=escape(model['archetype'])
    if result.get('count_shape'):
        st.html(f'<div class="clab-result"><div class="clab-kicker">数量表现画像</div><div class="clab-name">{title}</div><div class="clab-label">B站使用实际数量；抖音留住观众为完播率。各轴独立，不合成综合质量分。</div></div>')
    elif result.get('ready'):
        pct=result['percent'];unit=escape(result['unit'])
        st.html(f'<div class="clab-result"><div class="clab-kicker">{escape(result.get("shape_label","本次综合表现"))}</div><div class="clab-number">{pct:.1f}<small>%</small></div><div class="clab-label">超过 {unit}</div><div class="clab-track"><i style="width:{pct:.2f}%"></i></div><div class="clab-name">{title}</div><div class="clab-note">{result["axes"]}个共同维度 · {result["n"]}个参照 · {result["tied"]}个并列<br>当前参照范围内的结果，非全站排名</div></div>')
    else:
        st.html(f'<div class="clab-result"><div class="clab-kicker">你的战力类型</div><div class="clab-name">{title}</div><div class="clab-label">各维度已有画像，综合比例等待更多共同有效记录。</div></div>')
    if model.get('high'):
        high=model['high'];label=high['axis']
        if diagnosis:
            label={'likes':'点赞数量','like_ratio':'点赞转化','comments':'评论数量','comment_ratio':'评论转化',
                   'favorites':'收藏数量','favorite_ratio':'收藏转化','shares':'分享数量','share_ratio':'分享转化',
                   'views':'播放规模','completion_rate':'完播率','avg_image_views':'平均浏览图片数','image_depth':'阅读深度指数'}.get(high['metric'],label)
        if high['metric']=='completion_rate' and model.get('comparison') not in ('peer','weekly'):
            st.caption(f"优势维度：{label} · 高于{round(high['score']*high['n']/100)}/{high['n']}条有效历史作品")
        else:st.caption('优势维度：'+label+' · 历史位置 '+str(round(high['score']))+'/100')


def share(row,model,key='hero',demo=False,primary=True):
    from creatorlab.battlecard import render_card
    action=st.container()
    with st.expander('卡片样式与隐私'):
        show_name=st.checkbox('展示昵称',value=False,key=key+'_show_name')
        preview=st.checkbox('预览海报',value=False,key=key+'_preview')
    data=render_card(row,model,light=st.session_state.get('clab_appearance')=='暖灰浅色',show_name=show_name)
    with action:
        st.download_button('保存战力卡',data,'CLab-我的创作战力.png','image/png',key=key+'_share',width='stretch',type='primary' if primary else 'secondary')
        st.caption('保存图片即可分享 · '+('示例卡片已标注演示' if demo else '默认隐藏账号昵称'))
    if preview:st.image(data,width='stretch')


def peer_panel(rows,db):
    from creatorlab.genres import TAXONOMY
    from creatorlab.hub import latest_posts,accounts
    from creatorlab.content_analysis import frame
    from creatorlab.challenge import peer_result
    from creatorlab.personal_ui import radar_figure
    platform=rows[0]['platform'];taxonomy=TAXONOMY[platform]
    confirmed=[r.get('genre') for r in rows if isinstance(r.get('genre'),dict) and r['genre']['origin'] in ('manual','platform_metadata')]
    default=max(confirmed,key=lambda x:sum(g['minor']==x['minor'] for g in confirmed)) if confirmed else None
    a,b,c=st.columns([1.15,1.15,1])
    major=a.selectbox('分区',list(taxonomy),index=list(taxonomy).index(default['major']) if default else 0,key='challenge_major')
    minors=taxonomy[major];minor=b.selectbox('赛道',minors,index=minors.index(default['minor']) if default and default['minor'] in minors else 0,key='challenge_minor')
    own=frame(rows)
    bands=['0–6天','7–29天','30–89天','90天以上']
    known_ages=own[own.age_band!='未知'].age_band if not own.empty else pd.Series(dtype=str)
    default_age=known_ages.mode().iloc[0] if len(known_ages) else bands[0]
    age=c.selectbox('发布至采集时长',bands,index=bands.index(default_age),key='challenge_age')
    media=st.radio('作品体裁',['video','image'],format_func=lambda x:'视频' if x=='video' else '图文',horizontal=True,key='challenge_format')
    all_rows=latest_posts(db,include_references=True)
    ref_ids={a['id'] for a in accounts(db) if not a['is_self']}
    ref_rows=[r for r in all_rows if r['account_id'] in ref_ids and r['platform']==platform]
    if ref_rows:
        with st.expander('选择这次的对标账号'):
            options=sorted({r['account_id'] for r in ref_rows})
            selected=st.multiselect('参照账号',options,default=options,format_func=lambda aid:next(r['account_name'] for r in ref_rows if r['account_id']==aid),key='peer_selected_'+platform)
            st.caption('可排除不合适的参照。所选账号只有满足赛道、体裁、积累时长和数据要求，才会进入评分。')
        ref_rows=[r for r in ref_rows if r['account_id'] in selected]
    external=frame(ref_rows)
    result=peer_result(own,external,platform,(major,minor),age,media)
    st.caption('每位创作者取作品指标中位数，一人一票；仅比较已确认赛道、同体裁、同积累区间。当前未按粉丝量匹配。')
    if result['ready']:
        model=result['model'];row=dict(rows[0],title=minor+' · 我的账号战力',age_band=age,analysis_window='当前累计')
        for item in model['scores']:row[item['metric']]=item['value']
        with st.container(key='battle-stage'):
            left,right=st.columns([2.1,1],gap='large')
            with left:
                st.caption(major+' / '+minor+' · 账号画像')
                chart(radar_figure(model),key='peer_challenge_radar',surface='panel')
            with right:
                result_panel(model,result);share(row,model,key='peer')
        st.caption(f'探索性对标 · 自己{result["own_n"]}条作品，对标{result["n"]}位创作者 / {result["works"]}条作品。所选样本不代表全平台。')
        with st.expander('这次和谁比？评分如何计算？'):
            names={'csv':'CSV · 用户核对','bilibili_space':'B站空间采集','bilibili_manual':'B站手动','manual':'手动录入','douyin_creator_center':'抖音后台采集'}
            st.table(pd.DataFrame([{'参照账号':r['name'],'有效作品':r['n'],'最近观测':r['observed'],'数据来源':' / '.join(names.get(s,s) for s in r['sources'])} for r in result['accounts']]))
            st.caption('共同维度各自计算账号中位数的百分位，再等权平均；综合超过比例只计严格低于你的参照账号，并列不算超过。未使用的维度不补零。')
    else:
        with st.container(border=True):
            st.markdown('### 同行挑战，等待真实参照')
            st.write(result['reason'])
            st.progress(min(result['n']/5,1),text=f'符合范围的对标账号 {result["n"]} / 至少5位')
            st.caption('无需其他CLab用户注册。可使用已有参照账号或导入真实外部作品，样本够用后自动计算。')
    with st.expander('补充赛道或参照样本',expanded=not result['ready']):
        steps=['确认自己的作品赛道','导入外部参照 CSV','管理已有参照']
        if platform=='bilibili':steps.insert(1,'导入B站参照账号')
        step=st.selectbox('下一步',steps,key='peer_setup_step')
        if step=='确认自己的作品赛道':
            from creatorlab.classification_ui import editor
            editor(db,rows,'challenge_own_genre')
        elif step=='导入B站参照账号':
            reference_capture(db)
        elif step=='导入外部参照 CSV':
            reference_upload(db,platform,(major,minor))
        else:
            refs=[r for r in all_rows if r['account_id'] in ref_ids and r['platform']==platform]
            if refs:
                from creatorlab.classification_ui import editor
                aid=st.selectbox('参照账号',sorted({r['account_id'] for r in refs}),format_func=lambda a:next(r['account_name'] for r in refs if r['account_id']==a),key='challenge_ref_account')
                editor(db,[r for r in refs if r['account_id']==aid],'challenge_ref_genre')
            else:st.caption('尚无已导入的参照账号。B站公开账号采集入口仍在「创作进阶 → 分析与实验 → 学习对象」。')


def reference_upload(db,platform,pair):
    from creatorlab.challenge_import import preview,commit
    st.caption('每行一条真实作品。同一创作者使用相同creator_id；每人至少3条。必须填写来源链接及真实观测时间。')
    template='creator_id,title,external_id,published_at,observed_at,url,media_format,views,likes,comments,favorites,shares,coins,completion_rate\n'
    st.download_button('下载参照模板',template.encode('utf-8-sig'),'CLab-外部参照模板.csv','text/csv',key='peer_template')
    uploaded=st.file_uploader('外部参照 CSV',type=['csv'],key='peer_csv')
    if uploaded is None:return
    try:
        plan=preview(db,uploaded.getvalue(),platform)
        st.caption(f'{len(set(r["creator_id"] for r in plan))}位创作者 · {len(plan)}条作品 · 将标注为 {pair[0]} / {pair[1]}')
        st.dataframe(pd.DataFrame(plan)[['creator_id','title','views','published_at','observed_at','url']].head(10),hide_index=True)
        ack=st.checkbox('我已核对真实来源、账号ID与所选赛道；这些不是演示或估算数据',key='peer_csv_ack')
        if st.button('确认导入参照',disabled=not ack,key='peer_csv_commit'):
            commit(db,uploaded.getvalue(),platform,pair);st.rerun()
    except (ValueError,UnicodeDecodeError) as exc:st.error(str(exc))


def reference_capture(db):
    from pathlib import Path
    import subprocess,sys
    from creatorlab.bilibili_import import job_running,parse_uid
    from creatorlab.reference_import import prepare_reference
    from creatorlab.maintenance import backup_database
    root=Path(__file__).resolve().parents[1]
    uid=st.text_input('对标UP主的UID或空间链接',key='challenge_ref_uid')
    st.caption('使用现有B站浏览器采集流程，最多读取最近50条详情；如出现验证，请在窗口完成。采集后到“管理已有参照”确认赛道。')
    if st.button('导入这个参照账号',key='challenge_ref_capture',disabled=job_running(root)):
        try:
            uid=parse_uid(uid);backup_database(db,'before-reference-account');prepare_reference(db,uid)
            root.joinpath('local').mkdir(exist_ok=True)
            with open(root/'local'/'reference_import.log','a',encoding='utf-8') as log:
                subprocess.Popen([sys.executable,'-m','creatorlab.reference_import','--db',str(db),'--root',str(root),'--uid',uid],cwd=str(root),stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
            st.success('参照采集窗口已启动。完成后刷新，再确认作品赛道。')
        except (OSError,ValueError,RuntimeError) as exc:st.error(str(exc))
    if st.button('刷新参照数据',key='challenge_ref_refresh'):st.rerun()
