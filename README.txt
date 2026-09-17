단타포착 배포 안내

1. GitHub 저장소의 app.py를 이 파일로 교체합니다.
2. requirements.txt도 함께 교체합니다.
3. Streamlit Community Cloud에서 앱을 Reboot합니다.
4. Secrets/API Key는 필요 없습니다.

이번 버전의 주요 수정:
- 빈 DataFrame을 pd.concat()해서 앱이 죽는 문제 수정
- HTTP 403/429/timeout을 구분해 오류 상세 표시
- pandas.read_html 실패 시 BeautifulSoup 파서로 2차 처리
- 한 시장이 실패해도 다른 시장 데이터는 표시
- 중복 종목 제거, 숫자 파싱/빈 데이터 방어
- 3분 캐시로 불필요한 반복 요청 감소

중요:
Streamlit Cloud에서만 HTTP 403이 계속 발생하면 앱 코드 문제가 아니라
공개 시세 제공자가 클라우드 서버 IP 요청을 제한하는 상황일 수 있습니다.
그 경우 API Key 없는 '웹 스크래핑만으로 100% 보장'은 불가능하며,
데이터 소스 또는 배포 위치를 바꿔야 합니다.
