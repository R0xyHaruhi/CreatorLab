import json
from streamlit.testing.v1 import AppTest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.content_analysis import frame
from creatorlab.workspace_overview import summary,distribution
from creatorlab.genres import set_genre


def seed(db,n=203):
    init_hub(db);aid=add_account(db,'douyin','me')
    for i in range(n):upsert_post(db,aid,'作品'+str(i),str(7412345678901000000+i),metrics={'views':100+i})


def test_only_plays_still_have_exact_summary_and_distribution(tmp_path):
    db=tmp_path/'d.db';seed(db,5);df=frame(latest_posts(db))
    assert summary(df)=={'count':5,'total':510.,'median':102.,'maximum':104.}
    fig=distribution(df,df.id.iloc[0]).to_plotly_json()
    assert fig['data'][0]['y']==[0,5,0,0,0]


def test_203_legacy_posts_render_three_useful_views_without_fake_radar(tmp_path):
    db=tmp_path/'d.db';seed(db)
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nfrom creatorlab.hub import latest_posts\nhero(latest_posts('+repr(str(db))+'))',default_timeout=45).run()
    assert not app.exception,[e.message for e in app.exception]
    assert any(m.label=='已入库作品' and m.value=='203' for m in app.metric)
    data=[t for c in app.get('plotly_chart') for t in json.loads(c.proto.spec).get('data',[])]
    assert sum(t['type']=='bar' for t in data)==2
    assert sum(t['type']=='heatmap' for t in data)==1
    assert not any(t['type']=='scatterpolar' for t in data)
    assert not app.get('download_button')


def test_confirmed_classification_unlocks_comparison_instead_of_blank_panel(tmp_path):
    db=tmp_path/'d.db';seed(db,6)
    for i,row in enumerate(latest_posts(db)):set_genre(db,row['id'],'生活','校园生活' if i%2 else '职场生活')
    app=AppTest.from_string('from creatorlab.personal_ui import hero\nfrom creatorlab.hub import latest_posts\nhero(latest_posts('+repr(str(db))+'))').run()
    assert not app.exception,[e.message for e in app.exception]
    assert any('分类表现对比' in m.value for m in app.markdown)
    assert any('积累时间未对齐' in c.value for c in app.caption)
