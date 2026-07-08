# ARCHITECTURE — canton-telegram-bot

> **업데이트 트리거**: `bot.py` 실행 플로우 변경 / 새 collector 추가 / LaunchAgent plist 구조 변경 / fallback chain 수정 시 즉시 이 문서를 갱신한다.

| Meta | Value |
|------|-------|
| Project | canton-telegram-bot |
| Type | pipeline (daily report) |
| Runtime | Python 3.11+ |
| Schedule | 매일 09:00 KST 1회 (macOS launchd) |
| Entry | `python bot.py --now` (one-shot) / `python bot.py` (APScheduler) |
| Isolation | canton-hub와 **완전 분리** (코드/상태/API 쿼터 공유 없음) |

---

## 1. System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ macOS launchd (com.cobling.canton-bot.plist)                    │
│   StartCalendarInterval: Hour=9, Minute=0 KST                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ spawns
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ bot.py --now  →  collect_and_post()                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ asyncio.gather(return_exceptions=True)
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
  ┌──────────────┐ ┌───────────────┐ ┌──────────────┐
  │ Twitter      │ │ CantonScan    │ │ Price        │
  │ Collector    │ │ Collector     │ │ Collector    │
  │ (RapidAPI)   │ │ (API→HTML→PW) │ │ (CoinGecko)  │
  └──────┬───────┘ └───────┬───────┘ └──────┬───────┘
         │ TweetData[]     │ CantonScanData │ PriceData
         ▼                 ▼                ▼
  ┌─────────────────────────────────────────────────┐
  │ tweet_summarizer.summarize_tweets() (AI 번역/요약) │
  └──────────────────────┬──────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────┐
  │ formatter.build_daily_report() → HTML string    │
  └──────────────────────┬──────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────┐
  │ chart_generator.generate_chart_base64() (mpl)   │
  │ image_generator.generate_daily_card()           │
  │   (Jinja2 + templates/daily_card.html → PNG)    │
  └──────────────────────┬──────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────┐
  │ telegram.Bot.send_photo(caption=HTML)           │
  │   └ fallback: send_message(HTML)                │
  └─────────────────────────────────────────────────┘
