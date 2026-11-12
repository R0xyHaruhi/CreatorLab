"""A shareable visual identity built from measured per-axis historical positions."""
import io
import math
from functools import lru_cache
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import pandas as pd
from creatorlab.growth import radar_scores

ARCHETYPES={'触达':'触达先锋','喜欢':'人气磁场','讨论':'话题引擎','收藏':'收藏宝藏','传播':'分享引力','投币支持':'投币共鸣','留住观众':'留人高手','阅读深度':'图文引力'}
TESTS={
 'avg_image_views':'下一条保持图片张数相近，把最有吸引力的图片前置，观察平均浏览图片数和分享变化。',
 'image_depth':'下一条保持图片张数相近，调整图片顺序与衔接，观察阅读深度和收藏变化。',
 'views':'下一条试着让封面只表达一个看点，观察同一窗口的播放变化。',
 'like_ratio':'下一条把最有共鸣的一幕提前，观察点赞与播放的比例。',
 'comment_ratio':'下一条结尾提出一个容易回答的问题，观察评论与播放的比例。',
 'favorite_ratio':'下一条加入一段值得反复查看的清单或做法，观察收藏与播放的比例。',
 'share_ratio':'下一条试着围绕一个具体人群的共同经历创作，观察分享与播放的比例。',
 'coin_ratio':'下一条更清楚地展示你的原创过程，观察投币与播放的比例。',
 'completion_rate':'下一条把结果先展示出来，再展开过程，观察完播变化。'}


def profile(df,row):
    scores=radar_scores(df,row,min_n=3)
    return profile_from_scores(scores)


def profile_from_scores(scores):
    usable=[s for s in scores if s['score'] is not None]
    ready=len(usable)>=3
    high=max(usable,key=lambda s:s['score']) if usable else None
    low=min(usable,key=lambda s:s['score']) if usable else None
    balanced=bool(usable) and len({s['score'] for s in usable})==1
    archetype='均衡探索型' if balanced else ARCHETYPES.get(high['axis'],'成长探索型') if high else '正在解锁'
    n=min((s['n'] for s in usable),default=0)
    return {'scores':scores,'ready':ready,'archetype':archetype,'high':high,'low':low,
      'sample_n':n,'exploratory':n<5,'available':len(usable),
      'next_test':TESTS.get(low['metric'],'下一条只改变一处内容，同时观察播放和互动数量的变化。') if low and not balanced else '下一条保留这次最喜欢的一处做法，换一个选题，观察它能否再次奏效。'}


def profiles(df):
    """Rank each comparable cohort once rather than scanning all works per card."""
    from creatorlab.growth import AXES
    if df.empty:return {}
    data=df.copy()
    if 'analysis_window' in data:
        windows=data.analysis_window.fillna('当前累计').replace('','当前累计')
        data['_scope']=windows.where(windows!='当前累计',data.age_band)
    else:data['_scope']=data.age_band
    data['media_format']=data.get('media_format',pd.Series('unknown',index=data.index)).fillna('unknown')
    result={}
    for _,group in data.groupby(['account_id','platform','_scope','media_format'],dropna=False):
        rows=group.to_dict('records');axis_data=[]
        for label,key in AXES[rows[0]['platform']]:
            values=group[key] if key in group else pd.Series(index=group.index,dtype=float)
            n=int(values.notna().sum());ranks=100*(values.rank(method='average')-.5)/n if n else values
            axis_data.append((label,key,values,ranks,n))
        for index,row in zip(group.index,rows):
            scores=[]
            for label,key,values,ranks,n in axis_data:
                value=values.loc[index];usable=n>=3 and pd.notna(value) and row['age_band']!='未知'
                scores.append(dict(axis=label,metric=key,value=None if pd.isna(value) else value,score=float(ranks.loc[index]) if usable else None,n=n))
            result[row['id']]=profile_from_scores(scores)
    return result


