import pytest
from creatorlab.content_analysis import frame
from creatorlab.review import pattern_findings,representative_pair,hook_observation,display


def rows():
    return [dict(id=i,account_id=1,account_name='我',platform='douyin',title=f'作品{i}',
      category='变装' if i<5 else '剧情',track='COS / 动漫',published_at='2026-01-01',
      metric_recorded_at='2026-01-10',views=2000 if i<5 else 1000,
      completion_rate=.6 if i<5 else .3,bounce_rate_2s=.1+i*.02) for i in range(10)]


def test_unclassified_has_no_content_claim():
    data=rows()
    for row in data:row['category']='未分类'
    df=frame(data)
    assert not pattern_findings(df,'views')
    assert representative_pair(df,'views')  # still useful as a work-to-work comparison


def test_patterns_direction_age_and_track_boundaries():
    df=frame(rows())
    f=pattern_findings(df,'completion_rate')[0]
    assert f['category']=='变装' and f['n']==5 and f['other_n']==5
    assert pattern_findings(df,'bounce_rate_2s')[0]['category']=='变装'
    data=rows()
    for row in data[5:]:row['published_at']='2025-01-01'
    assert not pattern_findings(frame(data),'views')
    data=rows()
    for row in data[5:]:row['track']='生活 / Vlog'
    assert not pattern_findings(frame(data),'views')


def test_missing_metric_does_not_fall_back_and_zero_formats():
    df=frame(rows())
    assert representative_pair(df,'favorite_ratio') is None
    assert pattern_findings(df,'favorite_ratio')==[]
    assert display(0,'completion_rate')=='0.0%'
    assert display(None,'views')=='暂无数据'
    h=hook_observation(df)
    assert h['row']['id']==9 and h['n']==10 and h['gap']>0
