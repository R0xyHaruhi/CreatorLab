import io
import json
from datetime import date
from types import SimpleNamespace
import pandas as pd
import pytest
from PIL import Image
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts
from creatorlab.content_analysis import frame
from creatorlab.growth import radar_scores,save_experiment,experiments,update_experiment
from creatorlab.genres import set_genre,genre_rows,verticality,apply_ai_labels,suggest_title
from creatorlab.peers import save_peer,peer_rows,comparable
from creatorlab.covers import fetch_browser_cover,cached_cover


def fixture_rows(db):
    init_hub(db);aid=add_account(db,'bilibili','123')
    for i in range(5):upsert_post(db,aid,'Python编程教程'+str(i),'BV'+str(i).zfill(10),'2026-01-01',metrics={'views':100*(i+1),'likes':10,'comments':2,'favorites':1,'shares':1})
    return latest_posts(db)


def test_radar_ties_missing_axes_and_no_automatic_age_filter(tmp_path):
    rows=fixture_rows(tmp_path/'d.db');df=frame(rows);r=df.iloc[0].to_dict()
    scores=radar_scores(df,r);assert len(scores)==6
    assert next(x for x in scores if x['metric']=='coin_ratio')['score'] is None
    assert next(x for x in scores if x['metric']=='views')['score']==90
    flat=df.copy();flat['views']=100
    assert radar_scores(flat,flat.iloc[0].to_dict())[0]['score']==50
    df.loc[df.index[1:],'age_band']='7–29天'
    assert radar_scores(df,r)[0]['score']==90


def test_manual_genres_are_not_overwritten_by_ai(tmp_path):
    db=tmp_path/'d.db';rows=fixture_rows(db);r=rows[0]
    set_genre(db,r['id'],'科技区','编程开发')
    answer=json.dumps({'labels':[{'id':r['id'],'major':'生活区','minor':'日常Vlog','confidence':.9,'evidence':'Python'}]})
    assert apply_ai_labels(db,'bilibili',rows,answer)==0
    assert genre_rows(db,rows)[0]['genre']['minor']=='编程开发'
    bad=json.dumps({'labels':[{'id':rows[1]['id'],'major':'科技区','minor':'编程开发','confidence':.9,'evidence':'不存在的标题内容'}]})
    assert apply_ai_labels(db,'bilibili',rows,bad)==0
    with pytest.raises(ValueError):set_genre(db,r['id'],'科技数码','AI应用')
    v=verticality(genre_rows(db,rows));assert v['coverage']==.2 and v['share']==1
    assert suggest_title('bilibili','Python代码教程')['minor']=='编程开发'


def test_ai_peer_numbers_cannot_become_benchmarks(tmp_path):
    db=tmp_path/'d.db';fixture_rows(db)
    save_peer(db,'bilibili','候选','https://space.bilibili.com/999','科技区','编程开发','ai_unverified',data={'followers':999999})
    row=peer_rows(db,'bilibili','科技区','编程开发')[0]
    assert row['data']=={} and not comparable(row,'7–29天')
    save_peer(db,'bilibili','用户确认','https://space.bilibili.com/999','科技区','编程开发',data={'sample_n':5,'age_band':'7–29天','observed_at':date.today().isoformat(),'source_url':'https://space.bilibili.com/999','views':200})
    assert not save_peer(db,'bilibili','AI覆盖','https://space.bilibili.com/999','科技区','编程开发','ai_unverified')
    row=peer_rows(db,'bilibili','科技区','编程开发')[0]
    assert comparable(row,'7–29天') and not comparable(row,'90天以上')
    with pytest.raises(ValueError):save_peer(db,'bilibili','bad','http://127.0.0.1/','科技区','编程开发')


def test_persistent_challenge_is_user_reviewed(tmp_path):
    db=tmp_path/'d.db';rows=fixture_rows(db);aid=rows[0]['account_id']
    eid=save_experiment(db,aid,'试试新开头','第一秒展示结果','completion_rate')
    assert experiments(db,aid)[0]['stage']=='计划中'
    update_experiment(db,eid,'已复盘','下一条继续测试')
    assert experiments(db,aid)[0]['note']=='下一条继续测试'
    with pytest.raises(ValueError):update_experiment(db,eid,'保证爆款','')


def test_cover_loader_rejects_untrusted_hosts_and_caches_real_bytes(tmp_path):
    db=tmp_path/'d.db';init_hub(db);opened=[]
    assert not fetch_browser_cover(SimpleNamespace(new_page=lambda:opened.append(1)),db,'bilibili','BVx','https://127.0.0.1/private')
    assert not opened
    raw=io.BytesIO();Image.new('RGB',(120,160),'blue').save(raw,format='PNG')
    request=SimpleNamespace(get=lambda *a,**k:SimpleNamespace(status=200,headers={'content-type':'image/png'},body=lambda:raw.getvalue(),dispose=lambda:None))
    assert fetch_browser_cover(SimpleNamespace(request=request,new_page=lambda:pytest.fail('cover must not create a page')),db,'bilibili','BVx','https://i0.hdslb.com/cover.jpg')
    assert cached_cover(db,'bilibili','BVx').startswith(b'\xff\xd8')


def test_reference_accounts_never_pollute_own_dashboard(tmp_path):
    from creatorlab.reference_import import prepare_reference
    db=tmp_path/'d.db';own=fixture_rows(db)
    with pytest.raises(ValueError):prepare_reference(db,'123')
    prepare_reference(db,'999')
    from creatorlab.bilibili_import import persist,normalize
    persist(db,'999',normalize({'bvid':'BV1xx411c7mD','title':'参照作品','play':9999}))
    assert len(latest_posts(db))==5
    assert len(latest_posts(db,include_references=True))==6