def history_profiles(rows, efficiency=False, scope='all'):
    """Rank each count-led cohort once; exclude self, retain ties and missing values."""
    from creatorlab.hub import eligible
    from creatorlab.reporting import metric_value
    records=[r for r in eligible(rows) if not r.get('demo')]
    # Demonstration rows are handled separately and never enter real references.
    if not records:records=eligible(rows)
    if not records:return {}
    data=pd.DataFrame(records)
    data['media_format']=data.get('media_format',pd.Series('unknown',index=data.index)).fillna('unknown')
    data['_shape_window']=data.get('analysis_window',pd.Series('当前累计',index=data.index)).fillna('当前累计').replace('','当前累计')
    from creatorlab.own_scope import scope_key,scope_label
    data['_own_scope']=[scope_key(r,scope) for r in records]
    result={}
    for _,group in data.groupby('_own_scope',sort=False,dropna=False):
        members=group.to_dict('records')
        axes=[('触达','views'),('喜欢','likes'),('讨论','comments'),('收藏','favorites'),('传播','shares')]
        axes += [('投币支持','coins')] if members[0]['platform']=='bilibili' else [('留住观众','completion_rate')]
        if efficiency:
            from creatorlab.growth import AXES
            axes=AXES[members[0]['platform']]
        if members[0]['platform']=='douyin':axes=axes+[('阅读深度','image_depth' if efficiency else 'avg_image_views')]
        ranked=[]
        for label,key in axes:
            values=pd.Series([metric_value(r,key) for r in members],dtype=float)
            if efficiency and (key.endswith('_ratio') or key=='image_depth'):
                plays=pd.Series([metric_value(r,'views') for r in members],dtype=float)
                values=values.where(plays>=1000)
            count=int(values.notna().sum());ranks=values.rank(method='min')-1
            ranked.append((label,key,values,ranks,count))
        for index,row in enumerate(members):
            scores=[]
            for label,key,values,ranks,count in ranked:
                image=row.get('media_format')=='image' and row['platform']=='douyin'
                if (image and key=='completion_rate') or (not image and key in ('image_depth','avg_image_views')):continue
                ranked_value=values.iloc[index];value=metric_value(row,key);n=count-int(pd.notna(ranked_value))
                score=100*float(ranks.iloc[index])/n if n>=3 and pd.notna(ranked_value) else None
                not_applicable=row.get('media_format')=='image' and key=='completion_rate'
                status='not_applicable' if not_applicable else 'missing' if value is None or pd.isna(value) else 'insufficient' if score is None else 'ready'
                scores.append(dict(axis=label,metric=key,value=None if pd.isna(value) else float(value),score=score,n=0 if not_applicable else n,status=status))
            result[row['id']]=dict(profile_from_scores(scores),comparison='efficiency' if efficiency else 'counts',own_scope=scope,own_scope_label=scope_label(row,scope),applicable=6,media_format=row.get('media_format'))
    return result


BUNDLED_FONT=Path(__file__).resolve().parents[1]/'assets/fonts/NotoSansCJKsc-Regular.otf'
FONT_FILES=(
 r'C:\Windows\Fonts\msyh.ttc',r'C:\Windows\Fonts\msyh.ttf',r'C:\Windows\Fonts\simhei.ttf',r'C:\Windows\Fonts\simsun.ttc',
 '/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Medium.ttc','/System/Library/Fonts/Hiragino Sans GB.ttc',
 '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
 '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')


def font_path():
    """First usable CJK font: CLAB_FONT, the bundled file if present, then common system fonts."""
    import os
    for candidate in (os.environ.get('CLAB_FONT'),str(BUNDLED_FONT),*FONT_FILES):
        if candidate and Path(candidate).exists():return candidate
    raise RuntimeError('找不到支持中文的字体，无法生成分享海报。请保留assets/fonts中的内置字体，或设置环境变量CLAB_FONT指向系统中文字体。')


@lru_cache(maxsize=24)
def font(size):
    try:return ImageFont.truetype(font_path(),size)
    except OSError as exc:raise RuntimeError('中文字体无法读取，请检查CLAB_FONT或保留assets/fonts中的内置字体') from exc


def trim(text,size,max_width):
    f=font(size);text=str(text)
    while f.getlength(text)>max_width and text:text=text[:-1]
    return text


