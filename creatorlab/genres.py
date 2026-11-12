"""CLab editorial taxonomy, not a claim to mirror official platform partitions."""
import json
from collections import Counter
from creatorlab.hub import connect,utcnow

TAXONOMY={
'bilibili':{
 '生活区':['日常Vlog','校园生活','职场生活','旅行记录','家居收纳','宠物日常','生活经验'],
 '游戏区':['游戏直播回放','直播切片','游戏资讯','攻略教学','实况解说','操作高光','剧情考据','游戏测评','电竞赛事'],
 '动漫区':['动画解说','番剧评论','剧情考据','MAD与混剪','原创动画','COS与角色扮演','同人创作'],
 '知识区':['科学科普','人文社科','学习方法','职业技能','财经知识','环境与自然'],
 '科技区':['数码测评','软件教程','AI应用','编程开发','硬件DIY'],
 '美食区':['制作教程','探店测评','饮食记录','食品科普'],
 '时尚区':['穿搭','美妆教程','护肤测评','服装改造'],
 '音乐区':['翻唱','原创音乐','乐器演奏','音乐评论'],
 '舞蹈区':['宅舞','街舞','编舞展示','舞蹈教学'],
 '运动区':['足球','篮球','健身训练','户外运动','赛事评论'],
 '影视区':['影视解说','影视评论','影视混剪','短剧创作'],
 '动物与自然区':['动物科普','野生动物记录','自然观察','环保实践'],
 '鬼畜区':['鬼畜调教','人力VOCALOID','音MAD','鬼畜教程'],
 '汽车区':['车辆测评','用车经验','汽车文化'],
 '其他区':['待细分内容']},
'douyin':{
 '生活':['日常Vlog','校园生活','职场生活','家庭记录','家居收纳'],
 '游戏':['游戏直播回放','直播切片','游戏资讯','攻略教学','操作高光','搞笑游戏','电竞赛事'],
 '二次元':['COS变装','COS剧情','角色日常','动漫解说','动漫混剪','同人创作'],
 '知识':['科学科普','人文社科','学习方法','职场技能','环境与自然'],
 '科技数码':['数码测评','AI应用','软件技巧','编程开发'],
 '美食':['烹饪教程','探店测评','饮食日常','美食挑战'],
 '美妆穿搭':['穿搭分享','美妆教程','护肤测评','造型变装'],
 '音乐舞蹈':['翻唱','原创音乐','乐器演奏','舞蹈展示','舞蹈教学'],
 '搞笑剧情':['情景短剧','生活段子','剧情反转','配音创作'],
 '运动健身':['足球','篮球','健身训练','户外运动','赛事解说'],
 '旅行':['城市漫游','旅行攻略','风景记录','户外探险'],
 '萌宠':['宠物日常','宠物训练','动物科普'],
 '三农':['乡村生活','农业知识','农产品记录','乡村美食'],
 '汽车':['车辆测评','用车经验','汽车文化'],
 '摄影剪辑':['拍摄教程','剪辑教程','后期调色','摄影作品'],
 '亲子家庭':['亲子日常','育儿经验','家庭活动'],
 '其他':['待细分内容']}}
KEYWORDS={
 '游戏直播回放':['直播录像','完整直播'],'直播切片':['直播切片','直播精华'],'游戏资讯':['游戏资讯','版本更新','新赛季'],
 '攻略教学':['游戏攻略','通关','上分','配装'],'COS与角色扮演':['cos','变装','出片'],
 'COS变装':['cos','变装','出片'],'番剧评论':['番剧','新番','追番'],
 '环境与自然':['环境保护','气候变化','生态','冰川'],'AI应用':['人工智能','大模型','chatgpt','ai工具'],
 '校园生活':['大学日常','校园','宿舍'],'制作教程':['菜谱','做法','烹饪'],
 '烹饪教程':['菜谱','做法','烹饪'],'足球':['足球','曼城','英超'],'宠物日常':['猫咪','狗狗','宠物'],
 '科学科普':['科普','科学原理'],'编程开发':['python','编程','代码'],'旅行记录':['旅行','旅游'],
 '旅行攻略':['旅行攻略','旅游攻略'],'护肤测评':['护肤','防晒测评'],'翻唱':['翻唱','cover演唱']}


