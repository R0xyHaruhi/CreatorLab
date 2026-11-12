"""Build the first completed 100-issue bundle, without personal data or network."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creatorlab.weekly_reference import normalize_tag


def build(source, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
        src.row_factory = sqlite3.Row
        src.execute('BEGIN')
        coverage = src.execute('SELECT * FROM issue_collection_coverage WHERE issue_number BETWEEN 292 AND 391').fetchall()
        if {r['issue_number'] for r in coverage} != set(range(292, 392)):
            raise ValueError('需要完整的第292—391期处理记录')
        status = src.execute('SELECT issue,bvid,status FROM public_html_collection WHERE issue BETWEEN 292 AND 391').fetchall()
        if len(status) != sum(r['visible_link_count'] for r in coverage):
            raise ValueError('作品清单与处理记录不一致')
        accepted = {r['bvid'] for r in status if r['status'] == 'collected'}
        rejected = [r for r in status if r['status'] != 'collected']
        if any(r['status'] not in ('video_not_found', 'bangumi_series_not_comparable', 'redirected_to_homepage') for r in rejected):
            raise ValueError('仍有未经复核的采集缺口')
        temporary = output.with_suffix('.building')
        if temporary.exists():
            temporary.unlink()
        with closing(sqlite3.connect(temporary)) as dst:
            dst.executescript('''
            PRAGMA foreign_keys=ON;
            PRAGMA user_version=1;
            CREATE TABLE sample_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE sample_videos(bvid TEXT PRIMARY KEY,title TEXT NOT NULL,published_at TEXT,duration_seconds REAL,
                observed_at TEXT NOT NULL,source_url TEXT NOT NULL,views INTEGER,likes INTEGER,comments INTEGER,
                favorites INTEGER,shares INTEGER,coins INTEGER,danmaku INTEGER);
            CREATE TABLE sample_memberships(bvid TEXT REFERENCES sample_videos(bvid),issue INTEGER,PRIMARY KEY(bvid,issue));
            CREATE TABLE sample_tags(bvid TEXT REFERENCES sample_videos(bvid),tag TEXT,normalized TEXT,PRIMARY KEY(bvid,tag));
            CREATE INDEX idx_sample_tags_normalized ON sample_tags(normalized);
            CREATE TABLE sample_precision(bvid TEXT REFERENCES sample_videos(bvid),metric TEXT,displayed_value TEXT,precision TEXT,
                PRIMARY KEY(bvid,metric));
            CREATE TABLE sample_issues(issue INTEGER PRIMARY KEY,label TEXT,subject TEXT,source_url TEXT,visible INTEGER,collected INTEGER);
            CREATE TABLE sample_exclusions(issue INTEGER,bvid TEXT,status TEXT,PRIMARY KEY(issue,bvid));
            ''')
            observed = []
            for bvid in sorted(accepted):
                video = src.execute('SELECT * FROM reference_videos WHERE bvid=?', (bvid,)).fetchone()
                snap = src.execute('SELECT * FROM reference_snapshots WHERE bvid=? ORDER BY julianday(observed_at) DESC,observed_at DESC LIMIT 1', (bvid,)).fetchone()
                if not snap or snap['views'] is None:
                    raise ValueError('成功记录缺少播放快照：' + bvid)
                observed.append(snap['observed_at'])
                dst.execute('INSERT INTO sample_videos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (bvid, video['title'], video['published_at'], video['duration_seconds'], snap['observed_at'],
                     snap['source_url'], snap['views'], snap['likes'], snap['replies'], snap['favorites'], snap['shares'], snap['coins'], snap['danmaku']))
                for issue, in src.execute('SELECT issue_number FROM weekly_memberships WHERE bvid=? AND issue_number BETWEEN 292 AND 391', (bvid,)):
                    dst.execute('INSERT INTO sample_memberships VALUES(?,?)', (bvid, issue))
                for tag, in src.execute('SELECT DISTINCT tag FROM reference_video_tags WHERE bvid=?', (bvid,)):
                    dst.execute('INSERT INTO sample_tags VALUES(?,?,?)', (bvid, tag, normalize_tag(tag)))
                for p in src.execute('SELECT metric,displayed_value,precision FROM metric_provenance WHERE bvid=? AND observed_at=?', (bvid, snap['observed_at'])):
                    dst.execute('INSERT INTO sample_precision VALUES(?,?,?,?)', (bvid, 'comments' if p['metric'] == 'replies' else p['metric'], p['displayed_value'], p['precision']))
            for r in coverage:
                issue = src.execute('SELECT * FROM weekly_issues WHERE issue_number=?', (r['issue_number'],)).fetchone()
                dst.execute('INSERT INTO sample_issues VALUES(?,?,?,?,?,?)', (r['issue_number'], issue['label'], issue['subject'], issue['source_url'], r['visible_link_count'], r['collected_video_count']))
            dst.executemany('INSERT INTO sample_exclusions VALUES(?,?,?)', [tuple(r) for r in rejected])
            info = dict(id='bilibili-weekly-292-391-v1', platform='bilibili', scope='每周必看精选样本',
                        issue_min=292, issue_max=391, issues=100, entries=len(status), videos=len(accepted),
                        exclusions=len(rejected), exclusion_reasons={s: sum(r['status'] == s for r in rejected) for s in sorted({r['status'] for r in rejected})},
                        tagged_videos=dst.execute('SELECT COUNT(DISTINCT bvid) FROM sample_tags').fetchone()[0],
                        observed_from=min(observed), observed_to=max(observed),
                        counter_window='采集时累计值，非入选当周数据', is_sitewide=False)
            dst.execute('INSERT INTO sample_metadata VALUES(?,?)', ('dataset', json.dumps(info, ensure_ascii=False)))
            dst.commit()
            assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not dst.execute('PRAGMA foreign_key_check').fetchall()
        temporary.replace(output)
        output.with_suffix('.json').write_text(json.dumps(dict(info, sha256=hashlib.sha256(output.read_bytes()).hexdigest()), ensure_ascii=False, indent=2), encoding='utf-8')
    return info


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1] / 'assets/references/bilibili_weekly_100.sqlite3'))
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), ensure_ascii=False))
