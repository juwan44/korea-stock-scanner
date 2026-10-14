import re
import time
from io import StringIO
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title='단타포착', page_icon='🔥', layout='wide')
st.title('🔥 한국주식 단타포착')
st.caption('코스피·코스닥 공개 웹 시세 · 조회/검색 전용 · 실시간 체결 정보 아님')

URL = 'https://finance.naver.com/sise/sise_market_sum.naver'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Referer': 'https://finance.naver.com/',
}
COLUMNS = ['시장', '종목명', '현재가', '등락률', '거래량']


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(total=2, connect=2, read=2, backoff_factor=0.7,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=['GET'], respect_retry_after_header=True)
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def clean_num(values):
    return pd.to_numeric(values.astype(str).str.replace(r'[,％%+\s]', '', regex=True)
                         .str.replace('−', '-', regex=False).str.replace('▲', '', regex=False)
                         .str.replace('▼', '-', regex=False), errors='coerce')


def parse_page(html, market_name):
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.select_one('table.type_2')
    if table is None:
        raise ValueError('시세 표(table.type_2)가 없습니다. 사이트 구조 또는 접근 제한을 확인하세요.')
    records = []
    for tr in table.select('tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) < 10:
            continue
        link = tr.select_one('a[href*="/item/main.naver?code="]')
        if link is None:
            continue
        # 네이버 시가총액 표: N, 종목명, 현재가, 전일비, 등락률, 액면가, 시총, 상장주식수, 외국인비율, 거래량 ...
        try:
            name = link.get_text(' ', strip=True)
            price = cells[2].get_text(' ', strip=True)
            change = cells[4].get_text(' ', strip=True)
            volume = cells[9].get_text(' ', strip=True)
            if name:
                records.append([market_name, name, price, change, volume])
        except (IndexError, AttributeError):
            continue
    if not records:
        raise ValueError('표는 있으나 유효한 종목 행이 없습니다. HTML 구조 변경 가능성')
    df = pd.DataFrame(records, columns=COLUMNS)
    # 마지막 페이지 탐색: 페이지 링크의 최대 번호 (없는 경우 수집 종목의 반복으로 종료)
    page_numbers = []
    for a in soup.select('td.pgRR a, td.pgR a, table.Nnavi a, a[href*="page="]'):
        match = re.search(r'[?&]page=(\d+)', a.get('href', ''))
        if match:
            page_numbers.append(int(match.group(1)))
    return df, max(page_numbers, default=None)


@st.cache_data(ttl=120, show_spinner=False)
def load_market(market):
    name = 'KOSPI' if market == 0 else 'KOSDAQ'
    frames = []
    seen = set()
    warnings = []
    with make_session() as session:
        for page in range(1, 81):
            try:
                response = session.get(URL, params={'sosok': market, 'page': page}, timeout=(6, 15))
                if response.status_code in (403, 429):
                    raise RuntimeError(f'HTTP {response.status_code}: 네이버 금융에서 서버 접근을 제한했습니다. 코드만으로 우회할 수 없습니다.')
                response.raise_for_status()
                response.encoding = 'euc-kr'  # 네이버 금융 PC 페이지 인코딩
                part, last_page_hint = parse_page(response.text, name)
                new = part.loc[~part['종목명'].isin(seen)].copy()
                if new.empty:
                    break  # 같은 데이터 반복: 마지막 페이지를 지난 것으로 판단
                seen.update(new['종목명'])
                frames.append(new)
                if last_page_hint is not None and page >= last_page_hint:
                    break
                time.sleep(0.15)
            except Exception as exc:
                message = f'{name} {page}페이지: {type(exc).__name__}: {exc}'
                if not frames:
                    raise RuntimeError(message) from exc
                warnings.append('일부 페이지를 수집하지 못했습니다. ' + message)
                break
    if not frames:
        raise RuntimeError(f'{name}: 수집된 종목이 없습니다.')
    return pd.concat(frames, ignore_index=True), warnings


def scan_stocks(market, min_price, min_change, max_change, min_value, top_n):
    if min_change > max_change:
        raise ValueError('최소 상승률은 최대 상승률 이하여야 합니다.')
    targets = ([0, 1] if market == '전체' else [0] if market == '코스피' else [1])
    frames, warnings = [], []
    for target in targets:
        try:
            frame, issues = load_market(target)
            frames.append(frame)
            warnings.extend(issues)
        except Exception as exc:
            warnings.append(str(exc))
    if not frames:
        raise RuntimeError('\n'.join(warnings))
    df = pd.concat(frames, ignore_index=True).drop_duplicates(['시장', '종목명'])
    for col in ['현재가', '등락률', '거래량']:
        df[col] = clean_num(df[col])
    df = df.dropna(subset=['현재가', '등락률', '거래량'])
    df = df[(df['현재가'] > 0) & (df['거래량'] >= 0)].copy()
    df['거래대금(억)'] = df['현재가'] * df['거래량'] / 100_000_000
    df = df[(df['현재가'] >= min_price) & df['등락률'].between(min_change, max_change)
            & (df['거래대금(억)'] >= min_value)].copy()
    if not df.empty:
        value_score = df['거래대금(억)'].rank(pct=True) * 45
        volume_score = df['거래량'].rank(pct=True) * 30
        change_score = ((df['등락률'] - min_change) / max(max_change - min_change, 0.1)).clip(0, 1) * 25
        df['검색점수'] = (value_score + volume_score + change_score).round().astype(int)
        df = df.sort_values(['검색점수', '거래대금(억)'], ascending=False).head(top_n)
    return df, warnings


with st.sidebar:
    st.header('검색 조건')
    market = st.radio('시장', ['전체', '코스피', '코스닥'])
    min_price = st.number_input('최소 현재가(원)', min_value=0, max_value=1_000_000, value=1_000, step=500)
    min_change = st.number_input('최소 상승률(%)', min_value=-30.0, max_value=30.0, value=2.0, step=0.5)
    max_change = st.number_input('최대 상승률(%)', min_value=-30.0, max_value=30.0, value=15.0, step=0.5)
    min_value = st.number_input('최소 추정 거래대금(억원)', min_value=0, max_value=100_000, value=50, step=10)
    top_n = st.slider('표시 종목', 10, 100, 30, 10)
    refresh = st.checkbox('캐시 무시하고 새로 수집', value=False)

st.info('현재가 × 누적 거래량은 실제 거래대금이 아닌 추정치입니다. 시세는 지연될 수 있습니다.')
if st.button('🔎 지금 단타 후보 찾기', type='primary', use_container_width=True):
    if refresh:
        load_market.clear()
    with st.spinner('공개 시세를 조회하고 있습니다...'):
        try:
            results, warnings = scan_stocks(market, min_price, min_change, max_change, min_value, top_n)
            st.session_state['scan'] = results
            st.session_state['warnings'] = warnings
            st.session_state['error'] = None
        except Exception as exc:
            st.session_state['scan'] = pd.DataFrame()
            st.session_state['warnings'] = []
            st.session_state['error'] = str(exc)

if st.session_state.get('error'):
    st.error('시세 수집 실패: 아래 상세 오류를 확인하세요.')
    st.code(st.session_state['error'])
    st.warning('HTTP 403/429라면 Streamlit Cloud IP가 차단된 것일 수 있습니다. 이 경우 공식 데이터 API 등 데이터 공급원 변경이 필요합니다.')
for warning in st.session_state.get('warnings', []):
    st.warning(warning)

df = st.session_state.get('scan', pd.DataFrame())
if not df.empty:
    st.success(f'🔥 후보 {len(df)}종목')
    show = df[['시장', '종목명', '현재가', '등락률', '거래량', '거래대금(억)', '검색점수']].copy()
    show['현재가'] = show['현재가'].map(lambda x: f'{x:,.0f}원')
    show['등락률'] = show['등락률'].map(lambda x: f'{x:+.2f}%')
    show['거래량'] = show['거래량'].map(lambda x: f'{x:,.0f}')
    show['거래대금(억)'] = show['거래대금(억)'].map(lambda x: f'{x:,.0f}억')
    st.dataframe(show, hide_index=True, use_container_width=True, height=650)
    st.caption('검색점수는 후보 정렬용이며 매수·매도 추천이 아닙니다.')
elif 'scan' in st.session_state and not st.session_state.get('error'):
    st.warning('현재 조건에 맞는 종목이 없습니다. 검색 조건을 완화해 보세요.')
