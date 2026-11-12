"""An offline selected-sample comparison, with user-controlled scope."""
import json
import math
from datetime import date
import pandas as pd
import streamlit as st
from creatorlab.appearance import chart
from creatorlab.hub import eligible, fmt_count
from creatorlab.weekly_reference import load_dataset, parse_tags, select_samples, comparison_rows, tag_facets
from creatorlab.weekly_charts import percent_label, lower_count, position_figure, median_gap_figure, playback_summary


def _value(value, rates=False):
    if value is None or not math.isfinite(float(value)):
        return '—'
    return f'{value:.2%}' if rates else fmt_count(value)


def _comparison_table(rows, rates=False):
    return pd.DataFrame([{'指标': r['label'], '我的作品': _value(r['value'], rates),
                          '样本中位数': _value(r['median'], rates), '样本平均值': _value(r['mean'], rates),
                          '高于当前精选样本': percent_label(r['percent']),
                          '严格高于 / 有效样本': '—' if r['percent'] is None else f"{lower_count(r):,} / {r['n']:,}",
                          '有效样本': r['n']} for r in rows])


def panel(rows, key='weekly'):
    st.subheader('B站每周必看精选库')
    try:
        info, records = load_dataset()
    except (OSError, ValueError, KeyError) as exc:
        st.error('精选参照库暂时不可用。请使用包含 assets/references 的完整升级包。')
        st.caption(str(exc))
        return
    st.markdown(f"**{info['issues']} 期 · {info['videos']:,} 条精选作品**")
    st.caption(f"收录第 {info['issue_min']}–{info['issue_max']} 期，其中 {info['tagged_videos']:,} 条有公开标签。")
    st.caption('对比使用采集时的累计数据，样本位置仅适用于所选精选作品。')
    own = [r for r in eligible(rows) if r.get('platform') == 'bilibili' and not r.get('demo')]
    from creatorlab.personal_ui import dated_label
    if own:
        ids = [r['id'] for r in own]
        selected_key = key + '_work'
        if st.session_state.get(selected_key) not in (None, *ids):
            st.session_state.pop(selected_key, None)
        selected = st.selectbox('选择我的B站作品', ids,
                                format_func=lambda i: dated_label(next(r for r in own if r['id'] == i)), key=selected_key)
        target = next(r for r in own if r['id'] == selected)
        if target.get('_db'):
            from creatorlab.reference_workflow import reference_view
            info,records=reference_view(target['_db'],target['account_id'])
            if info['locally_updated']:
                st.caption(f"内置快照保持原样；叠加当前账号本地更新的{info['locally_updated']}条样本，逐条观测时间见来源列表。")
    else:
        target = None
        st.caption('可先浏览真实样本；导入自己的B站作品后即可进行对比。')
    summary_area = st.container(key=key + '_summary')
    default_tags = target.get('bili_tags', []) if target else []
    if key + '_pending_tags' in st.session_state:
        st.session_state[key + '_tags'] = st.session_state.pop(key + '_pending_tags')
    filters = st.expander('筛选参照范围')
    with filters:
        tag_text = st.text_input('匹配标签（用逗号分隔）', key=key + '_tags', placeholder='例如：COSPLAY，凉宫春日')
        if default_tags:
            st.caption('当前作品公开标签：' + '、'.join(default_tags))
            if st.button('使用当前作品的公开标签', key=key + '_use_tags'):
                st.session_state[key + '_pending_tags'] = '，'.join(default_tags)
                st.rerun()
        matching = st.radio('标签匹配', ['任一标签', '全部标签'], horizontal=True, key=key + '_match')
        issues = st.multiselect('入选期数（留空=全部100期）', list(range(info['issue_max'], info['issue_min'] - 1, -1)), key=key + '_issues')
        published_range = None
        if st.checkbox('按作品发布时间筛选', value=False, key=key + '_date_filter'):
            known = sorted(r['published_at'][:10] for r in records if r['published_at'])
            chosen = st.date_input('发布时间范围', value=(date.fromisoformat(known[0]), date.fromisoformat(known[-1])), key=key + '_dates')
            if not isinstance(chosen, (tuple, list)) or len(chosen) != 2:
                summary_area.info('请选择完整的开始和结束日期。')
                return
            published_range = tuple(d.isoformat() for d in chosen)
            st.caption('开启后只保留范围内、发布时间已知的作品；默认不按时间筛选。')
    tags = parse_tags(tag_text)
    excluded = {str(r.get('external_id')) for r in rows if r.get('platform') == 'bilibili' and r.get('external_id')}
    samples = select_samples(records, tags=tags, require_all=matching == '全部标签', issues=issues,
                             published_range=published_range, exclude_bvids=excluded)
    facets = tag_facets(samples)
    refine_key = key + '_refine_tags'
    previous = st.session_state.get(refine_key, [])
    retained = [t for t in previous if t in facets]
    if previous != retained:
        st.session_state[refine_key] = retained
    options = list(dict.fromkeys(list(facets)[:100] + retained))
    required_tags = filters.multiselect('进一步细分：必须同时包含的公开标签', options,
                                  format_func=lambda t: f'{t}（{facets[t]:,}条）', key=refine_key)
    filters.caption('候选来自当前筛选后的作品。追加标签必须全部命中，标签相似不等于已确认同赛道。')
    if required_tags:
        samples = select_samples(samples, tags=tags, require_all=matching == '全部标签', required_tags=required_tags)
    comparable = target and target.get('analysis_window') in (None, '', '当前累计')
    counts = comparison_rows(target, samples) if comparable and samples else []
    with summary_area:
        st.markdown(f'**当前参照 {len(samples):,} 条精选作品**')
        issue_scope = '第 ' + '、'.join(map(str, issues)) + ' 期' if 0 < len(issues) <= 3 else f'已选 {len(issues)} 期' if issues else '全部期数'
        date_scope = ' 至 '.join(published_range) if published_range else '不限发布时间'
        st.caption('当前标签范围：' + ('、'.join(tags) + '（' + matching + '）' if tags else '不限')
                   + ' · 追加全部命中：' + ('、'.join(required_tags) if required_tags else '不限')
                   + f' · {issue_scope} · {date_scope}')
        if not samples:
            st.info('当前范围没有可用参照。可以清除筛选或放宽条件。')
            def clear_filters():
                defaults = {'_tags':'', '_match':'任一标签', '_issues':[], '_date_filter':False, '_refine_tags':[]}
                st.session_state.update({key+suffix: value for suffix,value in defaults.items()})
                st.session_state.pop(key+'_dates', None)
            st.button('清除筛选', key=key+'_clear_filters', on_click=clear_filters)
        elif target and not comparable:
            st.info('当前作品使用固定窗口指标。请切换到累计数据后对比。')
        elif counts:
            summary = playback_summary(counts)
            if summary:st.info(summary)
        if 0 < len(samples) < 5:
            st.warning('当前参照不足5条，仅作少样本事实对照；样本位置不用于综合评分或增长判断。')
    a, b, c = st.columns(3)
    a.metric('当前参照作品', f'{len(samples):,}')
    b.metric('播放中位数', _value(float(pd.Series([r['views'] for r in samples], dtype=float).median())) if samples else '—')
    c.metric('点赞中位数', _value(float(pd.Series([r['likes'] for r in samples], dtype=float).median())) if samples else '—')
    observed=sorted(str(r['observed_at']) for r in samples if r.get('observed_at'))
    if observed:
        st.caption(f"当前范围观测时间（UTC）：{observed[0][:10]} 至 {observed[-1][:10]} · 发布时间筛选由你选择")
    else:
        st.caption('当前范围没有可展示的观测时间；逐条时间见来源列表。')
    if counts:
        st.markdown('#### 播放与互动数量')
        st.caption('图表比较当前范围内每周必看作品的累计数据。')
        perspective=st.radio('图表视角',['在精选样本中的位置','与精选中位数的差距'],horizontal=True,key=key+'_chart_view')
        if perspective=='在精选样本中的位置':
            st.markdown('##### 我的作品高于多少精选样本？')
            if any(r['percent'] is not None for r in counts):chart(position_figure(counts),key=key+'_positions')
            st.caption('点越靠右，该指标数值越高于更多精选作品。0%表示没有样本严格更低，不表示播放或互动为0；相同数值不算超过。')
        else:
            st.markdown('##### 我的数量相当于精选中位数的多少？')
            chart(median_gap_figure(counts),key=key+'_median_gap')
            st.caption('100%等于当前精选中位数，20%表示只有中位数的五分之一；这不是排名或超过的样本占比。中位数为0或缺失的项目不绘图。')
        st.caption('播放和互动数量的样本位置不是综合质量评分。未取得的指标不画成0；每个指标使用各自的有效样本数。')
        st.markdown('##### 查看具体数值与有效样本')
        st.dataframe(_comparison_table(counts), hide_index=True, width='stretch')
        with st.expander('查看互动 / 播放比例'):
            st.dataframe(_comparison_table(comparison_rows(target, samples, rates=True), rates=True), hide_index=True, width='stretch')
            st.caption('比例用于观察互动效率，与播放体量和互动数量一起理解；不同观测时间的个人指标不计算比例。')
            if target.get('views') is not None and target['views'] < 1000:
                st.caption('当前播放样本较小，比例可能不稳定；不据此生成综合战力或增长判断。')
        st.caption('我的指标观测于：' + str(target.get('metric_recorded_at') or '时间未知'))
    with st.expander('浏览匹配作品', expanded=not bool(target)):
        visible = pd.DataFrame([{'作品': r['title'], 'BV号': r['bvid'], '播放': r['views'], '点赞': r['likes'],
                                 '收藏': r['favorites'], '投币': r['coins'], '命中标签': '、'.join(r['matched_tags']),
                                 '未命中查询标签': '、'.join(r['unmatched_tags']), '公开标签': '、'.join(r['tags']),
                                 '入选期数': '、'.join(map(str, r['issues'])), '发布时间': r['published_at'],
                                 '观测时间': r['observed_at'], '来源': r['source_url']} for r in samples])
        if samples:
            st.dataframe(visible.head(100), column_config={'来源': st.column_config.LinkColumn('来源')}, hide_index=True, width='stretch')
            st.caption('页面显示前100条。标签排序是内容相似候选，不是经确认的同行，也不是置信概率。')
            export = visible.copy()
            export['样本范围'] = info['scope']
            export['查询标签'] = '、'.join(tags)
            export['查询标签匹配'] = matching
            export['追加全部命中标签'] = '、'.join(required_tags)
            export['筛选期数'] = '、'.join(map(str, issues)) if issues else '全部'
            export['发布时间范围'] = ' 至 '.join(published_range) if published_range else '不限'
            export['指标精度'] = [json.dumps(r['precision'], ensure_ascii=False) for r in samples]
            for column in export.select_dtypes(include='object'):
                export[column] = export[column].map(lambda v: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v)
            st.download_button('导出当前参照 CSV', export.to_csv(index=False).encode('utf-8-sig'), 'CLab-B站精选参照.csv', 'text/csv', key=key + '_csv')
    with st.expander('数据来源与计算口径'):
        st.caption(f"100期当前可见清单共{info['entries']:,}条，成功读取{info['videos']:,}条；{info['exclusions']}条失效或无法确认单条视频指标的记录已排除。当前可见清单不保证等于最初上榜清单。")
        st.caption('缩略显示的“万、亿”保留为近似值。缺失指标不填0；每个指标按自己的有效样本计算均值、中位数及严格低于当前作品的比例。相同BV号的个人作品从参照中排除。')
        st.caption('精选参照与个人账号、个人作品库独立存放。公开页没有的完播率、观看时长和新增粉丝不会估算。')
        st.link_button('查看B站每周必看', 'https://www.bilibili.com/v/popular/weekly/')
    if target and target.get('_db'):
        from creatorlab.reference_workflow_ui import reference_scope_panel
        reference_scope_panel(target['_db'],target['account_id'],samples,
            dict(tags=tags,require_all=matching=='全部标签',required_tags=required_tags,
                 issues=issues,published_range=published_range),key)
