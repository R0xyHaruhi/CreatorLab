from creatorlab.sync_browser import parse_work_list, normalize_item


def test_work_list_preserves_large_video_id():
    raw='{"data":{"items":[{"id":7412345678901234567,"description":"测试视频","create_time":1720000000,"metrics":{"like_count":18,"completion_rate":0.251,"bounce_rate_2s":0.28}}],"total":292,"has_more":1}}'
    result=parse_work_list(raw)
    assert result['total']==292
    assert result['rows'][0]['video_id']=='7412345678901234567'
    assert result['rows'][0]['completion_rate']==0.251
    assert result['rows'][0]['likes']==18
    assert result['rows'][0]['views'] is None


def test_nested_payload_and_invalid():
    assert parse_work_list('{"data":{"data":{"items":[],"total":0}}}')['rows']==[]
    assert parse_work_list('not json') is None
    assert parse_work_list('{"foo":123}') is None


def test_missing_metrics_not_invented():
    d=normalize_item({'id':'1234567890123456789','description':'作品','metrics':{}})
    assert d['views'] is None
    assert d['completion_rate'] is None
    assert normalize_item({'id':'abc'}) is None


def test_status_write_retries_windows_reader_lock_and_preserves_old_on_failure(tmp_path,monkeypatch):
    import json
    import pytest
    import creatorlab.sync_browser as sync
    dest=tmp_path/'status.json';sync.status_write(dest,state='starting')
    replace=sync.os.replace;calls=[]
    def busy_then_replace(src,target):
        calls.append(1)
        if len(calls)<3:raise PermissionError('temporary reader lock')
        return replace(src,target)
    monkeypatch.setattr(sync.os,'replace',busy_then_replace)
    monkeypatch.setattr(sync.time,'sleep',lambda _:None)
    sync.status_write(dest,state='completed')
    assert len(calls)==3 and json.loads(dest.read_text())['state']=='completed'
    def busy(*a):raise PermissionError('persistent reader lock')
    monkeypatch.setattr(sync.os,'replace',busy)
    with pytest.raises(PermissionError):sync.status_write(dest,state='error')
    assert json.loads(dest.read_text())['state']=='completed' and not list(tmp_path.glob('*.tmp'))
