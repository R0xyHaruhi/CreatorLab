from creatorlab.storage import (init_db,add_video,list_rows,update_video,delete_video,add_experiment,update_experiment,add_feedback)
from creatorlab.ai import generate,AIError
import pytest


def test_video_crud(tmp_path):
    db=tmp_path/'sub'/'test.db'; init_db(db)
    row=dict(title='Test',role='A',format='transition',hook='face_closeup',duration_sec=18,publish_hour=19,views=100,likes=5,comments=1,shares=2,new_followers=3,published_at='',notes='')
    vid=add_video(db,row)
    assert list_rows(db,'videos')[0]['views']==100
    assert update_video(db,vid,{'views':250})
    assert list_rows(db,'videos')[0]['views']==250
    assert delete_video(db,vid)
    assert list_rows(db,'videos')==[]


def test_experiment_and_feedback(tmp_path):
    db=tmp_path/'test.db'; init_db(db)
    eid=add_experiment(db,'Opening','Closeup wins','wide','close','retention')
    assert update_experiment(db,eid,'completed','No clear difference')
    add_feedback(db,eid,'modify','Need more posts')
    assert list_rows(db,'experiments')[0]['status']=='completed'
    assert list_rows(db,'feedback')[0]['decision']=='modify'


def test_provider_none_and_invalid():
    assert 'no language model' in generate('none','task',{})
    with pytest.raises(AIError): generate('unknown','task',{})
