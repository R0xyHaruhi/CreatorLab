from datetime import datetime,timedelta,timezone
import pytest
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts


def test_drift_report_redacts_dynamic_keys_and_sensitive_endpoint():
    from creatorlab.collect_health import structure
    text=' '.join(structure({'data':{'user-secret@email.com':{'token-123456':'secret','play_count':3}}}))
    assert 'secret' not in text and 'email' not in text and 'play_count:int' in text


def test_decision_never_pools_same_named_accounts_or_private_works():
    from creatorlab.decision import summarize
    now=datetime.now(timezone.utc)
    rows=[dict(platform='douyin',account_id=i//12,account_name='同名',title='作品',views=10+i,published_at=(now-timedelta(days=30)).isoformat()) for i in range(24)]
    result=summarize(rows)
    assert not result['ready'] and result.get('reason')
    result=summarize([dict(r,visibility='private') for r in rows])
    assert result['stats']['used']==0


def test_external_approximate_counts_are_marked_and_same_titles_not_merged(tmp_path):
    from creatorlab.ext_platforms import import_csv,ext_posts
    db=tmp_path/'d.db';init_hub(db)
    import_csv(db,'weibo','A','标题,播放量\n重复标题,1.2万\n重复标题,200\n')
    rows=ext_posts(db);assert len(rows)==2
    assert next(r for r in rows if r['views']==12000)['approx_fields']==['views']
    import_csv(db,'weibo','A','标题,播放量\n重复标题,300\n')
    assert len(ext_posts(db))==3


def test_external_mapping_and_late_errors_do_not_partially_mutate(tmp_path):
    from creatorlab.ext_platforms import import_csv,ext_posts
    db=tmp_path/'d.db';init_hub(db)
    with pytest.raises(ValueError):import_csv(db,'weibo','A','title,views\na,1\n',{'title':'title','views':'title'})
    assert ext_posts(db)==[]


def test_analysis_only_mode_blocks_both_browser_launches(tmp_path,monkeypatch):
    from creatorlab.douyin_ui import launch
    from creatorlab.bilibili_ui import launch_import
    monkeypatch.setenv('CREATORLAB_ANALYSIS_ONLY','1')
    with pytest.raises(ValueError,match='容器模式'):launch(tmp_path/'d.db',tmp_path)
    with pytest.raises(ValueError,match='容器模式'):launch_import(tmp_path/'d.db',tmp_path,'123')


def test_real_insight_panel_renders_interval_charts(tmp_path):
    from streamlit.testing.v1 import AppTest
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'bilibili','123')
    for i in range(24):
        at=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=i,hours=12 if i%2 else 1)
        upsert_post(db,aid,'标题有问号？' if i%2 else '普通标题',str(i),at.isoformat(),metrics={'views':3000+i if i%2 else 1000+i},observed_at=(at+timedelta(days=7)).isoformat())
    code='from creatorlab.hub import latest_posts\nfrom creatorlab.insight_ui import panel\npanel(latest_posts('+repr(str(db))+'))'
    app=AppTest.from_string(code).run(timeout=30)
    assert not app.exception,[r.message for r in app.exception]
    assert len(app.get('plotly_chart'))>=2


def test_font_fallback_keeps_bundled_cjk_offline(monkeypatch,tmp_path):
    from creatorlab import battlecard
    monkeypatch.delenv('CLAB_FONT',raising=False)
    assert battlecard.BUNDLED_FONT.exists()
    assert battlecard.font(20).getlength('创作战力')>0
    monkeypatch.setattr(battlecard,'BUNDLED_FONT',tmp_path/'missing.otf')
    monkeypatch.setattr(battlecard,'FONT_FILES',())
    with pytest.raises(RuntimeError,match='中文字体'):battlecard.font_path()
