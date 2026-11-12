"""Data needing verification is different from deliberately excluded records."""
from collections import Counter
from creatorlab.hub import quality


def privacy_notice(count,platform='douyin'):
    name={'douyin':'抖音','bilibili':'B站'}.get(platform,'原平台')
    return f'有 {count} 条私密作品，当前无法获取数据。如需采集，请在{name}将作品改为公开，再回到CLab重新同步。'


def summary(rows):
    counts=Counter(quality(r) for r in rows)
    return dict(total=len(rows),analysable=counts['可分析'],excluded=counts['不可公开计量'],
                missing=counts['播放量缺失'],zero=counts['零播放待核实'],
                inconsistent=counts['播放量疑似异常'],
                pending=sum(counts[k] for k in ('播放量缺失','零播放待核实','播放量疑似异常')))


def inventory_audit(data):
    count=data.get('count',0);total=data.get('total');visible=data.get('visible_list_count')
    verified=bool(data.get('visible_list_ended') and visible==count and count>0 and data.get('rejected_rows',0)==0)
    gap=max(0,total-count) if isinstance(total,int) else None
    return dict(count=count,total=total,visible=visible,visible_verified=verified,external_gap=gap,
                platform_verified=isinstance(total,int) and count==total)


def inventory_message(data):
    audit=inventory_audit(data)
    if audit['external_gap'] and audit['visible_verified']:
        return f"可见清单已核对{audit['count']}条并显示到底；平台标称{audit['total']}条，仍有{audit['external_gap']}条无法从当前清单核实。已入库不等于全量采齐；不要把差额计入私密或删除数量。"
    if audit['external_gap']:return f"已识别{audit['count']}条，距平台标称总数仍差{audit['external_gap']}条，清单尚未核实完整。"
    return '作品清单数量已对齐。' if audit['platform_verified'] else '平台总数未知，无法判定全量完整。'
