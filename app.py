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
    except:
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

    # 여러 페이지 수집
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

            # 응답 구조가 바뀌어도 최대한 대응
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

                if not name or price is None:
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