def render_card(row,model,light=False,show_name=False):
    if not model['ready']:raise ValueError('至少3个有真实参照的维度，才能生成分享卡')
    diagnosis=model.get('diagnosis');dual=model.get('dual_scores')
    w,h=1080,1480 if diagnosis else 1320
    from creatorlab.appearance import PALETTES
    palette=PALETTES['暖灰浅色' if light else '柔和深色']
    bg=palette['bg'];panel=palette['panel'];ink=palette['text'];muted=palette['muted']
    grid=palette['border'];accent=palette['accent']
    im=Image.new('RGB',(w,h),bg);d=ImageDraw.Draw(im)
    d.rounded_rectangle((30,30,w-30,h-30),radius=42,fill=panel,outline=grid,width=2)
    def text(x,y,value,size=28,color=ink,anchor=None):d.text((x,y),str(value),font=font(size),fill=color,anchor=anchor)
    text(72,65,'CLab  /  '+('演示数据' if model.get('demo') else '作品战力卡'),25,muted)
    text(1005,66,'B站' if row['platform']=='bilibili' else '抖音',24,muted,'ra')
    text(72,112,'我的创作战力',54)
    has_overall=model.get('overall') is not None
    if has_overall:
        text(1008,111,f'{model["overall"]:.1f}%',54,ink,'ra')
        text(1008,197,'超过对标创作者样本' if model.get('comparison')=='peer' else '数量位置 · 历史参照' if model.get('comparison')=='counts' else '互动效率 · 历史参照' if model.get('comparison')=='efficiency' else '超过同组历史作品',20,muted,'ra')
    title=trim(row['title'],30,600 if has_overall else 935)
    if title!=row['title']:title+='…'
    text(74,197,title,30,muted)
    badge=model['archetype'];badge_width=font(25).getlength(badge)+42
    d.rounded_rectangle((72,258,72+badge_width,304),radius=22,outline=accent,width=2)
    text(92,260,badge,25,accent)
    scope='同行样本 · 探索对标' if model.get('comparison')=='peer' else '小样本探索' if model['exploratory'] else '同组历史位置'
    text(1005,265,scope,24,muted,'ra')
    amber=palette['conversion']
    primary_efficiency=model.get('comparison')=='efficiency'
    line_color=amber if dual and primary_efficiency else accent
    if dual:
        text(72,325,'实线：数量位置',22,accent)
        text(740,325,'虚线：互动转化位置',22,amber)
    cx,cy,radius=540,665,235
    angles=[-math.pi/2+i*math.pi/3 for i in range(6)]
    def point(i,r):return (cx+math.cos(angles[i])*r,cy+math.sin(angles[i])*r)
    for level in (20,40,60,80,100):
        pts=[point(i,radius*level/100) for i in range(6)]
        d.line(pts+[pts[0]],fill=grid,width=2)
    for i in range(6):d.line([(cx,cy),point(i,radius)],fill=grid,width=2)
    # Distinct own-history midpoint, not an invented second creator.
    mid=[point(i,radius*.5) for i in range(6)]
    for i in range(6):
        a,b=mid[i],mid[(i+1)%6]
        for k in range(0,12,2):
            t,u=k/12,(k+1)/12
            d.line([(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t),(a[0]+(b[0]-a[0])*u,a[1]+(b[1]-a[1])*u)],fill=muted,width=2)
    scores=model['scores'];points=[point(i,radius*s['score']/100) if s['score'] is not None else None for i,s in enumerate(scores)]
    if all(p is not None for p in points):
        overlay=Image.new('RGBA',im.size);od=ImageDraw.Draw(overlay)
        od.polygon(points,fill=(151,96,31,24) if dual and primary_efficiency else (57,124,98,32))
        im=Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB');d=ImageDraw.Draw(im)
    def stroke(vertices,color,dashed=False,width=6):
        for i in range(6):
            a,b=vertices[i],vertices[(i+1)%6]
            if a is None or b is None:continue
            if not dashed:
                d.line([a,b],fill=color,width=width)
                continue
            for k in range(0,20,2):
                t,u=k/20,(k+1)/20
                d.line([(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t),(a[0]+(b[0]-a[0])*u,a[1]+(b[1]-a[1])*u)],fill=color,width=width)
    stroke(points,line_color,dashed=bool(dual and primary_efficiency))
    if dual:
        secondary=[point(i,radius*s['score']/100) if s['score'] is not None else None for i,s in enumerate(dual)]
        stroke(secondary,accent if primary_efficiency else amber,dashed=not primary_efficiency,width=5)
    for i,s in enumerate(scores):
        p=points[i]
        if p:d.ellipse((p[0]-7,p[1]-7,p[0]+7,p[1]+7),fill=line_color,outline=panel,width=2)
        x,y=point(i,310)
        from creatorlab.engagement import AXIS_NAMES
        text(x,y-21,AXIS_NAMES.get(s['axis'],s['axis']) if dual else s['axis'],26,muted,'mm')
        if s['metric']=='completion_rate' and model.get('comparison') not in ('peer','weekly'):
            from creatorlab.engagement import axis_value
            label_x=x-22 if x<cx else x+22
            text(label_x,y+16,'实测 '+axis_value(s),24,ink,'mm')
            text(label_x,y+47,'有效参照不足' if s['score'] is None else f"高于{round(s['score']*s['n']/100)}/{s['n']}条",19,muted,'mm')
        elif dual:
            a,b=(dual[i]['score'],s['score']) if primary_efficiency else (s['score'],dual[i]['score'])
            number=lambda v:'—' if v is None else str(round(v))
            text(x,y+24,'图文不适用' if s.get('status')=='not_applicable' else f'数量{number(a)} / 转化{number(b)}',21,ink,'mm')
        else:text(x,y+24,'不适用' if s.get('status')=='not_applicable' else '待解锁' if s['score'] is None else str(round(s['score'])),35,muted if s['score'] is None else ink,'mm')
    d.line((72,1043,1008,1043),fill=grid,width=2)
    from creatorlab.hub import fmt_count,fmt_rate
    raw=[('播放',fmt_count(row.get('views'))),('点赞/播放',fmt_rate(row.get('like_ratio'))),('投币/播放' if row['platform']=='bilibili' else '完播率',fmt_rate(row.get('coin_ratio') if row['platform']=='bilibili' else row.get('completion_rate')))]
    if model.get('comparison')=='counts':raw=[('播放',fmt_count(row.get('views'))),('点赞',fmt_count(row.get('likes'))),('收藏',fmt_count(row.get('favorites')))]
    if diagnosis:
        from creatorlab.engagement import axis_value
        raw=[('播放',fmt_count(diagnosis['views'])),('点赞',fmt_count(diagnosis['likes'])),('点赞 / 播放',axis_value(dict(metric='like_ratio',value=diagnosis['rate'])))]
    for x,(label,value) in zip((220,540,860),raw):text(x,1077,label,23,muted,'mm');text(x,1125,value,37,ink,'mm')
    window=row.get('analysis_window','当前累计');age=row.get('age_band','未知')
    if model.get('comparison')=='peer':
        scope_line=model['comparison_scope']+f' · {model["comparison_n"]}位对标创作者'
    elif model.get('comparison') in ('counts','efficiency'):scope_line=f'{window} · {model.get("own_scope_label","全部作品")} · 不限作品年龄 · 可用轴参照≥{model["sample_n"]}条'
    else:scope_line=f'{window} · 同账号'+(f' · 发布后{age}' if window=='当前累计' else '')+f' · 可用轴参照≥{model["sample_n"]}条'
    text(72,1180,trim(scope_line,21,935),21,muted)
    if model.get('comparison')=='counts' and not has_overall:text(72,1210,'数量为主；图文第六轴为平均浏览图片数 · 非内容质量总分' if row.get('media_format')=='image' else '数量为主；留住观众为完播率 · 非内容质量总分 · 非全站排名',19,muted)
    if has_overall:text(72,1210,f'综合比较{model["comparison_axes"]}维 · {model["comparison_n"]}个参照 · 并列不算超过 · 非全站排名',19,muted)
    footer=trim(row.get('account_name',''),22,300) if show_name else '把创作变成看得见的成长'
    if row.get('media_format')=='image':
        from creatorlab.reporting import metric_value
        avg=metric_value(row,'avg_image_views');total=metric_value(row,'image_count');depth=metric_value(row,'image_depth')
        footer='图文平均浏览 '+('—' if avg is None else f'{avg:g}')+' / 共 '+('—' if total is None else f'{total:g}')+'张 · 深度 '+('—' if depth is None else f'{depth:.1%}')
    text(72,1251,footer,20 if row.get('media_format')=='image' else 22,accent)
    text(1008,1240,f'{model["available"]}/{model.get("applicable",6)}适用维度 · 非行业评级',20,muted,'ra')
    if diagnosis:
        d.line((72,1290,1008,1290),fill=grid,width=2)
        text(72,1310,trim(diagnosis['message'],25,935),25,amber if diagnosis['state']=='reach_like_gap' else ink)
        if diagnosis['median_rate'] is not None:
            text(72,1360,f"同组点赞率中位数 {diagnosis['median_rate']:.2%} · {diagnosis['n']}条其他作品 · 参照播放≥{diagnosis['min_views']}",21,muted)
        text(72,1410,'图文深度=平均浏览张数÷总张数；非看完观众比例，源数据可能取整。' if row.get('media_format')=='image' else '数量与转化分开看；点赞行为不等于全部观众喜好，不代表全站评级。',20,muted)
    out=io.BytesIO();im.save(out,'PNG');return out.getvalue()
