import json
from creatorlab.hub import init_hub
from creatorlab.sync_browser import parse_work_list
from creatorlab.collect_health import (find_item_container, structure, metric_hints, record_unparsed,
    assess_rows, recent_drift, export_report)

RENAMED='{"data":{"list":[{"aweme_id":"7412345678901234567","desc":"测试","statistics":{"play_count":9,"like_count":2}}],"total":1,"has_more":0}}'


def test_renamed_list_is_detectable_but_not_silently_ingested():
    assert parse_work_list(RENAMED) is None
    parent,key,items=find_item_container(json.loads(RENAMED))
    assert key=='list' and len(items)==1


def test_unrelated_json_is_not_mistaken_for_a_list():
    assert parse_work_list('{"data":{"tags":[{"name":"a"},{"name":"b"}]}}') is None
    assert parse_work_list('{"data":{"codes":[{"id":"12"},{"id":"34"}]}}') is None  # ids too short


def test_container_prefers_largest_list():
    obj={'a':{'rows':[{'id':'12345678901'}]},'b':{'rows':[{'id':'12345678901'},{'id':'12345678902'}]}}
    parent,key,found=find_item_container(obj)
    assert key=='rows' and len(found)==2


def test_structure_has_no_values():
    paths=structure(json.loads(RENAMED))
    text=' '.join(paths)
    assert 'data.list[].statistics.play_count:int' in paths
    assert '测试' not in text and '7412345678901234567' not in text
    assert 'data.list[].statistics.play_count:int' in metric_hints(paths)


def test_record_unparsed_dedupes_and_exports_without_values(tmp_path):
    db=tmp_path/'d.db';init_hub(db)
    raw='{"weird":{"entries":[{"vid":"x","plays":123456}]}}'
    assert record_unparsed(db,'douyin','/a/work_list/?token=secret',raw) is True
    assert record_unparsed(db,'douyin','/a/work_list/?token=secret',raw) is False
    assert record_unparsed(db,'douyin','/x','not json') is None
    rec=recent_drift(db,'douyin')
    assert len(rec)==1 and '?' not in rec[0]['endpoint']
    out=export_report(db)
    assert 'secret' not in out and '123456' not in out and '<unknown-key>.entries[].plays:int' in out


def test_assess_rows_flags_missing_columns():
    assert assess_rows([])[0]['level']=='error'
    rows=[{'views':1,'likes':None,'comments':None} for _ in range(6)]
    msgs={i['field']:i['level'] for i in assess_rows(rows,fields=('views','likes'))}
    assert msgs=={'likes':'warn'}
    assert assess_rows(rows[:3])==[]  # too few rows to judge
