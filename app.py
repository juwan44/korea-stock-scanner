import re
import time
from io import StringIO

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="단타포착", page_icon="🔥", layout="wide")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
    "Referer": "https://finance.naver.com/",
    "Connection": "keep-alive",
}

MARKET_URL = "https://finance.naver.com/sise/sise_market_sum.naver"

st.title("🔥 한국주식 단타포착")
st.caption("갤럭시 Chrome · 증권사 API Key 없음 · 조회/검색 전용")


def clean_num(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace("+", "", regex=False)
        .str.replace("−", "-", regex=False)
        .str.strip(),
        errors="coerce",
    )


def normalize_table(df, market_name):
    # 네이버 표가 MultiIndex로 바뀌어도 최대한 버팀
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(x) for x in col if str(x) != "nan").strip()
            for col in df.columns
        ]
    df.columns = [str(c).strip() for c in df.columns]

    def find_col(name):
        for c in df.columns:
            if c == name or name in c:
                return c
        return None

    name_col = find_col("종목명")
    price_col = find_col("현재가")
    change_col = find_col("등락률")
    volume_col = find_col("거래량")

    if not all([name_col, price_col, change_col, volume_col]):
        return pd.DataFrame()

    out = df[[name_col, price_col, change_col, volume_col]].copy()
    out.columns = ["종목명", "현재가", "등락률", "거래량"]
    out = out.dropna(subset=["종목명"])
    out["종목명"] = out["종목명"].astype(str).str.strip()
    out = out[
        ~out["종목명"].isin(["nan", "종목명"])
        & out["종목명"].ne("")
    ]
    out["시장"] = market_name
    return out[["시장", "종목명", "현재가", "등락률", "거래량"]]


def parse_market_html(html, market_name):
    # 1차: pandas 표 파싱
    try:
        tables = pd.read_html(StringIO(html), attrs={"class": "type_2"})
        for table in tables:
            out = normalize_table(table, market_name)
            if not out.empty:
                return out
    except Exception:
        pass

    # 2차: HTML 구조가 조금 변해도 직접 파싱
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.type_2")
    if table is None:
        return pd.DataFrame()

    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    if not headers:
        header_row = table.find("tr")
        headers = [x.get_text(" ", strip=True) for x in header_row.find_all(["th", "td"])] if header_row else []

    rows = []
    for tr in table.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if cells and len(cells) == len(headers):
            rows.append(cells)

    if not rows or not headers:
        return pd.DataFrame()

    try:
        return normalize_table(pd.DataFrame(rows, columns=headers), market_name)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=180, show_spinner=False)
def load_market(market):
    market_name = "KOSPI" if market == 0 else "KOSDAQ"
    session = requests.Session()
    session.headers.update(HEADERS)

    collected = []
    errors = []

    # 20페이지 고정 호출 대신 데이터가 끝나면 즉시 종료
    for page in range(1, 41):
        try:
            r = session.get(
                MARKET_URL,
                params={"sosok": market, "page": page},
                timeout=(5, 12),
            )
            if r.status_code in (403, 429):
                raise RuntimeError(f"HTTP {r.status_code}: 공개 시세 서버가 클라우드 요청을 제한했습니다.")
            r.raise_for_status()

            # 네이버 금융 PC HTML은 통상 EUC-KR 계열
            r.encoding = r.apparent_encoding or "euc-kr"
            page_df = parse_market_html(r.text, market_name)

            if page_df.empty:
                if page == 1:
                    errors.append("첫 페이지에서 시세 표를 찾지 못했습니다.")
                break

            collected.append(page_df)

            # 보통 마지막 페이지는 행 수가 줄어든다.
            if len(page_df) < 40:
                break
            time.sleep(0.08)

        except requests.RequestException as e:
            errors.append(f"{type(e).__name__}: {e}")
            break
        except Exception as e:
            errors.append(str(e))
            break

    if not collected:
        detail = errors[-1] if errors else "응답은 받았지만 종목 표가 비어 있습니다."
        raise RuntimeError(f"{market_name} 데이터 수집 실패 — {detail}")

    df = pd.concat(collected, ignore_index=True)
    df = df.drop_duplicates(subset=["시장", "종목명"])
    return df


