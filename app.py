import streamlit as st
import pandas as pd
import requests
from datetime import datetime

st.set_page_config(page_title="KB 단타포착", page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1rem;padding-left:.7rem;padding-right:.7rem}
.stButton button{width:100%;height:3rem;font-weight:700}
</style>
""", unsafe_allow_html=True)

st.title("📈 KB 단타포착 V2")
st.caption("갤럭시 · Streamlit 모바일용 / KB증권 Open API")

BASE_URL = "https://developer.kbsec.com:32484"
TOKEN_URL = BASE_URL + "/oauth2/token"

def get_secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default

with st.sidebar:
    st.header("KB증권 API 설정")
    saved_key = get_secret("KB_APP_KEY")
    saved_secret = get_secret("KB_APP_SECRET")

    app_key = st.text_input("App Key", value=saved_key, type="password")
    app_secret = st.text_input("App Secret", value=saved_secret, type="password")
    st.caption("권장: Streamlit Settings → Secrets에 KB_APP_KEY / KB_APP_SECRET 저장")

    st.divider()
    st.header("검색 조건")
    min_change = st.number_input("최소 등락률(%)", -30.0, 30.0, 2.0, .5)
    max_change = st.number_input("최대 등락률(%)", -30.0, 30.0, 15.0, .5)
    min_value_uk = st.number_input("최소 거래대금(억원)", 0, 100000, 50, 10)
    min_strength = st.number_input("최소 체결강도(%)", 0, 1000, 120, 10)
    high_gap = st.number_input("고가 대비 최대 이격(%)", 0.0, 30.0, 3.0, .5)

def clean_credential(value):
    # TOML의 바깥 따옴표는 st.secrets가 제거한다.
    # 실수로 값 자체에 따옴표/공백을 넣은 경우만 정리한다.
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value

def request_token(key, secret_key):
    key = clean_credential(key)
    secret_key = clean_credential(secret_key)

    if not key or not secret_key:
        return None, {
            "kind": "local",
            "message": "App Key 또는 App Secret이 비어 있습니다."
        }

    payload = {
        "grant_type": "client_credentials",
        "appKey": key,
        "appSecret": secret_key,
    }

    try:
        r = requests.post(
            TOKEN_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=20,
        )

        try:
            data = r.json()
        except Exception:
            return None, {
                "kind": "http",
                "status": r.status_code,
                "message": r.text[:1000],
            }

        # KB 응답은 환경/버전에 따라 top-level 또는 dataBody 안에 토큰이 올 수 있어 둘 다 처리
        body = data.get("dataBody") if isinstance(data, dict) else None
        body = body if isinstance(body, dict) else {}
        token = body.get("access_token") or (data.get("access_token") if isinstance(data, dict) else None)

        if r.ok and token:
            return token, None

        header = data.get("dataHeader", {}) if isinstance(data, dict) else {}
        return None, {
            "kind": "kb",
            "status": r.status_code,
            "processCode": header.get("processCode"),
            "resultCode": header.get("resultCode"),
            "message": header.get("processMessage")
                       or body.get("error_description")
                       or body.get("message")
                       or data.get("message")
                       or str(data),
        }

    except requests.RequestException as e:
        return None, {"kind": "network", "message": str(e)}

def kb_post(path, token, body):
    r = requests.post(
        BASE_URL + path,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return r.status_code, data

def parse_json(txt):
    import json
    try:
        return json.loads(txt) if txt.strip() else {}
    except Exception:
        return None

def normalize_rows(data):
    lists = []
    def walk(x):
        if isinstance(x, list) and x and isinstance(x[0], dict):
            lists.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
    walk(data)
    if not lists:
        return pd.DataFrame()

    df = pd.DataFrame(max(lists, key=len))
    aliases = {
        "종목코드":["isu_cd","is_cd","stk_cd","stck_shrn_iscd","code","종목코드"],
        "종목명":["isu_nm","is_nm","stk_nm","hts_kor_isnm","name","종목명"],
        "현재가":["cur_prc","now_prc","stck_prpr","price","현재가"],
        "등락률":["updn_rt","flu_rt","prdy_ctrt","change_rate","등락률"],
        "거래량":["trd_qty","trde_qty","acml_vol","volume","거래량"],
        "거래대금":["trd_amt","trde_prica","acml_tr_pbmn","trade_value","거래대금"],
        "체결강도":["cntr_str","exec_str","tday_rltv","strength","체결강도"],
        "고가":["high_prc","high_pric","stck_hgpr","high","고가"],
    }
    out = pd.DataFrame(index=df.index)
    for dst, cands in aliases.items():
        src = next((c for c in cands if c in df.columns), None)
        out[dst] = df[src] if src else None
    return out

def num(s):
    return pd.to_numeric(
        s.astype(str)
         .str.replace(",", "", regex=False)
         .str.replace("+", "", regex=False)
         .str.replace("%", "", regex=False),
        errors="coerce",
    )

def score_frame(df):
    if df.empty:
        return df
    for c in ["현재가","등락률","거래량","거래대금","체결강도","고가"]:
        df[c] = num(df[c]).abs()

    df["고가이격%"] = ((df["고가"] - df["현재가"]) / df["고가"] * 100).clip(lower=0)
    df["거래대금억원"] = df["거래대금"] / 100_000_000

    v_norm = df["거래대금"].fillna(0).rank(pct=True) * 30
    vol_norm = df["거래량"].fillna(0).rank(pct=True) * 20
    str_norm = (df["체결강도"].fillna(0) / 200).clip(0,1) * 20
    high_norm = (1 - df["고가이격%"].fillna(100) / max(high_gap,.1)).clip(0,1) * 15
    chg_norm = (df["등락률"].fillna(0) / max(max_change,.1)).clip(0,1) * 15
    df["점수"] = (v_norm + vol_norm + str_norm + high_norm + chg_norm).round()

    mask = df["등락률"].between(min_change, max_change)
    if df["체결강도"].notna().any():
        mask &= df["체결강도"].fillna(0) >= min_strength
    if df["고가"].notna().any():
        mask &= df["고가이격%"].fillna(999) <= high_gap
    if df["거래대금"].notna().any():
        mask &= df["거래대금억원"].fillna(0) >= min_value_uk
    return df[mask].sort_values(["점수","거래대금"], ascending=False)

st.subheader("1. KB 인증 확인")

key_clean = clean_credential(app_key)
secret_clean = clean_credential(app_secret)

c1, c2, c3 = st.columns(3)
c1.metric("App Key", "입력됨" if key_clean else "없음")
c2.metric("App Secret", "입력됨" if secret_clean else "없음")
c3.metric("현재 시각", datetime.now().strftime("%H:%M:%S"))

# 키 원문은 절대 표시하지 않고 길이만 진단용으로 표시
st.caption(
    f"인증정보 감지: App Key {len(key_clean)}자 / App Secret {len(secret_clean)}자 "
    "(실제 값은 화면에 표시하지 않습니다.)"
)

if st.button("🔐 KB API 인증 테스트", type="primary"):
    token, err = request_token(app_key, app_secret)

    if token:
        st.success("✅ KB증권 Access Token 발급 성공!")
    else:
        st.error("❌ KB 인증 실패")
        if err.get("processCode") == "E021":
            st.warning(
                "KB 오류 E021: 서버가 전달받은 App Key로 앱 정보를 찾지 못했습니다. "
                "코드는 KB 공식 Client Credentials 형식으로 요청하고 있으므로, "
                "KB Open API 포털에서 Open API 신청 완료 여부와 발급된 App Key를 다시 확인하세요."
            )
        st.json(err)

st.subheader("2. 단타 검색 API 연결")
st.info(
    "인증이 성공한 다음 KB Open API 문서의 국내주식 순위/시세 API를 연결합니다. "
    "API별 경로와 요청 필드는 서로 달라 임의의 TR 값을 넣지 않습니다."
)

with st.expander("고급 설정 — KB 국내주식 순위/시세 API", expanded=True):
    api_path = st.text_input(
        "API 경로",
        value=get_secret("KB_SCAN_API_PATH", ""),
        placeholder="/api/v1/..."
    )
    body_text = st.text_area(
        "요청 JSON",
        value=get_secret("KB_SCAN_BODY", "{}"),
        height=160
    )

run = st.button("🔥 지금 단타 종목 찾기", type="primary")

if "last_df" not in st.session_state:
    st.session_state.last_df = pd.DataFrame()

if run:
    token, err = request_token(app_key, app_secret)
    if err:
        st.error("먼저 KB 인증을 해결해야 합니다.")
        st.json(err)
    elif not api_path.strip():
        st.warning("KB 국내주식 API 경로를 입력하세요.")
    else:
        body = parse_json(body_text)
        if body is None:
            st.error("요청 JSON 형식이 올바르지 않습니다.")
        else:
            status, data = kb_post(api_path.strip(), token, body)
            if status >= 400:
                st.error(f"KB API 호출 오류 (HTTP {status})")
                st.json(data)
            else:
                raw = normalize_rows(data)
                if raw.empty:
                    st.warning("응답은 받았지만 종목 목록을 자동으로 찾지 못했습니다.")
                    st.json(data)
                else:
                    st.session_state.last_df = score_frame(raw)

df = st.session_state.last_df
if not df.empty:
    st.subheader(f"🔥 포착 {len(df)}종목")
    for _, r in df.head(30).iterrows():
        name = r.get("종목명") or r.get("종목코드") or "-"
        with st.container(border=True):
            a,b,c = st.columns([1.7,1,1])
            a.markdown(f"### {name}")
            b.metric("등락률", f"+{r['등락률']:.2f}%" if pd.notna(r["등락률"]) else "-")
            c.metric("점수", f"{int(r['점수'])}" if pd.notna(r["점수"]) else "-")
            x,y,z = st.columns(3)
            x.metric("현재가", f"{int(r['현재가']):,}원" if pd.notna(r["현재가"]) else "-")
            y.metric("체결강도", f"{r['체결강도']:.0f}%" if pd.notna(r["체결강도"]) else "-")
            z.metric("고가대비", f"-{r['고가이격%']:.1f}%" if pd.notna(r["고가이격%"]) else "-")
    with st.expander("표로 보기"):
        st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.caption("검색 보조용이며 자동 주문은 실행하지 않습니다.")
