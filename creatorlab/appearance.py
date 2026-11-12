"""Session-scoped appearance: app controls, popovers and charts share one palette."""
import streamlit as st

PALETTES={
 '柔和深色':dict(bg='#17191B',panel='#202326',text='#ECEFEE',muted='#ADB5B2',border='#3A4043',accent='#83D8B8',button='#2A2F32',conversion='#E9AE6C'),
 '暖灰浅色':dict(bg='#D9D3C8',panel='#E6E0D5',text='#252B29',muted='#4D554F',border='#B9B1A4',accent='#215F4B',button='#D4CEC3',conversion='#7C4C17')}

PLATFORM_BACKGROUNDS={
    'douyin':{'柔和深色':'#17191F','暖灰浅色':'#D9CED0'},
    'bilibili':{'柔和深色':'#152733','暖灰浅色':'#CDD8DB'},
}


def setup(platform=None,host=None):
    chosen=(host or st.sidebar).radio('明暗切换',list(PALETTES),key='clab_appearance',horizontal=True)
    p=PALETTES[chosen]
    platform=platform or st.session_state.get('active_platform','douyin')
    canvas=PLATFORM_BACKGROUNDS.get(platform,PLATFORM_BACKGROUNDS['douyin'])[chosen]
    # Specific widget selectors avoid dark-control/light-text mismatches. No globals
    # are changed: each browser session has its own selection.
    css='''
    :root {--background-color:CANVAS;--secondary-background-color:PANEL;--text-color:TEXT;--primary-color:ACCENT;color-scheme:SCHEME;}
    .stApp,[data-testid="stAppViewContainer"],.stMain,[data-testid="stHeader"] {background:CANVAS!important;color:TEXT!important;}
    [data-testid="stSidebar"],[data-testid="stSidebarContent"] {background:PANEL!important;color:TEXT!important;}
    .stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp p,.stApp label,.stApp summary,.stApp legend,
    [data-testid="stMetricValue"],[data-testid="stMetricLabel"],.stMarkdown,[data-testid="stWidgetLabel"] {color:TEXT!important;}
    [data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p {color:MUTED!important;}
    .stApp a {color:ACCENT;}
    [data-baseweb="select"]>div,[data-baseweb="input"],[data-baseweb="base-input"],
    .stApp input,.stApp textarea,[data-baseweb="textarea"] {background:PANEL!important;color:TEXT!important;border-color:BORDER!important;}
    .stApp input::placeholder,.stApp textarea::placeholder {color:MUTED!important;}
    [data-testid="stDateInput"]>div,[data-testid="stDateInputField"],
    [data-testid="stDateInputFieldsScroller"] {background:PANEL!important;color:TEXT!important;border-color:BORDER!important;border-radius:8px;}
    [data-testid="stDateInput"] [data-rac],[data-testid="stDateInput"] span {color:TEXT!important;}
    [data-testid="stDateInput"] [role="spinbutton"]:focus {background:BUTTON!important;outline:2px solid ACCENT;}
    [data-baseweb="select"] *,[role="option"] *,[data-testid="stRadio"] label * {color:TEXT!important;}
    [data-testid="stRadioOption"]>div>div:first-child {background:transparent!important;border:1px solid MUTED!important;}
    [data-testid="stRadioOption"]>div>div:first-child>div {background:transparent!important;}
    [data-testid="stRadioOption"][data-selected="true"]>div>div:first-child {background:ACCENT!important;border-color:ACCENT!important;}
    [data-testid="stRadioOption"][data-selected="true"]>div>div:first-child>div {background:BG!important;}
    [data-testid="stRadioOption"]:has(input:focus-visible) {outline:2px solid ACCENT;outline-offset:4px;border-radius:4px;}
    [data-baseweb="select"] svg,[data-testid="stExpander"] summary svg {fill:TEXT!important;color:TEXT!important;}
    [data-baseweb="popover"],[data-baseweb="popover"]>div,[data-baseweb="menu"],
    [role="listbox"],[role="option"] {background:PANEL!important;color:TEXT!important;}
    [role="option"]:hover,[aria-selected="true"][role="option"] {background:BUTTON!important;}
    [data-baseweb="tag"] {background:BUTTON!important;color:TEXT!important;}
    .stApp button,[data-testid="stLinkButton"] a {background:BUTTON!important;color:TEXT!important;border:1px solid BORDER!important;}
    .stApp button p,.stApp button span,[data-testid="stLinkButton"] a p {color:TEXT!important;}
    .st-key-work_view [role="radiogroup"] {gap:8px;}
    .st-key-work_view button[data-variant="segmented_control"] {margin-right:0!important;}
    .stApp button[data-variant="segmented_control"][aria-checked="true"] {background:PANEL!important;border-color:ACCENT!important;box-shadow:inset 0 -3px 0 ACCENT!important;}
    .stApp button[data-variant="segmented_control"][aria-checked="true"] p {color:ACCENT!important;font-weight:650;}
    .stApp button:hover,[data-testid="stLinkButton"] a:hover {border-color:ACCENT!important;}
    .stApp button {border-radius:6px!important;font-weight:500;box-shadow:none!important;}
    .stApp button[kind="primary"],[data-testid="stBaseButton-primary"] {background:ACCENT!important;border-color:ACCENT!important;color:BG!important;}
    .stApp button[kind="primary"] p,[data-testid="stBaseButton-primary"] p {color:BG!important;}
    .stApp button:focus-visible {outline:2px solid ACCENT!important;outline-offset:3px;}
    .stApp button:disabled {opacity:.5;}
    [data-baseweb="tab-list"] {background:BG!important;border-bottom:1px solid BORDER;}
    [data-baseweb="tab"] {background:transparent!important;border:0!important;color:MUTED!important;}
    [data-baseweb="tab"][aria-selected="true"] {color:ACCENT!important;}
    [data-baseweb="tab-highlight"] {background:ACCENT!important;height:2px;}
    [data-testid="stExpander"],[data-testid="stExpander"] details,[data-testid="stExpander"] summary,
    [data-testid="stForm"],[data-testid="stVerticalBlockBorderWrapper"] {background:transparent!important;border-color:BORDER!important;}
    [data-testid="stAlert"] {background:transparent!important;color:TEXT!important;border:1px solid BORDER!important;border-radius:5px;}
    .stApp table,.stApp th,.stApp td {background:transparent!important;color:TEXT!important;border-color:BORDER!important;}
    .stApp th {background:PANEL!important;}
    [data-testid="stFileUploaderDropzone"] {background:PANEL!important;color:TEXT!important;}
    [data-testid="stMetricDelta"] {color:ACCENT!important;}
    /* Keep content below Streamlit's fixed 3.75rem toolbar, also on phones. */
    [data-testid="stMainBlockContainer"],.block-container {
      max-width:1520px;padding:1rem 2rem 3rem!important;
    }
    /* Put the toolbar in normal flow: fixed overlays clipped the first heading. */
    [data-testid="stHeader"] {position:relative!important;top:auto!important;min-height:3.75rem;flex-shrink:0;}
    [data-testid="stMain"] {scroll-padding-top:1rem;}
    [data-testid="stMarkdownContainer"] h1,[data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3 {white-space:normal!important;overflow:visible!important;overflow-wrap:anywhere;line-height:1.45!important;}
    [data-baseweb="select"] [data-testid="stMarkdownContainer"] {white-space:normal!important;}
    @media(min-width:1000px){[data-testid="stSidebar"]{min-width:230px!important;max-width:250px!important;}}
    [data-testid="stAppDeployButton"] {display:none;}
    [data-testid="stImage"] img {max-width:100%;height:auto;border-radius:8px;}
    [data-testid="stMetricValue"] {font-size:1.75rem;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:0;}
    [data-testid="stMetricLabel"] p {font-size:.875rem;color:MUTED!important;}
    [data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p {line-height:1.65;font-size:.875rem;}
    [data-testid="stTabs"] [data-baseweb="tab-list"] {gap:1.5rem;flex-wrap:nowrap;margin-bottom:.5rem;}
    [data-baseweb="tab"] {padding-left:0!important;padding-right:0!important;min-height:44px;}
    h1 {font-size:1.75rem!important;letter-spacing:0;font-weight:600!important;}
    h2 {font-size:1.3rem!important;font-weight:600!important;} h3 {font-size:1.04rem!important;font-weight:600!important;}
    .stApp p,.stApp label {line-height:1.6;}
    .stApp {font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif;font-variant-numeric:tabular-nums;}
    .stApp h2,.stApp h3,.stApp label {letter-spacing:0!important;}
    .stApp table {font-size:.875rem;}
    [data-testid="stTable"] {overflow-x:auto;}
    @media(max-width:1000px){
      [data-testid="stSidebar"]{min-width:216px!important;max-width:216px!important;}
      [data-testid="stMainBlockContainer"],.block-container{padding:1rem 1rem 2rem!important;}
      .st-key-battle-stage>[data-testid="stHorizontalBlock"]{flex-direction:column;}
      .st-key-battle-stage>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{width:100%!important;flex:1 1 100%!important;min-width:0!important;}
    }
    @media(max-width:640px){
      .st-key-battle-filters [data-testid="stHorizontalBlock"]{gap:12px;}
      .st-key-battle-stage .angularaxistick text{font-size:11px!important;}
      h1{font-size:1.5rem!important;}
      [data-testid="stCaptionContainer"] p{font-size:.8125rem;}
    }
    hr {border-color:BORDER!important;margin:1.15rem 0!important;}
    button {min-height:2.3rem;}
    '''
    css=css.replace('CANVAS',canvas)
    for token,key in [('BACKGROUND','bg'),('BUTTON','button'),('ACCENT','accent'),('BORDER','border'),('PANEL','panel'),('MUTED','muted'),('TEXT','text'),('BG','bg')]:
        css=css.replace(token,p[key])
    css=css.replace('SCHEME','dark' if chosen=='柔和深色' else 'light')
    st.markdown('<style>'+css+'</style>',unsafe_allow_html=True)


