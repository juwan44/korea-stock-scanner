import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="단타포착",
    page_icon="🔥",
    layout="wide"
)

st.title("🔥 한국주식 단타포착")
st.caption("갤럭시 Chrome · 증권사 API Key 없음 · 조회/검색 전용")


# -----------------------------
# 숫자 변환
# -----------------------------
def to_number(value):
    if value is None:
        return None

    text = (
        str(value)
        .replace(",", "")
        .replace("%", "")
        .replace("+", "")
        .strip()
    )

    try:
        return float(text)
    except (ValueError, TypeError):
        return None


# -----------------------------
# 네이버 금융 시장 데이터
# -----------------------------
@st.cache_data(ttl=60)
def load_market(market):

    rows = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Mobile Safari/537.36"
        ),
        "Referer": "https://finance.naver.com/"
    }

    session = requests.Session()
    session.headers.update(headers)

    for page in range(1, 21):

        url = (
            "https://finance.naver.com/sise/"
            f"sise_market_sum.naver?sosok={market}&page={page}"
        )

        try:
            response = session.get(url, timeout=10)
            response.raise_for_status()

            # 네이버 금융 한글 인코딩
            response.encoding = "euc-kr"

            soup = BeautifulSoup(response.text, "html.parser")

            table = soup.select_one("table.type_2")

            # 해당 페이지에서 표를 못 찾으면
            # 전체 검색을 죽이지 않고 다음 페이지 진행
            if table is None:
                continue

            for tr in table.select("tr"):

                name_tag = tr.select_one("a.tltle")

                if name_tag is None:
                    continue

                cells = tr.find_all("td")

                # 정상 종목 행은 충분한 td를 가지고 있음
                if len(cells) < 10:
                    continue

                name = name_tag.get_text(strip=True)

                # 네이버 시장총액 페이지 기준
                price = to_number(cells[1].get_text(strip=True))
                change_rate = to_number(cells[3].get_text(strip=True))
                volume = to_number(cells[9].get_text(strip=True))

                if (
                    price is None
                    or change_rate is None
                    or volume is None
                ):
                    continue

                rows.append({
                    "시장": "KOSPI" if market == 0 else "KOSDAQ",
                    "종목명": name,
                    "현재가": price,
                    "등락률": change_rate,
                    "거래량": volume,
                })

        except requests.RequestException:
            # 특정 페이지 오류 때문에 전체 검색이
            # 중단되지 않도록 다음 페이지로 진행
            continue

    return pd.DataFrame(rows)


# -----------------------------
# 사이드바
# -----------------------------
with st.sidebar:

    st.header("검색 조건")

    market = st.radio(
        "시장",
        ["전체", "코스피", "코스닥"]
    )

    min_price = st.number_input(
        "최소 현재가",
        min_value=0,
        max_value=1_000_000,
        value=1_000,
        step=500
    )

    min_change = st.number_input(
        "최소 상승률 %",
        min_value=-30.0,
        max_value=30.0,
        value=2.0,
        step=0.5
    )

    max_change = st.number_input(
        "최대 상승률 %",
        min_value=-30.0,
        max_value=30.0,
        value=15.0,
        step=0.5
    )

    min_value = st.number_input(
        "최소 거래대금 추정(억원)",
        min_value=0,
        max_value=100_000,
        value=50,
        step=10
    )

    top_n = st.slider(
        "표시 종목",
        min_value=10,
        max_value=100,
        value=30,
        step=10
    )


st.info(
    "API 키가 필요 없습니다. 공개 웹 시세 기반이라 "
    "증권사 실시간 체결강도/분봉과는 다를 수 있습니다."
)


# -----------------------------
# 검색 버튼
# -----------------------------
if st.button(
    "🔎 지금 단타 후보 찾기",
    type="primary",
    use_container_width=True
):

    try:

        frames = []

        with st.spinner("코스피·코스닥 시세를 확인하고 있습니다..."):

            if market in ("전체", "코스피"):

                kospi = load_market(0)

                if not kospi.empty:
                    frames.append(kospi)

            if market in ("전체", "코스닥"):

                kosdaq = load_market(1)

                if not kosdaq.empty:
                    frames.append(kosdaq)

        # 아무 시장 데이터도 못 받은 경우
        if not frames:

            st.session_state.scan = pd.DataFrame()

            st.error(
                "네이버 금융에서 종목 데이터를 가져오지 못했습니다."
            )

            st.info(
                "잠시 후 다시 시도해 주세요. "
                "웹사이트의 응답 방식이 변경됐을 수도 있습니다."
            )

        else:

            df = pd.concat(
                frames,
                ignore_index=True
            )

            # 거래대금 추정
            df["거래대금(억)"] = (
                df["현재가"] *
                df["거래량"] /
                100_000_000
            )

            # 검색 조건
            df = df[
                (df["현재가"] >= min_price)
                &
                (df["등락률"].between(
                    min_change,
                    max_change
                ))
                &
                (df["거래대금(억)"] >= min_value)
            ].copy()

            # 후보 점수
            if not df.empty:

                value_score = (
                    df["거래대금(억)"]
                    .rank(pct=True) * 45
                )

                volume_score = (
                    df["거래량"]
                    .rank(pct=True) * 30
                )

                change_score = (
                    (
                        (df["등락률"] - min_change)
                        /
                        max(
                            max_change - min_change,
                            0.1
                        )
                    )
                    .clip(0, 1)
                    * 25
                )

                df["검색점수"] = (
                    value_score
                    + volume_score
                    + change_score
                ).round().astype(int)

                df = (
                    df.sort_values(
                        [
                            "검색점수",
                            "거래대금(억)"
                        ],
                        ascending=False
                    )
                    .head(top_n)
                )

            st.session_state.scan = df

    except Exception as e:

        st.session_state.scan = pd.DataFrame()

        st.error(
            "시세 처리 중 오류가 발생했습니다."
        )

        st.code(
            f"{type(e).__name__}: {e}"
        )


# -----------------------------
# 결과 표시
# -----------------------------
df = st.session_state.get(
    "scan",
    pd.DataFrame()
)

if not df.empty:

    st.success(
        f"🔥 후보 {len(df)}종목"
    )

    show = df[
        [
            "시장",
            "종목명",
            "현재가",
            "등락률",
            "거래량",
            "거래대금(억)",
            "검색점수"
        ]
    ].copy()

    show["현재가"] = show["현재가"].map(
        lambda x: f"{x:,.0f}원"
    )

    show["등락률"] = show["등락률"].map(
        lambda x: f"{x:+.2f}%"
    )

    show["거래량"] = show["거래량"].map(
        lambda x: f"{x:,.0f}"
    )

    show["거래대금(억)"] = show[
        "거래대금(억)"
    ].map(
        lambda x: f"{x:,.0f}억"
    )

    st.dataframe(
        show,
        hide_index=True,
        use_container_width=True,
        height=650
    )

    st.caption(
        "검색점수는 후보 정렬용이며 "
        "매수·매도 추천이 아닙니다."
    )

elif "scan" in st.session_state:

    st.warning(
        "현재 조건에 맞는 종목이 없거나 "
        "시세 데이터를 가져오지 못했습니다."
    )


st.caption(
    "공개 웹 시세는 지연되거나 "
    "제공 방식이 변경될 수 있습니다."
)