```

---

## 2. Module Dependency Map

| Module | Depends On | Purpose |
|--------|-----------|---------|
| `bot.py` | `formatter`, `chart_generator`, `image_generator`, `tweet_summarizer`, `collectors/*` | 오케스트레이션 엔트리포인트 |
| `collectors/twitter_collector.py` | `httpx`, RapidAPI | 트윗 수집, `TweetData` 반환 |
| `collectors/cantonscan_collector.py` | `httpx`, `beautifulsoup4`, `playwright` | Canton 체인 스탯 수집, `CantonScanData` 반환 |
| `collectors/price_collector.py` | `httpx`, CoinGecko API | $CC 가격 수집, `PriceData` 반환 |
| `tweet_summarizer.py` | Gemini CLI (`gemq`, subprocess) | `list[TweetData]` → 한국어 요약 문자열 |
| `formatter.py` | dataclasses | HTML 메시지 빌드 |
| `chart_generator.py` | `matplotlib` | 최근 가격 라인차트 → base64 PNG |
| `image_generator.py` | `jinja2`, `playwright` (or HTML→image lib) | `daily_card.html` 렌더 → PNG bytes |

> **경고**: `collectors/`는 canton-hub의 동명 모듈과 **독립적인 복사본**이다. 수정 시 양쪽 프로젝트를 각각 갱신해야 한다.

---

## 3. Data Flow (9-Step Execution)

| Step | Action | Location | Failure Mode |
|------|--------|----------|--------------|
| 1 | 3개 collector 인스턴스 초기화 | `bot.collect_and_post()` | 생성자 실패 → 프로세스 종료 |
| 2 | `asyncio.gather(twitter, cantonscan, price, return_exceptions=True)` 병렬 실행 | `bot.py` | 각 collector 독립 실패 허용 |
| 3 | 예외가 반환된 항목은 **빈 dataclass**로 치환 (`fetched=False`) | `bot.py` | — |
| 4 | `tweets` 비어있지 않으면 `await summarize_tweets(tweets)` 호출 (gemq, 재시도 2회) | `tweet_summarizer` | 실패 시 **영어 원문 덤프 금지** → 한국어 안내+원문 링크 폴백 |
| 5 | `build_daily_report(tweets, scan_data, price_data, tweet_summary)` → HTML | `formatter.py` | 필수 |
| 6 | `TELEGRAM_BOT_TOKEN` 없으면 **preview mode**: HTML 태그 제거 후 stdout 출력, exit | `bot.py` | — |
| 7a | `chart_b64 = await generate_chart_base64()` | `chart_generator.py` | 실패 시 텍스트 폴백 |
| 7b | `image_bytes = await generate_daily_card(scan_data, price_data, date_str, chart_b64)` | `image_generator.py` | 실패 시 텍스트 폴백 |
| 7c | 성공: `bot.send_photo(chat_id, photo=image_bytes, caption=message, parse_mode=HTML)` | `python-telegram-bot` | 실패 시 Step 7d |
| 7d | 폴백: `bot.send_message(chat_id, text=message, parse_mode=HTML, disable_web_page_preview=True)` | `python-telegram-bot` | 재시도 없음 |
| 8 | `logger.info("텔레그램 전송 완료")` | `bot.py` | — |
| 9 | Cleanup: `await cantonscan.close()`, `await price.close()` (httpx client 종료) | `bot.py` | finally 블록 권장 |

---

## 4. Fallback Chains

### 4.1 TwitterCollector
```
RapidAPI user_tweets endpoint
    ↓ (rate limit / 5xx / empty)
RapidAPI search endpoint
    ↓ (실패)
빈 list[TweetData]  →  formatter가 트위터 섹션 생략
```

### 4.2 CantonScanCollector
```
CantonScan JSON API
    ↓ (4xx/5xx)
HTML scraping (httpx + BeautifulSoup)
    ↓ (JS 렌더 필요 / 파싱 실패)
Playwright Chromium headless
    ↓ (실패)
빈 CantonScanData(fetched=False)
```

### 4.3 PriceCollector
```
CoinGecko /coins/markets
    ↓ (rate limit / 5xx)
CoinGecko /simple/price
    ↓ (실패)
빈 PriceData(fetched=False)
```

### 4.4 Image Pipeline
```
chart_generator (matplotlib)
    ↓
image_generator (Jinja2 + daily_card.html → PNG)
    ↓
bot.send_photo(caption=HTML)
    ↓ (이미지 생성/전송 실패)
bot.send_message(HTML, disable_web_page_preview=True)
```

**규칙**: WHEN 이미지 파이프라인 실패 → DO 텍스트 메시지로 폴백. 재시도 없음.

---

## 5. Infrastructure — LaunchAgent

**Path**: `~/Library/LaunchAgents/com.cobling.canton-bot.plist`

| Key | Current (KeepAlive mode) | Future (One-shot mode) |
|-----|--------------------------|------------------------|
| `Label` | `com.cobling.canton-bot` | `com.cobling.canton-bot` |
| `ProgramArguments` | `.venv/bin/python bot.py` | `.venv/bin/python bot.py --now` |
| `KeepAlive` | `true` (APScheduler 내부 스케줄링) | `false` |
| `StartCalendarInterval` | — | `Hour=9, Minute=0` |
| `WorkingDirectory` | 프로젝트 루트 | 프로젝트 루트 |
| `StandardOutPath` | `launchd_stdout.log` | `launchd_stdout.log` |
| `StandardErrorPath` | `launchd_stderr.log` | `launchd_stderr.log` |

**운영 명령**:
```bash
# 로드
launchctl load ~/Library/LaunchAgents/com.cobling.canton-bot.plist
# 언로드
launchctl unload ~/Library/LaunchAgents/com.cobling.canton-bot.plist
# 즉시 실행(테스트)
launchctl start com.cobling.canton-bot
# 상태 확인
launchctl list | grep canton-bot
```

**마이그레이션 계획**: KeepAlive 모드는 프로세스 상주로 인한 메모리 누수 위험. One-shot 모드로 전환 예정 — `StartCalendarInterval`이 9시에 프로세스를 띄우고 `--now` 실행 후 즉시 종료.

---

## 6. canton-telegram-bot vs canton-hub

| 항목 | canton-telegram-bot | canton-hub |
|------|---------------------|------------|
| 목적 | **일 1회** 데일리 리포트 전송 | 실시간 대시보드/허브 |
| 트리거 | launchd 09:00 KST | 상시 구동 |
| 엔트리 | `bot.py --now` | (별도) |
| Collectors | `collectors/` 독립 복사본 | 동명 모듈 (별도 복사본) |
| 상태 공유 | **없음** | **없음** |
| API 쿼터 | **독립** (RapidAPI / CoinGecko 키 각자 관리) | **독립** |
| 프로세스 | 단발성 (또는 KeepAlive) | 상시 |
| 장애 전파 | canton-hub에 영향 없음 | canton-telegram-bot에 영향 없음 |

**격리 원칙**:
1. WHEN canton-hub에서 collector 버그 발견 → DO 이 프로젝트의 `collectors/`도 **수동으로** 동일 수정
2. WHEN RapidAPI 쿼터 소진 → 두 프로젝트 중 하나만 영향 (별도 키 사용 권장)
3. 두 프로젝트는 **어떤 파일시스템 경로도 공유하지 않는다**

---

## 7. Verification Gates

| Gate | Command | Expected |
|------|---------|----------|
| 로컬 프리뷰 | `TELEGRAM_BOT_TOKEN= python bot.py --now` | HTML 태그 제거된 리포트가 stdout 출력 |
| 실전 전송 테스트 | `python bot.py --now` (env 설정 후) | 텔레그램 채팅에 이미지+캡션 수신 |
| LaunchAgent 검증 | `launchctl list \| grep canton-bot` | PID 또는 `-` (last exit status 0) |
| 로그 확인 | TODO: `tail -f launchd_stdout.log` | "텔레그램 전송 완료" 라인 존재 |

---

## Change Log

| 날짜 | 변경 | 이유 |
|------|------|------|
| 2026-04-14 | 초기 생성 | docs-init으로 자동 생성 |
