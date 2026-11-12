from creatorlab.hub import init_hub
from creatorlab.ext_platforms import (detect_mapping, parse_count, parse_time, import_csv, ext_posts, delete_account)
import pytest

CSV='作品ID,标题,发布时间,阅读量,点赞,评论,收藏,转发\nfirst,第一篇,2026-10-01 20:30,"1.2万",300,12,40,5\nsecond,第二篇,2026/10/02,3456,,3,,\n, ,2026-10-03,1,1,1,1,1\n'


def test_parse_count_handles_chinese_units():
    assert parse_count('1.2万')==12000 and parse_count('3,456')==3456 and parse_count('2亿')==200000000
    assert parse_count('')is None and parse_count('--') is None
    with pytest.raises(ValueError):parse_count('很多')
    with pytest.raises(ValueError):parse_count('-5')


def test_parse_time_assumes_china_time_and_rejects_garbage():
    assert parse_time('2026-10-01 20:30')=='2026-10-01T20:30:00+08:00'
    assert parse_time('2026年10月1日')=='2026-10-01T00:00:00+08:00'
    assert parse_time('1759321800').endswith('+08:00')
    assert parse_time('')is None
    with pytest.raises(ValueError):parse_time('昨天')


def test_mapping_never_maps_impressions_to_views():
    m=detect_mapping(['标题','曝光量','展现','播放量'])
    assert m['views']=='播放量'
    assert 'views' not in detect_mapping(['标题','曝光量','展现'])


def test_import_and_blank_cells_do_not_erase(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    r=import_csv(db,'xiaohongshu','我的号',CSV)
    assert (r['inserted'],r['updated'],r['skipped'])==(2,0,1)
    rows={x['title']:x for x in ext_posts(db,'xiaohongshu')}
    assert rows['第一篇']['views']==12000 and rows['第一篇']['shares']==5
    assert rows['第二篇']['likes'] is None             # blank stays unknown, not 0
    r2=import_csv(db,'xiaohongshu','我的号','作品ID,标题,发布时间,阅读量,点赞\nfirst,第一篇,2026-10-01 20:30,15000,\n')
    assert (r2['inserted'],r2['updated'])==(0,1)
    again={x['title']:x for x in ext_posts(db)}['第一篇']
    assert again['views']==15000 and again['likes']==300   # blank like kept old value


def test_errors_are_reported_per_line_and_platform_validated(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    r=import_csv(db,'weibo','号','标题,播放量\n好,abc\n坏,5\n')
    assert r['inserted']==1 and r['skipped']==1 and '第 2 行' in r['errors'][0]
    with pytest.raises(ValueError):import_csv(db,'tiktok2','号',CSV)
    with pytest.raises(ValueError):import_csv(db,'weibo','号','foo,bar\n1,2\n')
    with pytest.raises(ValueError):import_csv(db,'weibo','','标题,播放量\na,1\n')


def test_delete_account_only_removes_that_account(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    import_csv(db,'weibo','A','标题,播放量\n甲,1\n');import_csv(db,'weibo','B','标题,播放量\n乙,2\n')
    assert delete_account(db,'weibo','A')==1 and [r['title'] for r in ext_posts(db)]==['乙']


def test_alias_priority_beats_column_order():
    m=detect_mapping(['内容','标题','播放量'])
    assert m['title']=='标题'
