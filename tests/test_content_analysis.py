import io
import pytest
from PIL import Image
from creatorlab.hub import init_hub,add_account,upsert_post,latest_posts,import_csv,connect
from creatorlab.content_analysis import annotate,frame,recommendations,group_summary
from creatorlab.covers import extract_cover,save_cover,cached_cover


def test_labels_survive_metric_sync_and_old_db(tmp_path):
    db=tmp_path/'d.db';init_hub(db);aid=add_account(db,'douyin','me')
    pid=upsert_post(db,aid,'作品','1234567890123456789',metrics={'views':100})
    annotate(db,pid,'COS / 动漫','变装','长门有希',18)
    upsert_post(db,aid,'作品','1234567890123456789',metrics={'views':200})
    init_hub(db)
    row=latest_posts(db)[0]
    assert (row['category'],row['topic'],row['duration_seconds'],row['views'])==('变装','长门有希',18,200)
    import_csv(db,aid,'title,external_id,views,category,track,duration_seconds\n视频2,1234567890123456780,100,剧情,COS / 动漫,30\n')
    assert latest_posts(db)[0]['category']=='剧情'


def sample(account=1,platform='douyin'):
    rows=[]
    for category,views,bounce in [('变装',2000,.2),('剧情',1000,.4)]:
        for i in range(5):
            rows.append(dict(id=len(rows),account_id=account,account_name='me',platform=platform,category=category,track='COS / 动漫',views=views,likes=10,bounce_rate_2s=bounce,title=category+str(i),published_at='2026-01-01T00:00:00Z',metric_recorded_at='2026-01-10T00:00:00Z'))
    return rows


def test_cohorts_missing_and_metric_direction():
    df=frame(sample())
    assert df.age_band.unique().tolist()==['7–29天']
    assert df.publish_hour.unique().tolist()==['08–11时']
    assert df.favorite_ratio.isna().all()
    assert df.relative_views.iloc[0]==pytest.approx(2000/1500)
    assert '变装' in recommendations(df,'COS / 动漫','views')[0]['title']
    assert '变装' in recommendations(df,'COS / 动漫','bounce_rate_2s')[0]['title']
    assert recommendations(df,'COS / 动漫','favorite_ratio')==[]
    assert recommendations(df.iloc[:7],'COS / 动漫','views')==[]
    split=sample()
    for r in split[5:]:r['account_id']=2
    assert recommendations(frame(split),'COS / 动漫','views')==[]
    split=sample()
    for r in split[5:]:r['published_at']='2025-01-01'
    assert recommendations(frame(split),'COS / 动漫','views')==[]


def test_covers_nested_and_persistent_bytes(tmp_path):
    url='https://example.org/cover.jpg'
    assert extract_cover({'video':{'cover':{'url_list':[None,url]}}})==url
    assert extract_cover({'cover':'javascript:bad'}) is None
    db=tmp_path/'d.db';init_hub(db)
    img=io.BytesIO();Image.new('RGB',(100,160),'blue').save(img,format='PNG')
    save_cover(db,'douyin','1234567890123456789',img.getvalue(),'test')
    assert cached_cover(db,'douyin','1234567890123456789').startswith(b'\xff\xd8')
    assert cached_cover(db,'douyin','other') is None
    with pytest.raises(ValueError):save_cover(db,'douyin','123',b'bad','test')
