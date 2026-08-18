import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st
import FinanceDataReader as fdr

st.set_page_config(page_title='한국주식 단타·스윙 검색기', page_icon='📈', layout='wide')


def col(df, *names, default=None):
    for n in names:
        if n in df.columns:
            return df[n]
    if default is not None:
        return pd.Series(default, index=df.index)
    return pd.Series(np.nan, index=df.index)


@st.cache_data(ttl=900, show_spinner=False)
def load_listing():
    df = fdr.StockListing('KRX').copy()
    rename = {
        'Code': 'Symbol', 'Ticker': 'Symbol', 'Name': 'Name',
        'Market': 'Market', 'Close': 'Close', 'Marcap': 'Marcap',
        'Volume': 'Volume', 'Amount': 'Amount', 'Changes': 'Change',
        'ChagesRatio': 'ChangeRate', 'ChangesRatio': 'ChangeRate'
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if 'Symbol' not in df.columns:
        raise RuntimeError('KRX 종목코드 컬럼을 찾지 못했습니다.')
    df['Symbol'] = df['Symbol'].astype(str).str.zfill(6)
    for c in ['Close', 'Marcap', 'Volume', 'Amount', 'ChangeRate']:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors='coerce')
    if 'Market' not in df.columns:
        df['Market'] = ''
    if 'Name' not in df.columns:
        df['Name'] = df['Symbol']
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def load_history(symbol: str, days: int = 150):
    start = (datetime.now() - timedelta(days=days * 2)).strftime('%Y-%m-%d')
    df = fdr.DataReader(symbol, start).copy()
    if df.empty:
        return df
    df.columns = [str(c).capitalize() for c in df.columns]
    for c in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.tail(days)