def platform_header(platform):
    """Wordmark and fixed background watermark, outside the document flow."""
    from pathlib import Path
    from html import escape
    from base64 import b64encode
    from xml.etree import ElementTree as ET
    from creatorlab.version import VERSION
    light=st.session_state.get('clab_appearance')=='暖灰浅色'
    filename='bilibili-mascot.svg' if platform=='bilibili' else 'tiktok.svg'
    source=Path(__file__).resolve().parents[1]/'assets'/'branding'/filename
    root=ET.fromstring(source.read_text(encoding='utf-8'))
    if platform=='bilibili':
        root.set('opacity','.24' if light else '.20')
        svg=ET.tostring(root,encoding='unicode').replace('currentColor','#1684AE' if light else '#64C8F0')
    else:
        path=escape(root.find('{http://www.w3.org/2000/svg}path').attrib['d'],quote=True)
        ink=PALETTES['暖灰浅色' if light else '柔和深色']['text']
        layers=(f'<path fill="#25F4EE" transform="translate(-.6,-.4)" d="{path}"/>'
                f'<path fill="#FE2C55" transform="translate(.6,.4)" d="{path}"/>'
                f'<path fill="{ink}" d="{path}"/>')
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 26 26" opacity=".16">{layers}</svg>'
    image='data:image/svg+xml;base64,'+b64encode(svg.encode('utf-8')).decode('ascii')
    accent=PALETTES['暖灰浅色' if light else '柔和深色']['accent']
    st.html('''<style>
    [data-testid="stMain"] {
      background-image:url("WATERMARK")!important;
      background-repeat:no-repeat!important;
      background-attachment:fixed!important;
      background-position:right 32px top 80px!important;
      background-size:280px auto!important;
    }
    .creatorlab-wordmark {
      font-family:"Segoe UI Variable Display","Aptos Display","Segoe UI",sans-serif!important;
      font-size:64px!important;font-weight:600!important;line-height:1.12!important;
      letter-spacing:-.025em!important;margin:0!important;padding:0!important;
    }
    .creatorlab-wordmark span{color:BRAND;font-weight:500;}
    .st-key-platform-brand [data-testid="stVerticalBlock"]{gap:4px;}
    .st-key-platform-brand{margin-bottom:12px;}
    @media(max-width:640px){
      .creatorlab-wordmark{font-size:44px!important;}
      [data-testid="stMain"]{background-size:168px auto!important;background-position:right 16px top 64px!important;}
    }
    </style>'''.replace('WATERMARK',image).replace('BRAND',accent))
    with st.container(key='platform-brand'):
        st.html('<h1 class="creatorlab-wordmark" aria-label="CreatorLab">Creator<span>Lab</span></h1>')
        st.caption(f'v{VERSION} · 创作者数据工作台')
        st.markdown('看见创作力，让每次尝试都有依据')
        st.caption(('B站' if platform=='bilibili' else '抖音')+' · 作品管理与分析')


