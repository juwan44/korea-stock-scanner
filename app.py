import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

st.set_page_config(page_title='단타포착', page_icon='📈', layout='wide')

st.markdown('''
<style>
.block-container{padding-top:1rem;padding-left:.7rem;padding-right:.7rem}
[data-testid="stMetricValue"]{font-size:1.25rem}
.stButton button{width:100%;height:3rem;font-weight:700}
</style>
''', unsafe_allow_html=True)

st.title('📈 단타포착')
st.caption('갤럭시 · Streamlit 모바일용 / 키움 REST API')

with st.sidebar:
    st.header('키움 API 설정')
    app_key = st.text_input('App Key', type='password')
    secret_key = st.text_input('Secret Key', type='password')
    use_mock = st.toggle('모의투자', value=True)
    st.divider()
    st.header('검색 조건')
    min_change = st.number_input('최소 등락률(%)', -30.0, 30.0, 2.0, .5)
    max_change = st.number_input('최대 등락률(%)', -30.0, 30.0, 15.0, .5)
    min_value_uk = st.number_input('최소 거래대금(억원)', 0, 100000, 50, 10)
    min_strength = st.number_input('최소 체결강도(%)', 0, 1000, 120, 10)
    high_gap = st.number_input('고가 대비 최대 이격(%)', 0.0, 30.0, 3.0, .5)
    refresh_sec = st.selectbox('자동 새로고침', [0, 5, 10, 30, 60], index=2, format_func=lambda x: '끄기' if x==0 else f'{x}초')

BASE_REAL='https://api.kiwoom.com'
BASE_MOCK='https://mockapi.kiwoom.com'

def base_url():
    return BASE_MOCK if use_mock else BASE_REAL

@st.cache_data(ttl=60*60*8)
def token_cached(key, secret, mock):
    if not key or not secret:
        return None, 'App Key / Secret Key를 입력하세요.'
    url=(BASE_MOCK if mock else BASE_REAL)+'/oauth2/token'
    payload={'grant_type':'client_credentials','appkey':key,'secretkey':secret}
    try:
        r=requests.post(url,json=payload,headers={'Content-Type':'application/json;charset=UTF-8'},timeout=10)
        data=r.json()
        if r.ok:
            tok=data.get('token') or data.get('access_token')
            return tok, None
        return None, data.get('return_msg') or data.get('message') or str(data)
    except Exception as e:
        return None, str(e)

def api_get(path, token, api_id, params=None):
    headers={'authorization':f'Bearer {token}','api-id':api_id,'Content-Type':'application/json;charset=UTF-8'}
    r=requests.get(base_url()+path, headers=headers, params=params or {}, timeout=10)
    try: data=r.json()
    except: data={'raw':r.text}
    return r.status_code, data

# API 명세 변경에 대비해, 검색 API ID/경로는 사용자가 직접 수정 가능하게 둡니다.
with st.expander('고급 설정 — 키움 순위 API'):
    st.info('키움 REST API 명세가 바뀌면 아래 API ID/경로/파라미터를 공식 명세에 맞게 수정하세요.')
    rank_path=st.text_input('거래대금/거래량 순위 API 경로', value='/api/dostk/rkinfo')
    rank_api_id=st.text_input('API ID', value='ka10032')
    rank_params_text=st.text_area('추가 파라미터 (key=value, 한 줄씩)', value='mrkt_tp=000\ntrde_qty_tp=0\nprice_tp=0\ntrde_prica_tp=0')

def parse_params(txt):
    out={}
    for line in txt.splitlines():
        if '=' in line:
            k,v=line.split('=',1); out[k.strip()]=v.strip()
    return out

def normalize_rows(data):
    # 응답 안에서 가장 그럴듯한 list[dict]를 찾아 공통 컬럼으로 변환
    lists=[]
    def walk(x):
        if isinstance(x, list) and x and isinstance(x[0], dict): lists.append(x)
        elif isinstance(x, dict):
            for v in x.values(): walk(v)
    walk(data)
    if not lists: return pd.DataFrame()
    rows=max(lists,key=len)
    df=pd.DataFrame(rows)
    aliases={
      '종목코드':['stk_cd','stck_shrn_iscd','code','종목코드'],
      '종목명':['stk_nm','hts_kor_isnm','name','종목명'],
      '현재가':['cur_prc','stck_prpr','price','현재가'],
      '등락률':['flu_rt','prdy_ctrt','change_rate','등락률'],
      '거래량':['trde_qty','acml_vol','volume','거래량'],
      '거래대금':['trde_prica','acml_tr_pbmn','trade_value','거래대금'],
      '체결강도':['cntr_str','tday_rltv','strength','체결강도'],
      '고가':['high_pric','stck_hgpr','high','고가'],
    }
    out=pd.DataFrame(index=df.index)
    for dst, candidates in aliases.items():
        src=next((c for c in candidates if c in df.columns),None)
        out[dst]=df[src] if src else None
    return out

