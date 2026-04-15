# DEVELOPMENT_GUIDE.md

> **Update Triggers**: 새 collector 추가 / formatter 섹션 추가 / 버그 재발 / 테스트 인프라 도입 / LaunchAgent 구성 변경

**Project**: canton-telegram-bot
**Stack**: Python 3.11+, python-telegram-bot, httpx, Playwright, beautifulsoup4, Jinja2, matplotlib, APScheduler (optional), python-dotenv
**Scope**: 개발 작업 표준 — 템플릿, 유틸, 테스트, 버그 패턴, 채널 안전

---

## 1. Pre-Work Checklist

작업 시작 전 **반드시** 아래 항목을 확인합니다.

| # | 체크 항목 | 확인 방법 |
|---|----------|----------|
| 1 | 올바른 프로젝트 경로인가? | `pwd` → `.../Ozzycanton/canton-telegram-bot` |
| 2 | canton-hub이 로컬에서 돌고 있지 않은가? (Rate Limit 위험) | `ps aux \| grep canton-hub` |
| 3 | 테스트 채널 or 프로덕션 채널? | `.env`의 `TELEGRAM_CHAT_ID` 확인 |
| 4 | Preview 모드 먼저 돌릴 준비됐는가? | `TELEGRAM_BOT_TOKEN= python bot.py --now` |
| 5 | 변경 파일 3~5개 이내로 제한했는가? | `git status` |

> **WHEN** 체크리스트 중 하나라도 미확인 → **DO** 작업 보류하고 먼저 확인

---

## 2. Standard Templates

### 2.1 Collector Template

신규 데이터 소스 추가 시 **반드시** 이 템플릿을 복사해서 시작합니다.

```python
import logging
import httpx
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class MyData:
    value: Optional[float] = None
    fetched: bool = False

class MyCollector:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "CantonTelegramBot/1.0"},
        )

    async def collect(self) -> MyData:
        try:
            r = await self.client.get("https://api.example.com/data")
            r.raise_for_status()
            payload = r.json()
            return MyData(value=payload["value"], fetched=True)
        except Exception as e:
            logger.warning(f"MyCollector failed: {e}")
            return MyData()  # empty, fetched=False — NEVER raise

    async def close(self):
        await self.client.aclose()
```

**규칙**:
- Collector 는 **절대** 예외를 바깥으로 던지지 않는다 (빈 dataclass 반환)
- `fetched: bool` 로 성공/실패 구분 (formatter 에서 skip 조건)
- `User-Agent` 는 `CantonTelegramBot/1.0` 통일

### 2.2 Formatter Extension

리포트에 섹션 추가 시 **반드시** `fetched` 플래그를 먼저 확인합니다.

```python
def build_daily_report(tweets, scan_data, price_data, tweet_summary=""):
    lines = []
    # existing header...
    if scan_data.fetched and scan_data.some_new_field is not None:
        lines.append(f"<b>New Metric: {scan_data.some_new_field:.2f}</b>")
    return "\n".join(lines)
```

**규칙**:
- 모든 dataclass 필드 접근 전 `fetched` 체크 + `is not None` 체크
- Telegram HTML 파싱을 쓰므로 자유 텍스트는 반드시 이스케이프 (섹션 5.3 참고)

### 2.3 Scheduler Usage

| 모드 | 명령 | 용도 |
|------|------|------|
| 즉시 실행 (실 발송) | `python bot.py --now` | 수동 트리거 |
| Preview (미발송) | `TELEGRAM_BOT_TOKEN= python bot.py --now` | 개발 검증 |
| 상시 루프 | `python bot.py` | LaunchAgent 실행 |

> **WHEN** APScheduler 통합 작업 → **DO** 기존 `bot.py --now` flow를 래핑하는 형태로 도입 (코드 중복 금지)

---

## 3. Utility Reference

`formatter.py` 에 정의된 숫자/통화 포맷 헬퍼.

| 함수 | 입력 | 출력 예 | 용도 |
|------|------|---------|------|
| `_fmt_cc(n)` | `1234567.89` | `1,234,567.89` | CC (Canton Coin) 수량 |
| `_fmt_usd(n)` | `0.0456` | `$0.0456` | USD 가격 (소수) |
| `_fmt_large_usd(n)` | `12345678` | `$12.35M` | 시가총액/TVL 등 대형 USD |

**규칙**:
- 소수점 자리수 변경이 필요하면 **헬퍼에서** 수정 (인라인 포맷 금지)
- `None` 입력 방어는 헬퍼 내부에서 처리 — 호출부는 `None` 넘기지 말 것

---

## 4. Testing Standards

> **현재 상태**: 정식 테스트 프레임워크 없음 (pytest 미도입)
> **TODO**: 향후 pytest + httpx MockTransport 기반 collector 단위 테스트 도입

### 4.1 검증 절차 (현행)

| 단계 | 명령 / 행동 | 통과 기준 |
|------|------------|-----------|
| 1. Preview 실행 | `TELEGRAM_BOT_TOKEN= python bot.py --now` | 예외 없이 종료, HTML 출력 확인 |
| 2. 로그 검사 | stdout / LaunchAgent 로그 `tail` | `WARNING` 개수 < 기존 baseline |
| 3. 테스트 채널 발송 | 테스트 채널 chat_id 로 `--now` | 메시지 정상 렌더, 이미지 첨부 확인 |
| 4. 프로덕션 발송 | 프로덕션 chat_id 로 `--now` | 섹션 6 안전 규칙 모두 통과 후에만 |

### 4.2 Collector 단독 검증 (ad-hoc)

```bash
python -c "import asyncio; from collectors.my_collector import MyCollector; c = MyCollector(); print(asyncio.run(c.collect()))"
```

