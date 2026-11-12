"""Team peer-matching UI; accounts are user-provided, not automatically discovered."""
import pandas as pd
import streamlit as st
from .benchmarks import save_account,list_accounts,match_peers,delete_account

def render(db,lang):
    zh=lang=='zh'
    st.subheader('🔎 同行对标' if zh else '🔎 Peer benchmarking')
    st.info('目前从你维护的账号库中自动匹配，不会自行抓取抖音博主。数据来源标签由录入者声明，软件尚未独立核验；未录入的指标不会被推测。' if zh else 'Matches accounts from your local directory; does not scrape Douyin. Add verified metrics manually or via authorized sources.')
    with st.expander('① 添加对标账号 / 维护数据' if zh else '① Add a peer account',expanded=False):
        with st.form('add_peer'):
            handle=st.text_input('账号名称 / Handle')
            url=st.text_input('账号主页链接（选填）' if zh else 'Profile URL (optional)')
            niche=st.text_input('赛道' if zh else 'Niche',value='COS/二次元')
            tags=st.text_input('内容标签，逗号分隔' if zh else 'Tags, comma separated',placeholder='变装,萌系,动漫角色')
            c1,c2,c3=st.columns(3)
            followers=c1.text_input('粉丝数（选填）' if zh else 'Followers (optional)')
            views=c2.text_input('近 30 天单条播放中位数（选填）' if zh else 'Median views (optional)')
            engagement=c3.text_input('互动率 %（选填）' if zh else 'Engagement rate % (optional)')
            c4,c5=st.columns(2)
            posts=c4.text_input('近 30 天发布数（选填）' if zh else 'Posts in 30d (optional)')
            growth=c5.text_input('近 30 天粉丝增长率 %（选填）' if zh else 'Growth % in 30d (optional)')
            source=st.selectbox('数据来源' if zh else 'Source',['manual','public_verified','authorized'],format_func=lambda v:{'manual':'手动录入 / Manual','public_verified':'已核验公开数据 / Verified public','authorized':'账号授权数据 / Authorized'}[v])
            note=st.text_input('来源备注（如后台截图、采集日期）' if zh else 'Source notes')
            if st.form_submit_button('保存账号' if zh else 'Save account'):
                try:
                    def num(s):return int(s.strip()) if s.strip() else None
                    def pct(s):return float(s.strip())/100 if s.strip() else None
                    save_account(db,dict(platform='douyin',handle=handle,account_url=url,niche=niche,tags=tags,followers=num(followers),median_views=num(views),engagement_rate=pct(engagement),posts_30d=num(posts),growth_30d=pct(growth),source_type=source,source_note=note))
                    st.success('已保存' if zh else 'Saved');st.rerun()
                except (ValueError,TypeError) as exc:st.error(str(exc))
    accounts=list_accounts(db,'douyin')
    st.caption(('账号库：%d 个真实/用户录入账号（演示数据默认不参与匹配）' if zh else '%d user-provided accounts (demo excluded)')%len(accounts))
    if accounts:
        view=pd.DataFrame([{'账号':a['handle'],'赛道':a['niche'],'标签':a['tags'],'粉丝数':a['followers'],'播放中位数':a['median_views'],'互动率':round(a['engagement_rate']*100,2) if a['engagement_rate'] is not None else None,'来源':a['source_type'],'更新日期':a['observed_at']} for a in accounts])
        st.dataframe(view,hide_index=True,use_container_width=True)
    with st.form('peer_target'):
        st.markdown('**② 选择你要分析的账号**' if zh else '**② Your account**')
        own=st.selectbox('从账号库选择' if zh else 'Select account', ['手动输入']+[a['handle'] for a in accounts])
        own_name=st.text_input('我的账号名称' if zh else 'My account handle',value='' if own=='手动输入' else own)
        own_tags=st.text_input('我的内容标签' if zh else 'My tags',value='COS,二次元')
        own_followers=st.text_input('我的粉丝数（选填）' if zh else 'My followers (optional)')
        own_views=st.text_input('我的播放中位数（选填）' if zh else 'My median views (optional)')
        own_eng=st.text_input('我的互动率 %（选填）' if zh else 'My engagement rate % (optional)')
        mode=st.radio('匹配范围' if zh else 'Comparison group',['both','similar','leaders'],format_func=lambda x:{'both':'同量级 + 头部参考','similar':'同量级','leaders':'头部参考'}[x],horizontal=True)
        go=st.form_submit_button('开始匹配' if zh else 'Match peers',type='primary')
    if go:
        try:
            base=next((a.copy() for a in accounts if a['handle']==own),{'platform':'douyin','niche':'COS/二次元'})
            base.update({'handle':own_name,'tags':own_tags,'followers':int(own_followers) if own_followers.strip() else base.get('followers'),'median_views':int(own_views) if own_views.strip() else base.get('median_views'),'engagement_rate':float(own_eng)/100 if own_eng.strip() else base.get('engagement_rate')})
            matches=match_peers(base,accounts,mode=mode)
            st.session_state['peer_matches']=matches
        except ValueError:st.error('请检查粉丝数、播放量和互动率格式' if zh else 'Please check numeric inputs')
    if 'peer_matches' in st.session_state:
        matches=st.session_state['peer_matches']
        st.markdown('**③ 匹配结果**' if zh else '**③ Results**')
        if not matches:st.warning('暂时没有符合条件的账号。请添加同行账号并填写可比较的指标。' if zh else 'No matching accounts. Add peer records first.')
        else:
            st.dataframe(pd.DataFrame([{'账号':a['handle'],'类型':a['segment'],'匹配分':a['match_score'],'可信度':f"{a['confidence_label']} {a['confidence']}%",'粉丝':a['followers'],'播放中位数':a['median_views'],'数据来源':a['source_type'],'缺失指标':a['missing']} for a in matches]),hide_index=True,use_container_width=True)
            st.caption('匹配分 = 已有指标的加权相似度；可信度 = 指标完整度 × 数据新鲜度 × 来源质量。分数不是增长预测，也不代表官方认证。' if zh else 'Match scores are weighted similarity, not growth forecasts. Confidence reflects completeness, recency and provenance.')
            st.download_button('下载匹配结果 CSV' if zh else 'Download results CSV',pd.DataFrame(matches).to_csv(index=False).encode('utf-8-sig'),'creatorlab_peer_matches.csv','text/csv')
    if accounts:
        with st.expander('删除对标账号' if zh else 'Delete peer'):
            to_delete=st.selectbox('选择账号' if zh else 'Select account',accounts,format_func=lambda a:a['handle'])
            if st.button('确认删除' if zh else 'Delete',key='delete_peer'):
                delete_account(db,to_delete['id']);st.session_state.pop('peer_matches',None);st.rerun()