def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',','',regex=False).str.replace('+','',regex=False).str.replace('%','',regex=False), errors='coerce').abs()

def score_frame(df):
    if df.empty: return df
    for c in ['현재가','등락률','거래량','거래대금','체결강도','고가']:
        df[c]=num(df[c])
    df['고가이격%']=((df['고가']-df['현재가'])/df['고가']*100).clip(lower=0)
    # 거래대금 단위는 API별 차이가 있을 수 있어 화면에서 원값도 확인 가능
    v=df['거래대금'].fillna(0)
    v_norm=(v.rank(pct=True)*30)
    vol_norm=(df['거래량'].fillna(0).rank(pct=True)*20)
    str_norm=((df['체결강도'].fillna(0)/200).clip(0,1)*20)
    high_norm=((1-(df['고가이격%'].fillna(100)/max(high_gap,0.1))).clip(0,1)*15)
    chg_norm=((df['등락률'].fillna(0)/max(max_change,0.1)).clip(0,1)*15)
    df['점수']=(v_norm+vol_norm+str_norm+high_norm+chg_norm).round(0)
    mask=(df['등락률'].between(min_change,max_change)) & (df['체결강도'].fillna(0)>=min_strength) & (df['고가이격%'].fillna(999)<=high_gap)
    df=df[mask].sort_values(['점수','거래대금'],ascending=False)
    return df

col1,col2=st.columns([2,1])
with col1:
    run=st.button('🔥 지금 단타 종목 찾기', type='primary')
with col2:
    st.metric('현재 시각', datetime.now().strftime('%H:%M:%S'))

if 'last_df' not in st.session_state: st.session_state.last_df=pd.DataFrame()

if run or (refresh_sec and app_key and secret_key):
    token,err=token_cached(app_key,secret_key,use_mock)
    if err:
        st.error('인증 실패: '+err)
    else:
        status,data=api_get(rank_path,token,rank_api_id,parse_params(rank_params_text))
        if status>=400 or (isinstance(data,dict) and str(data.get('return_code','0')) not in ('0','None')):
            st.error('키움 API 호출 오류')
            st.json(data)
        else:
            raw=normalize_rows(data)
            if raw.empty:
                st.warning('순위 데이터 목록을 찾지 못했습니다. 고급 설정의 API ID/경로를 키움 최신 명세와 맞춰주세요.')
                st.json(data)
            else:
                st.session_state.last_df=score_frame(raw)

df=st.session_state.last_df
if not df.empty:
    st.subheader(f'🔥 포착 {len(df)}종목')
    for _,r in df.head(30).iterrows():
        name=r.get('종목명') or r.get('종목코드') or '-'
        with st.container(border=True):
            a,b,c=st.columns([1.7,1,1])
            a.markdown(f"### {name}")
            b.metric('등락률', f"+{r['등락률']:.2f}%" if pd.notna(r['등락률']) else '-')
            c.metric('점수', f"{int(r['점수'])}" if pd.notna(r['점수']) else '-')
            x,y,z=st.columns(3)
            x.metric('현재가', f"{int(r['현재가']):,}원" if pd.notna(r['현재가']) else '-')
            y.metric('체결강도', f"{r['체결강도']:.0f}%" if pd.notna(r['체결강도']) else '-')
            z.metric('고가대비', f"-{r['고가이격%']:.1f}%" if pd.notna(r['고가이격%']) else '-')
            st.caption(f"코드 {r.get('종목코드','-')} · 거래량 {int(r['거래량']):,}" if pd.notna(r['거래량']) else f"코드 {r.get('종목코드','-')}")
    with st.expander('표로 보기'):
        st.dataframe(df, use_container_width=True, hide_index=True)
elif not run:
    st.info('왼쪽 설정에서 키움 App Key / Secret Key를 넣고 **지금 단타 종목 찾기**를 누르세요.')
    st.warning('API 키는 타인에게 보내거나 코드에 저장하지 마세요. 이 앱은 종목 검색 보조 도구이며 자동 주문은 하지 않습니다.')

if refresh_sec and app_key and secret_key:
    time.sleep(refresh_sec)
    st.rerun()