def run_scan(selected_market, min_price, min_change, max_change, min_value, top_n):
    if min_change > max_change:
        raise ValueError("최소 상승률은 최대 상승률보다 클 수 없습니다.")

    targets = []
    if selected_market in ("전체", "코스피"):
        targets.append(0)
    if selected_market in ("전체", "코스닥"):
        targets.append(1)

    frames, failures = [], []
    for m in targets:
        try:
            frames.append(load_market(m))
        except Exception as e:
            failures.append(str(e))

    good = [x for x in frames if not x.empty]
    if not good:
        raise RuntimeError(" / ".join(failures) if failures else "종목 데이터가 비어 있습니다.")

    df = pd.concat(good, ignore_index=True)

    for c in ["현재가", "등락률", "거래량"]:
        df[c] = clean_num(df[c])
    df = df.dropna(subset=["현재가", "등락률", "거래량"])

    df["거래대금(억)"] = df["현재가"] * df["거래량"] / 100_000_000

    df = df[
        (df["현재가"] >= min_price)
        & df["등락률"].between(min_change, max_change)
        & (df["거래대금(억)"] >= min_value)
    ].copy()

    if not df.empty:
        value_score = df["거래대금(억)"].rank(pct=True) * 45
        volume_score = df["거래량"].rank(pct=True) * 30
        change_score = (
            (df["등락률"] - min_change) / max(max_change - min_change, 0.1)
        ).clip(0, 1) * 25
        df["검색점수"] = (value_score + volume_score + change_score).round().astype(int)
        df = df.sort_values(
            ["검색점수", "거래대금(억)"], ascending=False
        ).head(top_n)

    return df, failures


with st.sidebar:
    st.header("검색 조건")
    market = st.radio("시장", ["전체", "코스피", "코스닥"])
    min_price = st.number_input("최소 현재가", 0, 1_000_000, 1_000, 500)
    min_change = st.number_input("최소 상승률 %", -30.0, 30.0, 2.0, 0.5)
    max_change = st.number_input("최대 상승률 %", -30.0, 30.0, 15.0, 0.5)
    min_value = st.number_input("최소 거래대금 추정(억원)", 0, 100_000, 50, 10)
    top_n = st.slider("표시 종목", 10, 100, 30, 10)

st.info("공개 웹 시세 기반입니다. 증권사 실시간 체결 데이터와 차이가 있을 수 있습니다.")

if st.button("🔎 지금 단타 후보 찾기", type="primary", use_container_width=True):
    with st.spinner("코스피·코스닥 시세를 확인하고 있습니다..."):
        try:
            scan, failures = run_scan(
                market, min_price, min_change, max_change, min_value, top_n
            )
            st.session_state["scan"] = scan
            st.session_state["scan_error"] = None
            st.session_state["partial_failures"] = failures
        except Exception as e:
            st.session_state["scan"] = pd.DataFrame()
            st.session_state["scan_error"] = str(e)
            st.session_state["partial_failures"] = []

error = st.session_state.get("scan_error")
if error:
    st.error("종목 데이터를 가져오지 못했습니다.")
    st.warning(
        "이 오류가 Streamlit Cloud에서만 반복된다면 공개 시세 사이트가 "
        "클라우드 서버 IP 요청을 제한하는 경우일 수 있습니다."
    )
    with st.expander("오류 상세"):
        st.code(error)

df = st.session_state.get("scan", pd.DataFrame())
partial = st.session_state.get("partial_failures", [])

if partial and not df.empty:
    st.warning("일부 시장 데이터는 불러오지 못해, 성공한 시장 데이터만 표시합니다.")
    with st.expander("일부 오류 상세"):
        st.code("\n".join(partial))

if not df.empty:
    st.success(f"🔥 후보 {len(df)}종목")
    show = df[
        ["시장", "종목명", "현재가", "등락률", "거래량", "거래대금(억)", "검색점수"]
    ].copy()
    show["현재가"] = show["현재가"].map(lambda x: f"{x:,.0f}원")
    show["등락률"] = show["등락률"].map(lambda x: f"{x:+.2f}%")
    show["거래량"] = show["거래량"].map(lambda x: f"{x:,.0f}")
    show["거래대금(억)"] = show["거래대금(억)"].map(lambda x: f"{x:,.0f}억")
    st.dataframe(show, hide_index=True, use_container_width=True, height=650)
    st.caption("검색점수는 후보 정렬용이며 매수·매도 추천이 아닙니다.")
elif "scan" in st.session_state and not error:
    st.warning("현재 설정한 조건에 맞는 종목이 없습니다.")

st.caption("공개 웹 데이터는 지연되거나 제공 방식이 변경될 수 있습니다.")