def rsi(series: pd.Series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def analyze(symbol: str, name: str, market: str):
    h = load_history(symbol)
    if h is None or len(h) < 65 or 'Close' not in h.columns or 'Volume' not in h.columns:
        return None

    close = h['Close']
    volume = h['Volume']
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    vol20 = volume.rolling(20).mean()
    rsi14 = rsi(close)

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else last
    day_ret = (last / prev - 1) * 100 if prev else 0
    mom5 = (last / close.iloc[-6] - 1) * 100 if len(close) > 6 else np.nan
    mom20 = (last / close.iloc[-21] - 1) * 100 if len(close) > 21 else np.nan
    vr = float(volume.iloc[-1] / vol20.iloc[-1]) if pd.notna(vol20.iloc[-1]) and vol20.iloc[-1] > 0 else np.nan
    high20 = float(h['High'].rolling(20).max().iloc[-1]) if 'High' in h.columns else float(close.rolling(20).max().iloc[-1])
    near_high = (last / high20) * 100 if high20 else np.nan
    volatility = float(close.pct_change().tail(20).std() * np.sqrt(252) * 100)
    trend = bool(last > ma20.iloc[-1] > ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else False
    short_trend = bool(last > ma5.iloc[-1] > ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else False
    rv = float(rsi14.iloc[-1]) if pd.notna(rsi14.iloc[-1]) else np.nan

    # 단타 점수: 거래량 급증 + 단기 추세 + 당일/5일 모멘텀 + 과열 억제
    scalp = 0.0
    scalp += np.clip((vr - 1.0) * 22, 0, 35) if pd.notna(vr) else 0
    scalp += 20 if short_trend else 0
    scalp += np.clip(day_ret * 4, 0, 18)
    scalp += np.clip(mom5 * 1.5, 0, 15) if pd.notna(mom5) else 0
    scalp += 8 if 52 <= rv <= 72 else (3 if 45 <= rv < 52 else 0)
    scalp += 4 if near_high >= 96 else 0
    if day_ret > 15 or rv > 80:
        scalp -= 15

    # 스윙 점수: 중기 추세 + 20일 모멘텀 + RSI + 신고가 근접 + 변동성 관리
    swing = 0.0
    swing += 30 if trend else 0
    swing += 12 if short_trend else 0
    swing += np.clip(mom20 * 1.2, 0, 25) if pd.notna(mom20) else 0
    swing += 15 if 50 <= rv <= 68 else (6 if 45 <= rv < 50 else 0)
    swing += 10 if near_high >= 94 else (5 if near_high >= 90 else 0)
    swing += 8 if 12 <= volatility <= 45 else (3 if volatility < 60 else 0)
    if rv > 78:
        swing -= 10

    return {
        '종목코드': symbol, '종목명': name, '시장': market, '현재가': last,
        '당일등락%': round(day_ret, 2), '5일모멘텀%': round(mom5, 2),
        '20일모멘텀%': round(mom20, 2), '거래량배수': round(vr, 2),
        'RSI14': round(rv, 1), '20일고가근접%': round(near_high, 1),
        '연환산변동성%': round(volatility, 1), '단타점수': round(max(0, min(100, scalp)), 1),
        '스윙점수': round(max(0, min(100, swing)), 1),
        '추세상승': trend, '단기추세': short_trend
    }


def format_krw(v):
    if pd.isna(v): return '-'
    return f'{int(v):,}'


st.title('📈 한국주식 단타 · 스윙 모바일 검색기')
st.caption('후보 종목을 빠르게 압축하는 도구입니다. 매수·매도 권유가 아니며, 주문 전 차트/공시/호가를 직접 확인하세요.')

with st.sidebar:
    st.header('검색 조건')
    mode = st.radio('전략', ['단타', '스윙'], horizontal=True)
    markets = st.multiselect('시장', ['KOSPI', 'KOSDAQ'], default=['KOSPI', 'KOSDAQ'])
    min_amount_b = st.slider('최소 거래대금(억원)', 1, 1000, 50, 10)
    min_marcap_b = st.slider('최소 시가총액(억원)', 100, 100000, 1000, 100)
    candidate_n = st.slider('1차 후보 수', 30, 300, 120, 10)
    top_n = st.slider('최종 표시 종목', 5, 50, 15, 5)
    min_score = st.slider('최소 점수', 0, 100, 55, 5)
    st.divider()
    st.caption('처음 실행은 종목별 가격 데이터를 읽기 때문에 다소 느릴 수 있습니다. 이후에는 캐시를 사용합니다.')

try:
    listing = load_listing()
except Exception as e:
    st.error(f'KRX 종목 목록을 불러오지 못했습니다: {e}')
    st.stop()

f = listing.copy()
if markets and 'Market' in f.columns:
    f = f[f['Market'].isin(markets)]

# ETF/ETN/스팩 등은 Name 패턴으로 1차 제외. 사용자가 원하면 쉽게 수정 가능.
exclude = r'스팩|SPAC|ETF|ETN|리츠|REIT|인버스|레버리지'
f = f[~f['Name'].astype(str).str.contains(exclude, case=False, regex=True, na=False)]
f = f[(f['Amount'].fillna(0) >= min_amount_b * 1e8) & (f['Marcap'].fillna(0) >= min_marcap_b * 1e8)]

# 거래대금 우선으로 실제 분석 수를 제한해 모바일/무료 배포 환경에서도 감당 가능하게 함
f = f.sort_values('Amount', ascending=False).head(candidate_n)

run = st.button('🔎 지금 검색', type='primary', use_container_width=True)

if run:
    progress = st.progress(0, text='종목 분석을 시작합니다...')
    rows = []
    total = max(len(f), 1)
    for i, row in enumerate(f.itertuples(index=False), 1):
        symbol = str(getattr(row, 'Symbol')).zfill(6)
        name = str(getattr(row, 'Name'))
        market = str(getattr(row, 'Market'))
        try:
            x = analyze(symbol, name, market)
            if x:
                amount = float(getattr(row, 'Amount')) if pd.notna(getattr(row, 'Amount')) else np.nan
                marcap = float(getattr(row, 'Marcap')) if pd.notna(getattr(row, 'Marcap')) else np.nan
                x['거래대금(억)'] = round(amount / 1e8, 1) if pd.notna(amount) else np.nan
                x['시가총액(억)'] = round(marcap / 1e8, 0) if pd.notna(marcap) else np.nan
                rows.append(x)
        except Exception:
            pass
        progress.progress(i / total, text=f'{i}/{total} 분석 중')
    progress.empty()

    result = pd.DataFrame(rows)
    if result.empty:
        st.warning('조건에 맞는 데이터를 만들지 못했습니다. 조건을 낮추거나 잠시 뒤 다시 시도하세요.')
        st.stop()

    score_col = '단타점수' if mode == '단타' else '스윙점수'
    result = result[result[score_col] >= min_score].sort_values(score_col, ascending=False).head(top_n).reset_index(drop=True)
    result.index = result.index + 1

    st.subheader(f'🔥 {mode} TOP {len(result)}')
    if len(result):
        best = result.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric('1위', f"{best['종목명']} ({best['종목코드']})")
        c2.metric('점수', f"{best[score_col]:.1f}")
        c3.metric('거래량', f"{best['거래량배수']:.2f}배")

        show_cols = ['종목코드','종목명','시장',score_col,'현재가','당일등락%','거래대금(억)','거래량배수','RSI14','5일모멘텀%','20일모멘텀%','20일고가근접%']
        st.dataframe(
            result[show_cols],
            use_container_width=True,
            hide_index=False,
            column_config={
                '현재가': st.column_config.NumberColumn(format='%d원'),
                score_col: st.column_config.ProgressColumn(min_value=0, max_value=100, format='%.1f'),
            },
        )

        csv = result.to_csv(index=False).encode('utf-8-sig')
        st.download_button('📥 검색결과 CSV 저장', csv, file_name=f'krx_{mode}_{datetime.now():%Y%m%d_%H%M}.csv', mime='text/csv', use_container_width=True)

        st.subheader('종목 상세')
        options = {f"{r['종목명']} ({r['종목코드']})": r['종목코드'] for _, r in result.iterrows()}
        picked_label = st.selectbox('상세 종목', list(options.keys()))
        picked = options[picked_label]
        detail = result[result['종목코드'] == picked].iloc[0]
        h = load_history(picked)
        chart = pd.DataFrame({'종가': h['Close'], '20일선': h['Close'].rolling(20).mean(), '60일선': h['Close'].rolling(60).mean()}).tail(100)
        st.line_chart(chart, use_container_width=True)

        reasons = []
        if detail['거래량배수'] >= 1.5: reasons.append(f"거래량 {detail['거래량배수']:.1f}배")
        if detail['단기추세']: reasons.append('5일선 > 20일선 + 종가 상단')
        if detail['추세상승']: reasons.append('20일선 > 60일선 상승추세')
        if detail['20일고가근접%'] >= 94: reasons.append('20일 고가 근접')
        if 50 <= detail['RSI14'] <= 68: reasons.append('RSI 우호 구간')
        st.info('선정 이유: ' + (' · '.join(reasons) if reasons else '복합 점수 기준 통과'))
    else:
        st.info('현재 설정의 최소 점수를 넘는 종목이 없습니다. 최소 점수를 낮춰보세요.')

st.divider()
st.caption('데이터 소스: FinanceDataReader/KRX 기반. 무료 공개 데이터 특성상 실시간 호가 검색기가 아니라 일봉/최근 거래 데이터 기반 후보 압축기입니다.')
