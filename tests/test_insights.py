from creatorlab.insights import describe,completeness,rate_for,actions,match_candidates
from creatorlab.hub import init_hub,accounts,latest_posts,auto_sync_douyin
from creatorlab.bridge import save_batch


def test_analysis_nulls_and_quantiles():
    rows=[{'id':1,'views':100,'likes':10,'completion_rate':0.3,'platform':'douyin','title':'A'},
          {'id':2,'views':None,'likes':30,'completion_rate':None,'platform':'douyin','title':'B'},
          {'id':3,'views':300,'likes':None,'completion_rate':.7,'platform':'douyin','title':'C'}]
    assert describe(rows,'views')['median']==200
    assert describe(rows,'views')['q1']==150
    assert completeness(rows)['views']=={'present':2,'total':3}
    assert rate_for(rows[0],'likes')==.1
    assert rate_for(rows[1],'likes') is None
    assert describe(rows,'completion_rate')['median']==.5


def test_insights_not_hallucinated():
    assert '0 条' in actions([])[0]['evidence']
    rows=[{'id':i,'title':str(i),'views':None,'likes':None,'platform':'douyin',
           'completion_rate':None,'bounce_rate_2s':None,'avg_view_second':None} for i in range(3)]
    result=actions(rows)
    assert all('100%' not in x['evidence'] for x in result)
    assert any('缺少' in x['detail'] for x in result)


def test_cross_platform_candidates_conservative():
    rows=[{'title':'凉宫春日 Cosplay #01','platform':'douyin','project_id':None},
          {'title':'凉宫春日 Cosplay #01','platform':'bilibili','project_id':None},
          {'title':'无关作品','platform':'douyin','project_id':None}]
    assert len(match_candidates(rows))==1


def test_auto_import_idempotent(tmp_path):
    db=tmp_path/'test.sqlite'
    init_hub(db)
    assert auto_sync_douyin(db)['available'] is False
    save_batch(db,{'rows':[{'video_id':'7377777777777777777','title':'真实视频标题',
                    'likes':12,'comments':2,'shares':1,'views':110,'completion_rate':0.42}]})
    result=auto_sync_douyin(db)
    assert result['processed']==1
    assert len(accounts(db))==1
    assert len(latest_posts(db))==1
    assert latest_posts(db)[0]['completion_rate']==.42
    assert auto_sync_douyin(db)['processed']==0
