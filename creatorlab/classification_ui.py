"""One canonical classification editor used everywhere."""
import streamlit as st
from creatorlab.feedback import scoped_selectbox
from creatorlab.genres import TAXONOMY,set_genre,genre_rows
from creatorlab.content_analysis import annotate
from creatorlab.hub import connect

from creatorlab.genres import LEGACY_TRACK as LEGACY


def editor(db,rows,key,single=False):
    from creatorlab.feedback import notify,show_notices
    show_notices()
    if not rows:return
    platform=rows[0]['platform'];taxonomy=TAXONOMY[platform];first=genre_rows(db,rows)[0].get('genre')
    majors=['未确认']+list(taxonomy);major=scoped_selectbox('分区',majors,index=majors.index(first['major']) if first else 0,key=key+'_major')
    minors=taxonomy.get(major,['未确认']);minor=scoped_selectbox('细分赛道',minors,index=minors.index(first['minor']) if first and first['minor'] in minors else 0,key=key+'_minor')
    with st.form(key+'_canonical'):
        ids=[rows[0]['id']] if single else st.multiselect('给哪些作品确认这个赛道',[r['id'] for r in rows],format_func=lambda i:next(r['title'][:65] for r in rows if r['id']==i),key=key+'_ids')
        old=rows[0] if single else {}
        form=st.text_input('表现形式（选填）',value=old.get('category','') if old.get('category')!='未分类' else '',placeholder='例如：实况讲解、变装、教程',key=key+'_format')
        topic=st.text_input('具体主题 / 游戏 / 角色（选填）',value=old.get('topic',''),key=key+'_topic')
        if single:
            secs=st.number_input('时长（秒，0表示未知）',0.,86400.,float(old.get('duration_seconds') or 0),key=key+'_duration')
            published=st.text_input('精确发布时间（固定窗口分析需要时分）',value=old.get('published_at') or '',key=key+'_published')
        default=st.checkbox('也设为账号学习对标赛道',key=key+'_default')
        if st.form_submit_button('确认赛道' if not single else '保存作品分类'):
            if not ids and not default:st.error('先选择作品，或设为账号赛道。');return
            if major=='未确认' and (not single or default):st.error('请选择有效分区与细分赛道。');return
            if single and published!=(old.get('published_at') or ''):
                from creatorlab.measurements import timestamp
                if timestamp(published) is None:st.error('精确发布时间需包含时分和时区。');return
            for pid in ids:
                r=next(x for x in rows if x['id']==pid)
                if major!='未确认':set_genre(db,pid,major,minor)
                annotate(db,pid,LEGACY.get(major,r.get('track','其他')),(form.strip() or '未分类') if single else form or r.get('category') or '未分类',topic.strip() if single else topic or r.get('topic',''),(secs or None) if single else r.get('duration_seconds'))
                if single and published!=(old.get('published_at') or ''):
                    from creatorlab.measurements import timestamp
                    if timestamp(published) is None:st.error('请填写含时分和时区的时间，例如2026-10-26T12:00:00+08:00');return
                    with connect(db) as con:con.execute('UPDATE hub_posts SET published_at=? WHERE id=?',(published,pid))
            if default:
                with connect(db) as con:con.execute('INSERT OR REPLACE INTO hub_account_genres VALUES(?,?,?)',(rows[0]['account_id'],major,minor))
            notify(f'已保存 {len(ids)} 条作品的赛道'+('，并更新账号学习对标赛道。' if default else '。'))
            st.rerun()
    st.caption('所有入口使用同一套：分区 → 细分赛道 → 具体主题 → 表现形式。旧分类保留兼容，不再重复填写两套。')
