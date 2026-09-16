KB 단타포착 - Streamlit

1) Streamlit Cloud > App > Settings > Secrets 에 입력:
KB_APP_KEY = "본인의 KB App Key"
KB_APP_SECRET = "본인의 KB App Secret"

2) GitHub의 app.py를 이 파일로 교체하고 재부팅합니다.
3) 'KB API 인증 테스트'를 눌러 Access Token 발급 성공을 확인합니다.
4) KB Open API 포털 > API문서 > 국내주식에서 사용할 순위/시세 API의 경로와 Request JSON을 앱 고급설정에 넣습니다.

주의: 키를 GitHub 코드에 직접 적지 마세요.
