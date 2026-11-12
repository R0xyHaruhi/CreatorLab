from creatorlab.hub import quality, eligible, sort_posts

def test_zero_not_private():
    row={'views':0,'likes':0,'comments':0,'shares':0,'favorites':0,'visibility':None}
    assert quality(row)=='零播放待核实'
    assert eligible([row])==[]

def test_zero_with_engagement_suspect():
    row={'views':0,'likes':8,'comments':0,'shares':0,'favorites':0,'visibility':None}
    assert quality(row)=='播放量疑似异常'

def test_private_excluded_even_with_views():
    assert quality({'visibility':'private','views':500})=='不可公开计量'

def test_missing_values_sort_last():
    rows=[{'views':None},{'views':4},{'views':20}]
    assert sort_posts(rows,'播放量最高')==[rows[2],rows[1],rows[0]]
