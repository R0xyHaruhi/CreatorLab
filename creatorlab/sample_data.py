"""Ephemeral, visibly labelled examples; never inserted into a user's database."""


def sample_rows(platform):
    titles=['开头先放成片','一段制作过程','完整故事版本','同主题的第二次尝试','剪辑节奏实验','保留环境声的版本']
    views=[8200,2300,4600,12500,6100,3400]
    rows=[]
    for i,(title,view) in enumerate(zip(titles,views)):
        rows.append(dict(id=-(i+1),account_id=-1,account_name='示例账号',platform=platform,title='示例数据 · '+title,
          external_id='demo-'+str(i),visibility='public',views=view,likes=[580,130,410,950,430,210][i],comments=[42,12,38,76,31,20][i],
          favorites=[180,70,280,390,160,98][i],shares=[44,19,68,120,39,27][i],coins=[85,24,65,140,72,32][i] if platform=='bilibili' else None,
          completion_rate=[.42,.31,.58,.53,.48,.36][i] if platform=='douyin' else None,
          published_at='2026-01-01T00:00:00Z',metric_recorded_at='2026-02-01T00:00:00Z',category='成片展示' if i%2 else '过程记录',project_id=None,project_name=None,
          duration_seconds=30+i*4))
    return rows
