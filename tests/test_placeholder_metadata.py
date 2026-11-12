from creatorlab.work_formats import match_visible_metadata


def source():
    row=dict(video_id='7412345678901234567',title='视频 7412345678901234567',
             published_at='2023-12-03T03:18:42+00:00',cover_url='https://p3.douyinpic.com/tos/a~one.webp')
    card=dict(title='源页真实标题\n#标签',published_at='2023-12-02T19:18:00-08:00',
              cover_url='https://p5.douyinpic.com/tos/a~two.webp',visibility='private')
    return row,card


def test_placeholder_recovers_actual_title_and_privacy_from_unique_cover_and_minute():
    row,card=source()
    result=match_visible_metadata([card],[row])
    assert result==[dict(video_id=row['video_id'],title='源页真实标题 #标签',visibility='private')]


def test_no_title_guess_with_only_date_or_similar_cover_or_wrong_minute():
    row,card=source()
    for changed in (dict(card,cover_url=None),dict(card,cover_url='https://p5.douyinpic.com/tos/b'),
                    dict(card,published_at='2023-12-03T03:19:00+00:00')):
        assert match_visible_metadata([changed],[row])==[]


def test_repeated_cover_minute_and_manual_titles_remain_untouched():
    row,card=source()
    assert not match_visible_metadata([card,dict(card,title='另一个作品')],[row])
    other=dict(row,video_id='7412345678901234568',title='视频 7412345678901234568')
    assert not match_visible_metadata([card],[row,other])
    assert not match_visible_metadata([card],[dict(row,title='用户自定义标题')])


def test_blank_source_title_can_fix_visibility_without_inventing_a_title():
    row,card=source()
    result=match_visible_metadata([dict(card,title='')],[row])
    assert result==[dict(video_id=row['video_id'],title=row['title'],visibility='private')]
