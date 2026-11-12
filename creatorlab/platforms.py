"""Separate platform products share storage infrastructure, never metric meanings."""
COMMON=[('views','播放'),('likes','点赞'),('comments','评论'),('shares','分享'),('favorites','收藏')]
EXTRAS={
 'bilibili':[('coins','投币'),('danmaku','弹幕')],
 'douyin':[('completion_rate','完播率'),('completion_rate_5s','5秒完播率'),('bounce_rate_2s','2秒跳出率'),('avg_view_second','平均观看秒数')]}
FEEDBACK={
 'bilibili':['like_ratio','comment_ratio','favorite_ratio','share_ratio','coin_ratio','danmaku_ratio'],
 'douyin':['like_ratio','comment_ratio','favorite_ratio','share_ratio','completion_rate','bounce_rate_2s']}


def goals(platform):
    from creatorlab.review import GOALS
    result={k:v for k,v in GOALS.items() if v[0] in ['views']+FEEDBACK[platform]}
    result['让观众更愿意讨论']=('comment_ratio','评论比例','越高通常越好')
    if platform=='bilibili':result['让观众更愿意发弹幕']=('danmaku_ratio','弹幕比例','越高通常越好')
    return result
