"""
키움 REST API 인증 최소 클라이언트.

주의:
- 이 파일은 인증 토큰 발급부만 공식 문서 사양에 맞춰 구현합니다.
- 실제 실시간 시세/분봉 데이터 매핑은 계정에서 사용하는 API 명세(TR/필드)에 맞춰
  StockSnapshot으로 변환해 scanner.py에 넘기면 됩니다.
- 운영 전에는 반드시 모의투자 서버에서 테스트하세요.
"""
from __future__ import annotations
import os
import requests

class KiwoomRestClient:
    def __init__(self, app_key=None, app_secret=None, mock=True):
        self.app_key = app_key or os.getenv("KIWOOM_APP_KEY")
        self.app_secret = app_secret or os.getenv("KIWOOM_APP_SECRET")
        self.base_url = "https://mockapi.kiwoom.com" if mock else "https://api.kiwoom.com"
        self.token = None

    def issue_token(self):
        if not self.app_key or not self.app_secret:
            raise RuntimeError("KIWOOM_APP_KEY / KIWOOM_APP_SECRET 환경변수를 설정하세요.")
        url = self.base_url + "/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }
        r = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("return_code", 0) != 0:
            raise RuntimeError(data)
        self.token = data["token"]
        return data

    def headers(self, api_id: str, cont_yn="N", next_key=""):
        if not self.token:
            raise RuntimeError("먼저 issue_token()을 호출하세요.")
        return {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": api_id,
        }