> **WHEN** Collector 응답 형태 바뀜 의심 → **DO** 먼저 ad-hoc 스니펫으로 raw payload 확인 후 dataclass 수정

---

## 5. Bug Pattern Catalog

모든 항목은 **실제 발생 사례**입니다. 재발 시 이 섹션부터 검색하세요.

### 5.1 9am KST CoinGecko 429

| 항목 | 내용 |
|------|------|
| 증상 | 매일 오전 9시(KST) CoinGecko 호출 429 Too Many Requests |
| 원인 | bot + canton-hub 이 같은 IP quota 공유 |
| 해결 | `COINGECKO_API_KEY` Demo key 추가 + canton-hub 를 Fly.io 로 분리 배포 |
| 검색 | `grep -n "COINGECKO_API_KEY\|coingecko" collectors/` |

### 5.2 Collector Exception Bubble-Up

| 항목 | 내용 |
|------|------|
| 증상 | 한 collector 실패가 전체 파이프라인 크래시 |
| 규칙 | **Collector 는 절대 raise 하지 않는다** |

**Wrong**
```python
async def collect(self):
    r = await self.client.get(url)
    r.raise_for_status()  # bubbles up
    return MyData(value=r.json()["v"], fetched=True)
```

**Right**
```python
async def collect(self):
    try:
        r = await self.client.get(url)
        r.raise_for_status()
        return MyData(value=r.json()["v"], fetched=True)
    except Exception as e:
        logger.warning(f"failed: {e}")
        return MyData()
```

### 5.3 Telegram HTML Parse Mode Fails on Special Chars

| 항목 | 내용 |
|------|------|
| 증상 | 트윗 본문의 `<`, `>`, `&` 로 인해 `BadRequest: can't parse entities` |
| 해결 | HTML 이스케이프 |

**Wrong**
```python
lines.append(f"<i>{tweet.text}</i>")
```

**Right**
```python
safe = tweet.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
lines.append(f"<i>{safe}</i>")
```

검색: `grep -rn "parse_mode\|replace(\"<\"" .`

### 5.4 Image Generation Failure Takes Down Report

| 항목 | 내용 |
|------|------|
| 증상 | `generate_daily_card` 한 번 실패 → 텍스트 리포트까지 발송 실패 |
| 해결 | `bot.py` 에서 try/except 로 텍스트 fallback |

**Wrong**
```python
img = generate_daily_card(...)
await bot.send_photo(chat_id, img, caption=text)
```

**Right**
```python
try:
    img = generate_daily_card(...)
    await bot.send_photo(chat_id, img, caption=text)
except Exception as e:
    logger.warning(f"image failed: {e}")
    await bot.send_message(chat_id, text, parse_mode="HTML")
```

### 5.5 LaunchAgent KeepAlive Infinite Restart

| 항목 | 내용 |
|------|------|
| 증상 | `bot.py` 가 예외로 종료 → LaunchAgent `KeepAlive` 가 무한 재시작 |
| 해결 | `bot.py` main loop 내부에서 예외 catch, 정상 종료 금지 (sleep 후 재시도) |
| 검색 | `grep -n "while True\|except Exception" bot.py` |

### 5.6 Channel Spam from `--now` Dev Testing

| 항목 | 내용 |
|------|------|
| 증상 | 개발 중 `--now` 반복 실행으로 프로덕션 채널 도배 |
| 규칙 | Preview 모드 (`TELEGRAM_BOT_TOKEN=`) 또는 테스트 채널 우선 |

### 5.7 Tweet Time Parsing Drift

| 항목 | 내용 |
|------|------|
| 증상 | RapidAPI 응답의 `created_at` 포맷이 들쭉날쭉 (`Wed Apr 10 ...`, ISO8601 등) |
| 해결 | `TweetData.created_at` 에서 정규화 (여러 포맷 try/except 순차 파싱) |
| 검색 | `grep -n "created_at\|strptime" collectors/` |

### 5.8 Matplotlib CJK Font Warnings

| 항목 | 내용 |
|------|------|
| 증상 | 차트에 CJK 텍스트 → `Glyph missing from current font` 경고 + 두부 문자 |
| 해결 | `fonts-noto-cjk` 시스템 패키지 설치 **또는** 차트에서 CJK 생략 (영문만) |

---

## 6. Channel Safety Rules

> **CRITICAL**: 프로덕션 채널 발송은 돌이킬 수 없다. 아래 규칙을 **순서대로** 지킨다.

| # | 규칙 | 검증 |
|---|------|------|
| 1 | 코드 변경 후 **첫 실행은 Preview 모드** | `TELEGRAM_BOT_TOKEN= python bot.py --now` |
| 2 | Preview 통과 후 **테스트 채널 먼저** | `.env.test` 또는 별도 chat_id 환경변수 |
| 3 | 테스트 채널 시각 검수 후 **프로덕션 채널** | 사용자 승인 |
| 4 | canton-hub 로컬 동시 구동 금지 (Rate Limit 리스크) | `ps aux \| grep canton-hub` |
| 5 | `--now` 연속 실행 시 **최소 5분 간격** (스팸 방지) | 수동 |
| 6 | CoinGecko 호출 전 `COINGECKO_API_KEY` 확인 | `.env` |

> **WHEN** 위 규칙 중 하나라도 우회하고 싶다 → **DO** 먼저 사용자에게 확인

---

## 7. Change Log

| 날짜 | 변경 | 이유 |
|------|------|------|
| 2026-04-14 | 초기 생성 | docs-init 으로 자동 생성 (collector/formatter 템플릿, 8개 버그 카탈로그, 채널 안전 규칙 포함) |
