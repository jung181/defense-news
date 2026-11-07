# 네이버 뉴스 → Notion 수집기 (개인 열람용)

방산·항공우주·에너지·지정학 키워드로 네이버 뉴스 검색 결과를 매일 자동 수집해
Notion DB에 **원시 정보만**(제목/링크/발행일/분야/검색어) 저장합니다.

이 저장소(GitHub Actions)는 **1단계(수집)만** 담당합니다. 네이버 API 응답
데이터는 가공하지 않고 그대로 저장하며, 기사 본문을 가져오거나 AI로
요약하지 않습니다 (네이버 API HUB 약관: 응답 데이터의 AI 입력/가공 금지).

**2단계(원문 열람 → 기자명·언론사·3줄 요약 작성)**는 별도로, 매일 아침
Claude 예약 작업이 이 DB에서 아직 보강되지 않은 행을 찾아 원문 페이지를
직접 읽고 채웁니다. 이 저장소의 스크립트는 그 단계에 관여하지 않습니다.

## 설정

GitHub 저장소 Settings → Secrets and variables → Actions 에 아래 4개를 등록:

| Secret | 값 |
|---|---|
| `NCP_APIHUB_CLIENT_ID` | NAVER API HUB Client ID |
| `NCP_APIHUB_CLIENT_SECRET` | NAVER API HUB Client Secret |
| `NOTION_TOKEN` | Notion 내부 연동(naver-news-writer) 토큰 |
| `NOTION_DATABASE_ID` | 대상 Notion 데이터베이스 ID |

`.github/workflows/daily.yml`이 매일 20:30 UTC(05:30 KST)에 자동 실행됩니다.
Actions 탭에서 "Run workflow"로 수동 실행도 가능합니다.

## 약관 준수

- 네이버 API 응답(title/link/pubDate)을 가공 없이 그대로 저장합니다.
- 21일이 지난 행은 매 실행 시 자동으로 Notion 휴지통에 보관(archive) 처리됩니다
  (네이버 API HUB 약관상 이력 조회 목적 서버 보관은 최대 21일).
- API 응답 데이터를 AI 요약·학습·평가에 사용하지 않습니다.
