"""Explicit public refresh and user-reviewed, account-scoped reference sets."""
import json
import streamlit as st
from creatorlab.genres import TAXONOMY
from creatorlab.reference_workflow import save_scope,refresh_references
from creatorlab.workflow_store import documents


def reference_scope_panel(db,aid,samples,filters,key):
    if not st.toggle('保存或更新细分赛道参照',key=key+'_manage_scope'):return
    st.caption('参照单独保存，不写入个人作品库。标签只能筛出候选，需要你核对内容后确认赛道。')
    taxonomy=TAXONOMY['bilibili']
    major=st.selectbox('参照分区',list(taxonomy),key=key+'_scope_major')
    minor=st.selectbox('参照细分赛道',taxonomy[major],key=key+'_scope_minor')
    name=st.text_input('参照范围名称',placeholder='例如：我的COS角色参照',key=key+'_scope_name')
    lookup={r['bvid']:r for r in samples}
    pick_key=key+'_verified_samples'
    previous=st.session_state.get(pick_key,[])
    if any(i not in lookup for i in previous):st.session_state[pick_key]=[i for i in previous if i in lookup]
    chosen=st.multiselect('已核对内容的样本（最多2000条）',list(lookup),
        format_func=lambda b:lookup[b]['title'][:70]+' · '+b,max_selections=2000,key=pick_key)
    reviewed=st.checkbox('已查看所选作品，确认可作为这个细分赛道的学习参照',key=key+'_scope_reviewed')
    if st.button('保存赛道参照',key=key+'_save_scope',disabled=not reviewed or not chosen):
        try:
            save_scope(db,aid,name,major,minor,chosen,filters,samples)
            st.success('参照已保存；可在「创作进阶 → 创作助手」选择，供建议引用。')
        except ValueError as exc:st.error(str(exc))
    st.markdown('##### 更新所选公开样本')
    st.caption('每次最多10条；更新当前累计计数与公开标签。遇验证、限流或失败立即停止，旧快照保留；不把整库标为已更新。')
    update_key=key+'_refresh_samples'
    if any(i not in lookup for i in st.session_state.get(update_key,[])):st.session_state[update_key]=[]
    update=st.multiselect('本次更新的BV号',list(lookup),max_selections=10,key=update_key)
    if st.button('读取最新公开计数与标签',key=key+'_refresh_now',disabled=not update):
        try:
            with st.spinner('读取所选公开视频的公开数据…'):
                result=refresh_references(db,aid,update)
            st.session_state[key+'_last_refresh']=result
            st.rerun()
        except (ValueError,OSError) as exc:st.error(str(exc))
    if key+'_last_refresh' in st.session_state:
        r=st.session_state[key+'_last_refresh']
        st.info(f"本次更新{len(r['updated'])}条，失败{len(r['failures'])}条，未尝试{len(r['not_attempted'])}条。仅成功样本使用新快照。")
    logs=documents(db,'refresh',aid,'bilibili',5)
    if logs:
        with st.expander('最近更新记录'):
            for item in logs:st.json(item['data'])
    scopes=documents(db,'scope',aid,'bilibili')
    if scopes:
        with st.expander('已保存参照及导出'):
            for item in scopes:
                s=item['data'];st.write(s['name']+' · '+s['major']+' / '+s['minor']+f" · {len(s['bvids'])}条")
            st.download_button('导出赛道参照设置',json.dumps(scopes,ensure_ascii=False,indent=2).encode('utf-8'),
                               'CreatorLab-赛道参照.json','application/json',key=key+'_scopes_export')
    from creatorlab.workflow_backup import backup_panel
    backup_panel(db,aid,'bilibili',key+'_backup')