def init_genres(db):
    with connect(db) as con:
        con.executescript('''CREATE TABLE IF NOT EXISTS hub_genres(
           post_id INTEGER PRIMARY KEY REFERENCES hub_posts(id),major TEXT NOT NULL,minor TEXT NOT NULL,
           origin TEXT NOT NULL,confidence REAL NOT NULL,evidence TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hub_account_genres(
           account_id INTEGER PRIMARY KEY REFERENCES hub_accounts(id),major TEXT NOT NULL,minor TEXT NOT NULL);''')


def valid_genre(platform,major,minor):return minor in TAXONOMY.get(platform,{}).get(major,[])


def suggest_title(platform,title):
    hits=[];text=str(title).lower()
    for major,minors in TAXONOMY[platform].items():
        for minor in minors:
            matched=[k for k in KEYWORDS.get(minor,[]) if k.lower() in text]
            if matched:hits.append(dict(major=major,minor=minor,confidence=.6,evidence='、'.join(matched)))
    if len(hits)!=1:return None  # ambiguous titles should not become definitive labels
    return hits[0]


def set_genre(db,post_id,major,minor,origin='manual',confidence=1.,evidence='用户确认'):
    init_genres(db)
    with connect(db) as con:
        post=con.execute('SELECT a.platform,p.title FROM hub_posts p JOIN hub_accounts a ON p.account_id=a.id WHERE p.id=?',(post_id,)).fetchone()
        if not post or not valid_genre(post['platform'],major,minor):raise ValueError('所选赛道不属于这个平台')
        old=con.execute('SELECT origin FROM hub_genres WHERE post_id=?',(post_id,)).fetchone()
        if old and old['origin']=='manual' and origin!='manual':return False
        if old and old['origin']=='platform_metadata' and origin in ('ai','title_rule'):return False
        if origin not in ('manual','ai','title_rule','platform_metadata'):raise ValueError('未知分类来源')
        if not 0<=float(confidence)<=1:raise ValueError('置信度需要在0–1之间')
        con.execute('INSERT OR REPLACE INTO hub_genres VALUES(?,?,?,?,?,?,?)',(post_id,major,minor,origin,confidence,str(evidence)[:500],utcnow()))
    return True


def genre_rows(db,rows):
    init_genres(db)
    with connect(db) as con:labels={r['post_id']:dict(r) for r in con.execute('SELECT * FROM hub_genres')}
    return [dict(r,genre=labels.get(r['id'])) for r in rows]


def verticality(rows):
    labels=[r['genre'] for r in rows if r.get('genre') and r['genre']['confidence']>=.6]
    counts=Counter((g['major'],g['minor']) for g in labels)
    key,n=counts.most_common(1)[0] if counts else ((None,None),0)
    return dict(major=key[0],minor=key[1],labelled=len(labels),total=len(rows),coverage=len(labels)/len(rows) if rows else 0,
       share=n/len(labels) if labels else None,counts=counts)


def apply_ai_labels(db,platform,rows,answer):
    payload=json.loads(answer.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
    if not isinstance(payload,dict) or not isinstance(payload.get('labels'),list):raise ValueError('AI返回格式不正确')
    allowed={r['id']:r for r in rows};saved=0
    for item in payload['labels'][:len(rows)]:
        if not isinstance(item,dict):continue
        row=allowed.get(item.get('id'));quote=str(item.get('evidence',''))
        if not row or not quote or quote not in row['title'] or not valid_genre(platform,item.get('major'),item.get('minor')):continue
        try:saved+=bool(set_genre(db,row['id'],item['major'],item['minor'],'ai',float(item.get('confidence',0)),quote))
        except (ValueError,TypeError):continue
    return saved

LEGACY_TRACK={"生活区":"生活 / Vlog","生活":"生活 / Vlog","游戏区":"游戏","游戏":"游戏","动漫区":"COS / 动漫","二次元":"COS / 动漫","知识区":"知识科普","知识":"知识科普","科技区":"知识科普","科技数码":"知识科普","美食区":"美食","美食":"美食","时尚区":"美妆 / 穿搭","美妆穿搭":"美妆 / 穿搭"}
