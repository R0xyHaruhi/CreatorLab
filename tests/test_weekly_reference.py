import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.weekly_reference import DATASET, load_dataset, select_samples, comparison_rows, parse_tags
from creatorlab.hub import init_hub, add_account, upsert_post, connect, latest_posts


def test_bundled_completed_100_issues_only_and_provenance():
    info, rows = load_dataset()
    assert info['issues'] == 100 and info['entries'] == 4620
    assert info['videos'] == len(rows) == 4600 and info['exclusions'] == 20
    assert info['tagged_videos'] == 4539 and info['is_sitewide'] is False
    assert len({r['bvid'] for r in rows}) == len(rows)
    assert all(r['issues'] and set(r['issues']) <= set(range(292, 392)) for r in rows)
    assert all(r['source_url'].startswith('https://www.bilibili.com/') for r in rows)
    assert sum(r['precision']['views']['precision'] == 'approximate_abbreviated' for r in rows) == 89
    assert sum(r['comments'] is None for r in rows) > 0
    with sqlite3.connect(DATASET) as con:
        assert con.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert not con.execute('pragma foreign_key_check').fetchall()
        assert con.execute('select count(*) from sample_issues').fetchone()[0] == 100
        assert not con.execute("select name from sqlite_master where name like 'hub_%'").fetchall()


def test_tags_explicit_partial_matches_date_opt_in_and_self_exclusion():
    _, rows = load_dataset()
    assert parse_tags('ＣＯＳＰＬＡＹ，#凉宫春日') == ['cosplay', '凉宫春日']
    found = select_samples(rows, tags=['CoSpLaY', '__not_a_real_tag__'])
    assert found and all(r['unmatched_tags'] == ('__not_a_real_tag__',) for r in found)
    assert select_samples(rows, tags=['CoSpLaY', '__not_a_real_tag__'], require_all=True) == []
    assert select_samples(rows, tags=['__not_a_real_tag__']) == []
    assert len(select_samples(rows)) == 4600
    excluded = select_samples(rows, exclude_bvids=[rows[0]['bvid']])
    assert len(excluded) == 4599 and all(r['bvid'] != rows[0]['bvid'] for r in excluded)
    one_issue = select_samples(rows, issues=[391])
    assert one_issue and all(391 in r['issues'] for r in one_issue)
    filtered = select_samples(rows, published_range=('2026-01-01', '2026-12-31'))
    assert all(r['published_at'] and '2026-01-01' <= r['published_at'][:10] <= '2026-12-31' for r in filtered)
    assert any(r['published_at'] is None for r in rows)


def test_counts_do_not_let_two_views_one_like_dominate_and_missing_is_not_zero():
    _, rows = load_dataset()
    counts = comparison_rows({'views': 2, 'likes': 1}, rows)
    assert next(r for r in counts if r['metric'] == 'likes')['percent'] < 1
    assert next(r for r in counts if r['metric'] == 'comments')['value'] is None
    samples = [dict(views=100, likes=0), dict(views=200, likes=10, comments=0)]
    comparison = comparison_rows(dict(views=100, likes=0), samples)
    assert comparison[0]['percent'] == 0  # Equal values never count as exceeded.
    assert next(r for r in comparison if r['metric'] == 'comments')['n'] == 1
    rates = comparison_rows(dict(views=100, likes=10, _ratio_allowed={'likes': False}), samples, rates=True)
    assert next(r for r in rates if r['metric'] == 'likes')['value'] is None


def test_bundle_corruption_is_detected_before_query(tmp_path):
    path = tmp_path / DATASET.name
    shutil.copyfile(DATASET, path)
    shutil.copyfile(DATASET.with_suffix('.json'), path.with_suffix('.json'))
    data = bytearray(path.read_bytes());data[-1] ^= 1;path.write_bytes(data)
    with pytest.raises(ValueError, match='校验失败'):
        load_dataset(path)


def test_browse_without_personal_account_and_apply_tags():
    code = "from creatorlab.weekly_ui import panel\npanel([])"
    app = AppTest.from_string(code, default_timeout=30).run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.metric[0].value == '4,600'
    assert app.checkbox(key='weekly_date_filter').value is False
    app.text_input(key='weekly_tags').set_value('__not_a_real_tag__').run()
    assert not app.exception and app.metric[0].value == '0'
    assert not app.get('plotly_chart')
    app.text_input(key='weekly_tags').set_value('COSPLAY').run()
    assert not app.exception and int(app.metric[0].value.replace(',', '')) > 0


def test_own_public_tags_button_and_unstable_small_ratio():
    row = dict(id=1, platform='bilibili', title='我的小样本', views=2, likes=1,
               comments=None, external_id='not-in-references', bili_tags=['COSPLAY'],
               visibility='public', metric_recorded_at='2026-11-03T00:00:00Z')
    code = 'from creatorlab.weekly_ui import panel\npanel(' + repr([row]) + ')'
    app = AppTest.from_string(code, default_timeout=30).run()
    app.button(key='weekly_use_tags').click().run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.text_input(key='weekly_tags').value == 'COSPLAY'
    assert any('比例可能不稳定' in c.value for c in app.caption)
    assert any('不是综合质量评分' in c.value for c in app.caption)


def test_integrated_app_platform_switch_and_no_reference_import_into_personal_db(tmp_path, monkeypatch):
    db = tmp_path / 'personal.db';init_hub(db)
    for platform in ('bilibili', 'douyin'):
        aid = add_account(db, platform, platform + '-own')
        for i in range(3):
            upsert_post(db, aid, platform + '个人作品' + str(i), platform + str(i),
                        '2026-01-01T00:00:00Z', metrics=dict(views=100+i, likes=10, comments=2,
                        favorites=3, shares=1, coins=2, danmaku=3), observed_at='2026-11-01T00:00:00Z')
    monkeypatch.setenv('CREATORLAB_DB', str(db))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=45).run()
    app.radio(key='platform_space').set_value('B站空间').run()
    app.get('button_group')[0].set_value('每周必看').run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.selectbox(key='weekly_compare_work')
    app.radio(key='platform_space').set_value('抖音空间').run()
    assert not app.exception, [e.message for e in app.exception]
    assert app.get('button_group')[0].value=='直观看表现'
    assert not any('每周必看' in option for option in app.get('button_group')[0].options)
    assert not any((s.key or '').startswith('weekly_') for s in app.selectbox)
    with connect(db) as con:
        assert con.execute('select count(*) from hub_accounts').fetchone()[0] == 2
        assert con.execute('select count(*) from hub_posts').fetchone()[0] == 6
    assert len(latest_posts(db, include_references=True)) == 6