def chart(fig,key=None,surface='bg',**kwargs):
    name=st.session_state.get('clab_appearance','柔和深色');p=PALETTES[name]
    fig.update_layout(template='plotly_dark' if name=='柔和深色' else 'plotly_white',
      paper_bgcolor=p[surface],plot_bgcolor=p[surface],font=dict(size=14,color=p['text'],family='Microsoft YaHei, PingFang SC, sans-serif'),
      hoverlabel=dict(bgcolor=p['panel'],font_color=p['text']),
      margin=fig.layout.margin.to_plotly_json() if fig.layout.margin.to_plotly_json() else dict(l=32,r=32,t=32,b=24),colorway=[p['accent'],p['conversion'],'#9DAFD0'])
    fig.update_polars(bgcolor=p[surface],radialaxis_gridcolor=p['border'],angularaxis_gridcolor=p['border'])
    fig.update_xaxes(gridcolor=p['border'],zerolinecolor=p['border'])
    fig.update_yaxes(gridcolor=p['border'],zerolinecolor=p['border'])
    options={k:v for k,v in kwargs.items() if k in ('on_select','selection_mode')}
    return st.plotly_chart(fig,width='stretch',theme=None,config={'displayModeBar':False,'scrollZoom':False},key=key,**options)


def table(data,**kwargs):
    """HTML tables inherit both palettes, including their headers and borders."""
    st.table(data)
