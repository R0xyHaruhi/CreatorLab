from creatorlab.weekly_charts import percent_label,position_figure,median_gap_figure,playback_summary


def rows():
    return [dict(metric='views',label='播放',value=686900,median=5360900,mean=6902500,percent=100/844,n=844),
            dict(metric='likes',label='点赞',value=15500,median=297200,mean=362400,percent=0,n=844),
            dict(metric='comments',label='评论',value=None,median=4842,mean=7230,percent=None,n=824)]


def test_tiny_positions_keep_precision_and_zero_is_not_missing():
    assert percent_label(100/844)=='0.12%'
    assert percent_label(.001)=='<0.01%'
    assert percent_label(0)=='0%' and percent_label(None)=='—'
    fig=position_figure(rows()).to_plotly_json()
    trace=fig['data'][0]
    assert trace['text']==['0.12%','0%']
    assert trace['x']==[100/844,0]
    assert trace['customdata'][1][0]!='0'
    assert list(trace['y'])==['播放','点赞']
    assert fig['layout']['shapes'][0]['x0']==50


def test_median_ratio_is_not_percentile_and_missing_is_not_zero():
    fig=median_gap_figure(rows()).to_plotly_json()
    assert abs(fig['data'][0]['x'][0]-12.8124)<.01
    assert len(fig['data'][0]['x'])==2
    assert fig['layout']['shapes'][0]['x0']==100
    assert '1 /' not in playback_summary(rows())
    assert '中的 1 条（0.12%）' in playback_summary(rows())
    assert '12.81%' in playback_summary(rows())
    assert not median_gap_figure([dict(rows()[0],median=0)]).data[0].x
