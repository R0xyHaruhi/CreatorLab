import csv
import io
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from creatorlab.challenge import peer_result,work_result
from creatorlab.battlecard import profiles,render_card
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts,connect,accounts
from creatorlab.genres import set_genre
from creatorlab.content_analysis import frame
from creatorlab.challenge_import import preview,commit

PAIR=('生活区','校园生活')


def seed(db,values=(10,20,30,40,60)):
    init_hub(db);own=add_account(db,'bilibili','100','测试自己的账号')
    for number,(aid,value) in enumerate([(own,50)]+[(add_account(db,'bilibili',str(200+i),'测试参照'+str(i)),v) for i,v in enumerate(values)]):
        if number:
            with connect(db) as con:con.execute('UPDATE hub_accounts SET is_self=0 WHERE id=?',(aid,))
        for j in range(3):
            views=value*100
            metrics=dict(views=views,likes=value*value,comments=value*value,favorites=value*value,shares=value*value,coins=value*value)
            pid=upsert_post(db,aid,'验收样本'+str(j),str(aid)+'-'+str(j),'2026-09-01T00:00:00Z',metrics=metrics,observed_at='2026-10-02T00:00:00Z')
            set_genre(db,pid,*PAIR)
    rows=latest_posts(db,include_references=True)
    return frame([r for r in rows if r['account_id']==own]),frame([r for r in rows if r['account_id']!=own])


def test_real_creator_composite_and_one_vote_per_account(tmp_path):
    own,refs=seed(tmp_path/'d.db')
    a=peer_result(own,refs,'bilibili',PAIR,'30–89天')
    assert a['ready'] and a['n']==5 and a['percent']==80 and a['axes']==6
    prolific=pd.concat([refs,refs[refs.account_id==refs.account_id.iloc[0]]]*10,ignore_index=True)
    b=peer_result(own,prolific,'bilibili',PAIR,'30–89天')
    assert b['percent']==a['percent'] and b['n']==5


def test_ties_are_not_claimed_as_exceeded_and_sparse_never_publish(tmp_path):
    own,refs=seed(tmp_path/'d.db',(50,50,50,50,50))
    result=peer_result(own,refs,'bilibili',PAIR,'30–89天')
    assert result['ready'] and result['percent']==0 and result['tied']==5
    for changed in [refs[refs.account_id!=refs.account_id.iloc[0]],refs.assign(platform='douyin'),refs.assign(age_band='7–29天'),refs.assign(media_format='image')]:
        assert not peer_result(own,changed,'bilibili',PAIR,'30–89天')['ready']


def test_common_axes_only_and_unconfirmed_genre_not_used(tmp_path):
    own,refs=seed(tmp_path/'d.db')
    refs['coin_ratio']=None
    result=peer_result(own,refs,'bilibili',PAIR,'30–89天')
    assert result['axes']==5 and result['model']['scores'][-1]['score'] is None
    refs['genre']=[dict(g,origin='ai') for g in refs.genre]
    assert not peer_result(own,refs,'bilibili',PAIR,'30–89天')['ready']


def test_personal_percent_uses_works_and_excludes_self(tmp_path):
    own,_=seed(tmp_path/'d.db');models=profiles(own)
    result=work_result(own,own.iloc[0].to_dict(),models)
    assert result['ready'] and result['n']==2 and result['percent']==0 and result['unit']=='同组历史作品'


def dataset(creator='900'):
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=['creator_id','title','external_id','published_at','observed_at','url','views','likes','comments','favorites'])
    writer.writeheader()
    for i in range(3):writer.writerow(dict(creator_id=creator,title='外部作品'+str(i),external_id='BVtest'+str(i),published_at='2026-09-01T00:00:00Z',observed_at='2026-10-02T00:00:00Z',url='https://www.bilibili.com/video/BVtest'+str(i),views=100,likes=10,comments=3,favorites=5))
    return out.getvalue().encode()


def test_import_is_previewed_isolated_and_repeat_does_not_inflate(tmp_path):
    db=tmp_path/'d.db';init_hub(db);add_account(db,'bilibili','100')
    assert len(preview(db,dataset(),'bilibili'))==3 and len(accounts(db))==1
    commit(db,dataset(),'bilibili',PAIR);commit(db,dataset(),'bilibili',PAIR)
    assert not latest_posts(db) and len(latest_posts(db,include_references=True))==3
    assert [a['is_self'] for a in accounts(db)]==[1,0]
    with pytest.raises(ValueError,match='个人账号'):commit(db,dataset('100'),'bilibili',PAIR)


def test_import_failure_restores_database(tmp_path,monkeypatch):
    import creatorlab.challenge_import as module
    db=tmp_path/'d.db';init_hub(db);original=module.upsert_post;calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise OSError('模拟磁盘故障')
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'upsert_post',fail)
    with pytest.raises(OSError):commit(db,dataset(),'bilibili',PAIR)
    assert accounts(db)==[] and latest_posts(db,include_references=True)==[]


def test_peer_page_generates_export_and_safe_empty_state(tmp_path):
    db=tmp_path/'d.db';own,refs=seed(db)
    code='from creatorlab.personal_ui import hero\nfrom creatorlab.hub import latest_posts\nhero(latest_posts('+repr(str(db))+'))'
    app=AppTest.from_string(code,default_timeout=30).run()
    app.radio(key='battle_mode').set_value('同行挑战').run()
    assert not app.exception,[x.message for x in app.exception]
    assert len(app.get('download_button'))==1
    assert any('80' in x.proto.body and '对标创作者样本' in x.proto.body for x in app.get('html'))
    app.selectbox(key='challenge_age').set_value('0–6天').run()
    assert not app.exception and not any(x.key=='peer_share' for x in app.get('download_button'))


def test_selected_work_survives_peer_mode_and_shortcut_cycles(tmp_path):
    db=tmp_path/'d.db';own,_=seed(db)
    # New count-led shapes need three OTHER references, excluding the current work.
    aid=int(own.account_id.iloc[0])
    upsert_post(db,aid,'新增历史参照','extra','2026-09-01T00:00:00Z',metrics=dict(views=5000,likes=2500,comments=2500,favorites=2500,shares=2500,coins=2500),observed_at='2026-10-02T00:00:00Z')
    code='from creatorlab.personal_ui import hero\nfrom creatorlab.hub import latest_posts\nhero(latest_posts('+repr(str(db))+'))'
    app=AppTest.from_string(code,default_timeout=30).run()
    ids=sorted(own.id.tolist(),reverse=True)
    visited=[app.selectbox(key='hero_work').value]
    for _ in range(2):
        app.button(key='battle_next_ready').click().run();visited.append(app.selectbox(key='hero_work').value)
    assert len(set(visited))==3
    chosen=app.selectbox(key='hero_work').value
    app.radio(key='battle_mode').set_value('同行挑战').run()
    app.radio(key='battle_mode').set_value('作品战力').run()
    assert not app.exception and app.selectbox(key='hero_work').value==chosen


@pytest.mark.parametrize('replacement',[('https://www.bilibili.com/','https://example.com/'),('900','000900'),('2026-10-02T00:00:00Z','2026-08-01T00:00:00Z')])
def test_invalid_reference_never_changes_database(tmp_path,replacement):
    db=tmp_path/'d.db';init_hub(db)
    data=dataset().decode().replace(*replacement).encode()
    with pytest.raises(ValueError):commit(db,data,'bilibili',PAIR)
    assert not accounts(db)
