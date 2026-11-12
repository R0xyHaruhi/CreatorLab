"""Local checks plus explicit source-page reconciliation; never fakes online acceptance."""
import json
import math
from creatorlab.hub import connect,accounts,latest_posts,utcnow
from creatorlab.bilibili_account import latest_fields
from creatorlab.covers import cached_cover


def reconcile(db,aid,metric,expected,actual,note):
    expected=float(expected)
    if not math.isfinite(expected) or expected<0:raise ValueError('请输入源页面的非负数字')
    result={'metric':metric,'expected':expected,'actual':actual,'passed':actual is not None and abs(float(actual)-expected)<1e-9,'note':note}
    with connect(db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS clab_acceptance_checks(id INTEGER PRIMARY KEY,account_id INTEGER,created_at TEXT,result_json TEXT)')
        con.execute('INSERT INTO clab_acceptance_checks(account_id,created_at,result_json) VALUES(?,?,?)',(aid,utcnow(),json.dumps(result,ensure_ascii=False)))
    return result


def panel(db,platform=None):
    import streamlit as st
    import pandas as pd
    from creatorlab.sync_jobs import failures
    st.markdown('### 实机核对与失败诊断')
    own=[a for a in accounts(db) if a['is_self'] and (platform is None or a['platform']==platform)]
    if not own:st.info('导入一个真实账号后，可逐项核对源页面与工作台的数值。');return
    aid=st.selectbox('验收哪个账号',[a['id'] for a in own],format_func=lambda i:next(a['display_name'] for a in own if a['id']==i),key='acceptance_account')
    acc=next(a for a in own if a['id']==aid);rows=[r for r in latest_posts(db) if r['account_id']==aid]
    with connect(db) as con:integrity=con.execute('PRAGMA quick_check').fetchone()[0]
    st.write('本地数据库检查：'+integrity)
    st.caption(f'作品 {len(rows)} 条；缓存封面 {sum(bool(cached_cover(db,r["platform"],r["external_id"])) for r in rows)} 条。这里只检查本地状态，不代表源网站已验收。')
    options={'账号粉丝量':('followers',latest_fields(db,aid).get('followers',{}).get('value'))} if acc['platform']=='bilibili' else {}
    for r in rows[:50]:
        for key,label in [('views','播放'),('likes','点赞'),('shares','分享'),('favorites','收藏')]:options[r['title'][:35]+' / '+label+' #'+str(r['id'])]=(str(r['id'])+':'+key,r.get(key))
    if options:
        chosen=st.selectbox('打开源页面后，要核对哪一个值',list(options),key='acceptance_field')
        key,actual=options[chosen];st.write('工作台当前记录：'+str(actual if actual is not None else '未知'))
        expected=st.text_input('源页面完整数字（不要输入“1.2万”缩写）',key='acceptance_expected')
        note=st.text_input('核对页面 / 时间范围备注',key='acceptance_note')
        if st.button('保存这一项实机核对'):
            try:
                result=reconcile(db,aid,key,expected,actual,note)
                st.success('这一项数值一致，已保存记录。') if result['passed'] else st.error('这一项不一致，已保存失败记录；先定向补采或检查口径。')
            except (ValueError,TypeError) as exc:st.error(str(exc))
    if acc['platform']=='bilibili':
        pending=failures(db,acc['handle'])
        if pending:st.table(pd.DataFrame([{'作品ID':r['external_id'],'缺失':', '.join(r['missing']),'原因':r['error']} for r in pending]))
    with connect(db) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='clab_acceptance_checks'").fetchone()
        history=[dict(r) for r in con.execute('SELECT created_at,result_json FROM clab_acceptance_checks WHERE account_id=? ORDER BY id DESC LIMIT 20',(aid,))] if exists else []
    if history:
        st.table(pd.DataFrame([{'核对时间':r['created_at'],**json.loads(r['result_json'])} for r in history]))
        st.download_button('导出本账号核对记录',json.dumps(history,ensure_ascii=False,indent=2).encode(),'clab_acceptance.json','application/json')
    st.caption('离线测试、人工单字段核对和完整线上验收是不同状态；程序不会把前两者自动升级成“整个平台已验证可用”。')
