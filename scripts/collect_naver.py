#!/usr/bin/env python3
"""네이버 뉴스(NAVER API HUB) 키워드 수집 -> Notion DB에 '원시 정보'만 기록.

개인 열람용 수집기. 네이버 검색 API가 돌려준 데이터(제목/링크/발행일)는
가공하지 않고 그대로 Notion에 저장한다. AI 요약·기자명·언론사는 여기서
만들지 않는다 (별도 프로세스가 원문을 직접 읽어서 채운다).

네이버 API HUB 약관상 응답 데이터의 서버 보관은 "이력 조회 목적"으로
최대 21일까지만 허용되므로, 21일이 지난 행은 매 실행 시 자동으로
보관(archive) 처리한다 (완전 삭제가 아니라 Notion 휴지통으로 이동).

필요한 환경변수:
  NCP_APIHUB_CLIENT_ID
  NCP_APIHUB_CLIENT_SECRET
  NOTION_TOKEN
  NOTION_DATABASE_ID
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

NAVER_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion 데이터베이스 속성 이름 (만들 때와 동일해야 함)
P_TITLE = "제목"    # title
P_LINK = "링크"     # url
P_DATE = "발행일"   # date
P_FIELD = "분야"    # select
P_QUERY = "검색어"  # rich_text

KST = timezone(timedelta(hours=9))
RETENTION_DAYS = 21  # 네이버 API HUB 약관: 이력 조회 목적 서버 보관 최대 21일

KEYWORDS = {
    "방산": ["방위산업", "방산 수출", "방위사업청", "무기체계 개발"],
    "항공우주": ["항공우주", "우주발사체", "위성 발사", "KF-21"],
    "에너지": ["에너지 정책", "신재생에너지", "원전 SMR", "해상풍력"],
    "지정학": ["지정학 리스크", "우크라이나 전쟁", "중동 정세", "미중 갈등"],
}


def http_json(url, method="GET", headers=None, body=None, retries=3):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = dict(headers or {})
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            last = RuntimeError(f"HTTP {e.code} {url.split('?')[0]} :: {detail}")
            if e.code == 429 or e.code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last
        except urllib.error.URLError as e:
            last = RuntimeError(f"네트워크 오류 {url.split('?')[0]} :: {e.reason}")
            time.sleep(1.5 * (attempt + 1))
    raise last


def clean_title(text):
    """<b> 강조 태그만 제거. 그 외 가공하지 않는다(약관: 독립적으로, 가공 없이 노출)."""
    import html

    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def parse_pub(s):
    try:
        dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def search_news(query, client_id, client_secret, display=30):
    params = urllib.parse.urlencode(
        {"query": query, "display": display, "start": 1, "sort": "date", "format": "json"}
    )
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }
    return http_json(f"{NAVER_URL}?{params}", headers=headers).get("items", [])


def collect(client_id, client_secret, hours=30):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    seen_links, seen_titles, out = set(), set(), []
    for field, queries in KEYWORDS.items():
        for q in queries:
            try:
                items = search_news(q, client_id, client_secret)
            except RuntimeError as e:
                print(f"[경고] '{q}' 검색 실패: {e}", file=sys.stderr)
                continue
            kept = 0
            for it in items:
                pub = parse_pub(it.get("pubDate"))
                if pub is None or pub.astimezone(timezone.utc) < cutoff:
                    continue
                link = it.get("link") or it.get("originallink")
                title = clean_title(it.get("title"))
                if not link or not title:
                    continue
                norm = re.sub(r"\W+", "", title)[:40]
                if link in seen_links or norm in seen_titles:
                    continue
                seen_links.add(link)
                seen_titles.add(norm)
                out.append(
                    {
                        "field": field,
                        "query": q,
                        "title": title,
                        "link": link,
                        "pub": pub.astimezone(KST),
                    }
                )
                kept += 1
            print(f"  [{field}] {q}: 신규 후보 {kept}건")
            time.sleep(0.2)
    out.sort(key=lambda x: x["pub"], reverse=True)
    return out


def notion_headers(token):
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}


def notion_exists(token, db_id, link):
    body = {"filter": {"property": P_LINK, "url": {"equals": link}}, "page_size": 1}
    res = http_json(f"{NOTION_API}/databases/{db_id}/query", "POST", notion_headers(token), body)
    return bool(res.get("results"))


def rt(text):
    return [{"type": "text", "text": {"content": text[:1900]}}]


def notion_create(token, db_id, item):
    props = {
        P_TITLE: {"title": rt(item["title"])},
        P_LINK: {"url": item["link"]},
        P_DATE: {"date": {"start": item["pub"].isoformat()}},
        P_FIELD: {"select": {"name": item["field"]}},
        P_QUERY: {"rich_text": rt(item["query"])},
    }
    body = {"parent": {"database_id": db_id}, "properties": props}
    http_json(f"{NOTION_API}/pages", "POST", notion_headers(token), body)


def notion_archive_older_than(token, db_id, days):
    """RETENTION_DAYS 지난 행을 보관(archive) 처리한다 (네이버 API HUB 약관 준수)."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).date().isoformat()
    body = {"filter": {"property": P_DATE, "date": {"before": cutoff}}, "page_size": 100}
    total = 0
    while True:
        res = http_json(f"{NOTION_API}/databases/{db_id}/query", "POST", notion_headers(token), body)
        for page in res.get("results", []):
            if page.get("archived"):
                continue
            http_json(
                f"{NOTION_API}/pages/{page['id']}", "PATCH", notion_headers(token), {"archived": True}
            )
            total += 1
            time.sleep(0.35)
        if not res.get("has_more"):
            break
        body["start_cursor"] = res["next_cursor"]
    return total


def main():
    cid = os.environ.get("NCP_APIHUB_CLIENT_ID")
    secret = os.environ.get("NCP_APIHUB_CLIENT_SECRET")
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")

    missing = [
        n
        for n, v in [
            ("NCP_APIHUB_CLIENT_ID", cid),
            ("NCP_APIHUB_CLIENT_SECRET", secret),
            ("NOTION_TOKEN", token),
            ("NOTION_DATABASE_ID", db_id),
        ]
        if not v
    ]
    if missing:
        sys.exit("환경변수가 없습니다: " + ", ".join(missing))

    print(f"수집 시작: 최근 30시간, 검색어 {sum(len(v) for v in KEYWORDS.values())}개")
    items = collect(cid, secret, hours=30)
    print(f"중복 제거 후 후보 {len(items)}건")

    saved = skipped = failed = 0
    for it in items:
        try:
            if notion_exists(token, db_id, it["link"]):
                skipped += 1
            else:
                notion_create(token, db_id, it)
                saved += 1
        except RuntimeError as e:
            failed += 1
            print(f"[경고] 저장 실패: {it['title'][:30]} :: {e}", file=sys.stderr)
        time.sleep(0.35)
    print(f"완료: 저장 {saved}건, 이미 있음 {skipped}건, 실패 {failed}건")

    archived = notion_archive_older_than(token, db_id, RETENTION_DAYS)
    if archived:
        print(f"{RETENTION_DAYS}일 지난 행 {archived}건을 보관 처리했습니다 (약관상 최대 보관기간 준수).")


if __name__ == "__main__":
    main()
