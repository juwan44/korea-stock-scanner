import streamlit as st
import pandas as pd
import requests
from io import StringIO
from datetime import datetime

st.set_page_config(page_title="단타포착", page_icon="🔥", layout="wide")
st.title("🔥 한국주식 단타포착")
st.caption("갤럭시 Chrome · 증권사 API Key 없음 · 조회/검색 전용")

@st.cache_data(ttl=60)
def load_market(market):
    rows = []
    for page in range(1, 21):
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={market}&page={page}"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        r.encoding = "euc-kr"
        tables = pd.read_html(StringIO(r.text), attrs={"class":"type_2"})
        if tables:
            x = tables[0].dropna(subset=["종목명"])
            rows.append(x)
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows, ignore_index=True)
    df["시장"] = "KOSPI" if market == 0 else "KOSDAQ"
    return df

def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",","",regex=False)
                         .str.replace("%","",regex=False)
                         .str.replace("+","",regex=False), errors="coerce")

with st.sidebar:
    st.header("검색 조건")
    market = st.radio("시장", ["전체","코스피","코스닥"])
    min_price = st.number_input("최소 현재가", 0, 1000000, 1000, 500)
    min_change = st.number_input("최소 상승률 %", -30.0, 30.0, 2.0, .5)
    max_change = st.number_input("최대 상승률 %", -30.0, 30.0, 15.0, .5)
    min_value = st.number_input("최소 거래대금 추정(억원)", 0, 100000, 50, 10)
    top_n = st.slider("표시 종목", 10, 100, 30, 10)

st.info("API 키가 필요 없습니다. 공개 웹 시세 기반이라 증권사 실시간 체결강도/분봉과는 다를 수 있습니다.")

if st.button("🔎 지금 단타 후보 찾기", type="primary", use_container_width=True):
    try:
        frames = []
        if market in ("전체","코스피"): frames.append(load_market(0))
        if market in ("전체","코스닥"): frames.append(load_market(1))
        df = pd.concat([x for x in frames if not x.empty], ignore_index=True)
        for c in ["현재가","등락률","거래량"]:
            df[c] = num(df[c])
        df["거래대금(억)"] = df["현재가"] * df["거래량"] / 100_000_000
        df = df[(df["현재가"] >= min_price) &
                df["등락률"].between(min_change, max_change) &
                (df["거래대금(억)"] >= min_value)].copy()
        if not df.empty:
            a = df["거래대금(억)"].rank(pct=True)*45
            b = df["거래량"].rank(pct=True)*30
            c = ((df["등락률"]-min_change)/max(max_change-min_change,.1)).clip(0,1)*25
            df["검색점수"] = (a+b+c).round().astype(int)
            df = df.sort_values(["검색점수","거래대금(억)"], ascending=False).head(top_n)
        st.session_state.scan = df
    except Exception as e:
        st.error("시세를 불러오지 못했습니다. 잠시 후 다시 시도하세요.")
        st.code(str(e))

df = st.session_state.get("scan", pd.DataFrame())
if not df.empty:
    st.success(f"🔥 후보 {len(df)}종목")
    show = df[["시장","종목명","현재가","등락률","거래량","거래대금(억)","검색점수"]].copy()
    show["현재가"] = show["현재가"].map(lambda x:f"{x:,.0f}원")
    show["등락률"] = show["등락률"].map(lambda x:f"{x:+.2f}%")
    show["거래대금(억)"] = show["거래대금(억)"].map(lambda x:f"{x:,.0f}억")
    st.dataframe(show, hide_index=True, use_container_width=True, height=650)
    st.caption("검색점수는 후보 정렬용이며 매수·매도 추천이 아닙니다.")
elif "scan" in st.session_state:
    st.warning("조건에 맞는 종목이 없습니다.")

st.caption("공개 웹 시세는 지연되거나 제공 방식이 변경될 수 있습니다.")
