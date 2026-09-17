import streamlit as st
import pandas as pd
import requests

st.set_page_config(
    page_title="단타포착",
    page_icon="🔥",
    layout="wide"
)

st.title("🔥 한국주식 단타포착")
st.caption("갤럭시 Chrome · 증권사 API Key 없음 · 조회/검색 전용")


def num(v):
    if v is None:
        return None

    try:
        return float(
            str(v)
            .replace(",", "")
            .replace("%", "")
            .replace("+", "")
            .strip()
        )
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=60)
def load_market(market):

    url = (
        "https://m.stock.naver.com/front-api/"
        "stock/domestic/stockList"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://m.stock.naver.com/"
    }

    rows = []

    for page in range(1, 21):

        params = {
            "sortType": "marketValue",
            "category": market,
            "page": page,
            "pageSize": 100
        }

        try:
            r = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=10
            )

            r.raise_for_status()
            data = r.json()

            stocks = (
                data.get("stocks")
                or data.get("result")
                or data.get("stockList")
                or []
            )

            if isinstance(stocks, dict):
                stocks = (
                    stocks.get("stocks")
                    or stocks.get("result")
                    or stocks.get("items")
                    or []
                )

            if not stocks:
                break

            for x in stocks:

                name = (
                    x.get("stockName")
                    or x.get("name")
                )

                price = num(
                    x.get("closePrice")
                    or x.get("currentPrice")
                )

                rate = num(
                    x.get("fluctuationsRatio")
                    or x.get("changeRate")
                )

                volume = num(
                    x.get("accumulatedTradingVolume")
                    or x.get("tradingVolume")
                )

                value = num(
                    x.get("accumulatedTradingValue")
                    or x.get("tradingValue")
                )

                if (
                    not name
                    or price is None
                    or rate is None
                    or volume is None
                ):
                    continue

                rows.append({
                    "시장": market,
                    "종목명": name,
                    "현재가": price,
                    "등락률": rate,
                    "거래량": volume,
                    "거래대금원": value
                })

        except Exception:
            continue

    return pd.DataFrame(rows)


with st.sidebar:

    st.header("검색 조건")

    market = st.radio(
        "시장",
        ["전체", "코스피", "코스닥"]
    )

    min_price = st.number_input(
        "최소 현재가",
        0,
        1000000,
        1000,
        500
    )

    min_change = st.number_input(
        "최소 상승률 %",
        -30.0,
        30.0,
        2.0,
        0.5
    )

    max_change = st.number_input(
        "최대 상승률 %",
        -30.0,
        30.0,
        15.0,
        0.5
    )

    min_value = st.number_input(
        "최소 거래대금 추정(억원)",
        0,
        100000,
        50,
        10
    )

    top_n = st.slider(
        "표시 종목",
        10,
        100,
        30,
        10
    )


st.info(
    "공개 웹 시세 기반입니다. "
    "증권사 실시간 체결 데이터와 차이가 있을 수 있습니다."
)


if st.button(
    "🔎 지금 단타 후보 찾기",
    type="primary",
    use_container_width=True
):

    frames = []

    with st.spinner("종목을 불러오고 있습니다..."):

        if market in ("전체", "코스피"):
            x = load_market("KOSPI")

            if not x.empty:
                frames.append(x)

        if market in ("전체", "코스닥"):
            x = load_market("KOSDAQ")

            if not x.empty:
                frames.append(x)

    if not frames:

        st.session_state.scan = pd.DataFrame()

        st.error(
            "종목 데이터를 가져오지 못했습니다."
        )

    else:

        df = pd.concat(
            frames,
            ignore_index=True
        )

        for col in [
            "현재가",
            "등락률",
            "거래량",
            "거래대금원"
        ]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        calc_value = (
            df["현재가"] * df["거래량"]
        )

        df["거래대금원"] = (
            df["거래대금원"]
            .fillna(calc_value)
        )

        df["거래대금(억)"] = (
            df["거래대금원"]
            / 100_000_000
        )

        df = df[
            (df["현재가"] >= min_price)
            & df["등락률"].between(
                min_change,
                max_change
            )
            & (
                df["거래대금(억)"]
                >= min_value
            )
        ].copy()

        if not df.empty:

            a = (
                df["거래대금(억)"]
                .rank(pct=True) * 45
            )

            b = (
                df["거래량"]
                .rank(pct=True) * 30
            )

            c = (
                (
                    (df["등락률"] - min_change)
                    / max(
                        max_change - min_change,
                        0.1
                    )
                )
                .clip(0, 1)
                * 25
            )

            df["검색점수"] = (
                a + b + c
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

    show["거래대금(억)"] = (
        show["거래대금(억)"].map(
            lambda x: f"{x:,.0f}억"
        )
    )

    st.dataframe(
        show,
        hide_index=True,
        use_container_width=True
    )

    st.caption(
        "검색점수는 후보 정렬용이며 "
        "매수·매도 추천이 아닙니다."
    )


elif "scan" in st.session_state:

    st.warning(
        "현재 조건에 맞는 종목이 없거나 "
        "종목 데이터를 가져오지 못했습니다."
    )


st.caption(
    "공개 웹 데이터는 지연되거나 "
    "제공 방식이 변경될 수 있습니다."
)
