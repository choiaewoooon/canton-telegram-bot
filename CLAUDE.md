# Canton Telegram Bot

매일 아침 10시(KST) Canton Network ($CC) 일일 리포트를 텔레그램 채널에 자동 포스팅하는 Python 파이프라인. CoinGecko / CantonScan / RapidAPI Twitter API45에서 데이터를 병렬 수집하고, HTML 텔레그램 메시지 + 이미지 카드를 생성해서 `python-telegram-bot` SDK로 전송한다.

**홈 Mac의 `launchd`에서 구동**. 클라우드 배포 대상이 아님.

- Project Path: `/Users/choejaewon/project/Ozzycanton/canton-telegram-bot`
- LaunchAgent: `~/Library/LaunchAgents/com.cobling.canton-bot.plist`
- 관련 프로젝트:
  - `../canton-hub/` — Canton 웹 대시보드 (별도 레포, 독립 운영). 웹 스케줄러가 이 봇과 동시에 CoinGecko를 두드릴 수 있어서 분리됨 (9am KST rate limit 사고 이후 분리)
  - `../canton-bot/` — **레거시 원본**, 봇/웹 혼재. 분리 전 상태. 수정 금지

## Tech Stack

| 카테고리 | 기술 | 버전/비고 |
|---|---|---|
| 런타임 | Python | 3.11+ |
| 텔레그램 SDK | python-telegram-bot | 21+ (async) |
| HTTP 클라이언트 | httpx | 0.25+ (async) |
| HTML 파싱 | beautifulsoup4 | 4.12+ |
| 동적 스크래핑 | Playwright + Chromium | 1.40+ (CantonScan SPA 폴백) |
| 스케줄러 | APScheduler | 3.10+ (cron trigger) |
| 이미지 생성 | Jinja2 + matplotlib | 3.1 / 3.8+ |
| 설정 | python-dotenv | 1.0+ |
| 실행 환경 | macOS `launchd` | LaunchAgent plist + StartCalendarInterval |

## Project Structure

```
canton-telegram-bot/
├── bot.py                      # 엔트리포인트 — `--now` 또는 스케줄러 모드
├── formatter.py                # 수집 데이터 → HTML 텔레그램 메시지
├── chart_generator.py          # matplotlib 기반 차트 base64 생성
├── image_generator.py          # Jinja2 daily card 템플릿 렌더 → PNG
├── tweet_summarizer.py         # 트윗 AI 요약 (번역 + 요점)
├── collectors/                 # 3개 수집기만 (canton-hub와 독립 복사본)
│   ├── __init__.py
│   ├── price_collector.py      # CoinGecko $CC 가격
│   ├── cantonscan_collector.py # Canton 네트워크 지표
│   └── twitter_collector.py    # RapidAPI Twitter API45
├── templates/                  # Jinja2 HTML 템플릿 (daily_card.html + assets)
│   ├── daily_card.html
│   └── assets/
├── config.py                   # .env 로드 + 상수
├── requirements.txt            # 봇 전용 deps (fastapi/uvicorn 없음)
├── .env.example
└── docs/                       # 이 문서를 포함한 운영 문서
```

---

## 0. Core Principles (핵심 원칙)

- 언어: 한국어 문서·주석, 영어 코드
- 프로젝트 경로: `/Users/choejaewon/project/Ozzycanton/canton-telegram-bot` — 다른 경로 작업 금지
- **canton-hub와 절대 runtime state/API 호출 공유 금지** — 이 봇은 자기 `collectors/`를 갖고 독립 수행. 공유 state는 rate limit 동시 소진으로 이어진 과거 사고의 원인
- 수집기는 항상 예외를 내부에서 삼키고 빈 dataclass 반환 — `raise`는 파이프라인을 통째로 죽임
- 시크릿(`TELEGRAM_BOT_TOKEN`, `RAPIDAPI_KEY`, `COINGECKO_API_KEY`) 하드코딩 금지. `.env` 사용, `.gitignore` 등록됨
- 봇은 **하루 1회** 실행이 정상. 연속 실행 시 텔레그램 채널 스팸 가능 → 수동 테스트는 반드시 `python bot.py --now` + `TELEGRAM_BOT_TOKEN=` (공백 = 미리보기 모드)

## 1. Quick Reference

| 작업 | 명령어 |
|---|---|
| venv 생성 | `python3 -m venv venv && source venv/bin/activate` |
| 설치 | `pip install -r requirements.txt && playwright install chromium` |
| 미리보기 (전송 없음) | `TELEGRAM_BOT_TOKEN= python bot.py --now` |
| 실제 전송 (1회) | `python bot.py --now` (.env에 토큰 로드됨) |
| 스케줄러 모드 | `python bot.py` (APScheduler + 매일 10시 KST) |
| LaunchAgent 로드 | `launchctl load ~/Library/LaunchAgents/com.cobling.canton-bot.plist` |
| LaunchAgent 언로드 | `launchctl unload ~/Library/LaunchAgents/com.cobling.canton-bot.plist` |
| 수동 발사 (LaunchAgent 경유) | `launchctl kickstart gui/$(id -u)/com.cobling.canton-bot` |
| 로그 확인 | `tail -f launchd_stdout.log launchd_stderr.log bot.log` |

## 2. Workflow Protocols

### 2.1 Plan First → Implement → Verify

```
1. 변경 대상 명확화 (collector / formatter / image / bot.py 어디?)
2. 미리보기 모드 먼저 — TELEGRAM_BOT_TOKEN= python bot.py --now
3. 출력 HTML 수동 검토 (채널 스팸 방지)
4. 실제 전송 테스트는 테스트 채널 또는 본인 DM에서
5. 프로덕션 채널 전송은 스케줄러에게 맡기거나 수동 1회만
```

### 2.2 Side Impact Analysis

- [ ] `collectors/` 수정 시 `formatter.py`의 사용처 확인
- [ ] 새 `dataclass` 필드 추가 시 `formatter.py` + `image_generator.py` 양쪽 사용처 확인
- [ ] `image_generator.py`의 Jinja 템플릿 변수 이름과 Python 전달 인자 이름 일치 확인
- [ ] 수집기 시그니처 변경 시 `bot.py`의 asyncio.gather 호출부 수정
- [ ] `.env.example` 변경 시 `config.py` + `DEPLOY.md`(있다면) 동기화

### 2.3 Batch Size Limits

- 단일 변경: 파일 3-5개 이내 권장 (봇은 작은 코드베이스라 더 엄격)
- formatter + image_generator + chart_generator 동시 수정이면 1 PR 허용

### 2.4 Git Workflow

```
feat: 트윗 AI 요약에 언어 감지 추가
fix: CantonScan 429 시 retry + 파일 캐시
refactor: formatter HTML 헬퍼 분리
```
Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`

## 3. Cross-Cutting Change Protocol

수집기와 포매터 양쪽 수정 시:
1. `grep -r "from collectors import" .` 로 사용처 확인
2. `dataclass` 필드 추가 시 `formatter.py`, `image_generator.py`, `chart_generator.py` 세 파일 모두 검토
3. 미리보기 모드로 HTML 출력 + 이미지 생성 검증
4. 같은 PR에 모든 변경 포함

## 4. Known Patterns & Anti-Patterns

| 패턴 | 검색 쿼리 | 잘못된 예시 | 올바른 예시 |
|---|---|---|---|
| Collector 예외 버블링 | `raise ` in `collectors/` | `raise httpx.TimeoutException` | `logger.warning(...); return EmptyData()` |
| 블로킹 sync | `requests.` / `time.sleep` | `requests.get(url)` | `await client.get(url)` |
| 토큰 하드코딩 | `TOKEN = "..."` | `bot = Bot(token="123:abc")` | `Bot(token=config.TELEGRAM_BOT_TOKEN)` |
| 채널 스팸 | 전송 테스트 반복 | 프로덕션 채널에 연속 `--now` | 미리보기 모드 또는 테스트 채널 |
| 이미지 생성 실패 → 전체 실패 | 예외 미포착 | `img = generate_daily_card(...)` → 실패 시 메시지도 안 감 | `try/except` 후 텍스트 fallback (bot.py에 이미 구현) |
| webhook/polling 병행 | 텔레그램 SDK 오용 | polling 띄우면서 launchd도 구동 | **하루 1회 one-shot 전송만**, polling 쓰지 말 것 |

## 5. Evidence-Based Completion

| 주장 | 필요한 증거 | 불충분한 증거 |
|---|---|---|
| 메시지 전송 성공 | 텔레그램 채널에서 육안 확인 + `로그 "텔레그램 전송 완료"` | `bot.send_message` 호출했음 |
| 수집기 동작 | `bot.log` 에 해당 수집기 수집 완료 라인 | import 성공 |
| 이미지 카드 생성 | 파일시스템 PNG 파일 + 텔레그램 photo caption 확인 | Jinja 렌더 성공 |
| LaunchAgent 구동 | `launchctl list \| grep canton-bot` → 마지막 exit 0 | plist 로드됨 |

## 6. STOP Conditions

- 텔레그램 API 401 → `TELEGRAM_BOT_TOKEN` 재확인, 봇이 채널에 추가됐는지 확인
- CoinGecko 429 → canton-hub 백엔드와 쿼터 충돌 여부 확인 (같은 홈 Mac IP면 OK, 다르면 OK)
- RapidAPI 403 → Twitter API45 구독 만료 의심
- 이미지 생성 계속 실패 → Jinja 템플릿 변수 일치 확인 + matplotlib 폰트 이슈 확인
- LaunchAgent가 10시에 안 뜸 → Mac이 자고 있었을 가능성. **재기동 보충 발송 로직**이 처리함: 봇 시작 시 오늘 스케줄 시각이 지났고 `.last_sent`(KST 발송일 기록)가 오늘이 아니면 즉시 1회 보충 발송. 절전에서 깬 뒤 launchd가 재기동하면 자동으로 당일 리포트 보장. 중복은 `.last_sent`로 차단

→ **추측 금지, 로그부터 확인**

## 7. 3-Failure Escalation

- 동일 수집기 3회 실패 → 외부 API 문제인지 코드 문제인지 격리
- 동일 이미지 생성 3회 실패 → 텍스트 폴백으로 당일 리포트는 발송, 이미지 생성은 별도 이슈로 처리

## 8. Document Map

| 문서 | 읽어야 할 때 | 업데이트 트리거 |
|---|---|---|
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 파이프라인 흐름 파악 | 수집기/포매터/이미지 변경 |
| [docs/DATA_GUIDE.md](./docs/DATA_GUIDE.md) | 데이터 소스·스키마 | 새 수집기 또는 외부 API 변경 |
| [docs/DEVELOPMENT_GUIDE.md](./docs/DEVELOPMENT_GUIDE.md) | 코딩 패턴 | 새 패턴/버그 발견 |
| [docs/SYSTEM_OVERVIEW.md](./docs/SYSTEM_OVERVIEW.md) | 과거 결정 배경 | 매 작업 완료 시 |

## 9. Documentation Rules

| 변경 감지 | 업데이트 대상 | 업데이트 내용 |
|---|---|---|
| `collectors/` 신규 추가 | ARCHITECTURE.md + DATA_GUIDE.md | 모듈 + 소스 테이블 |
| `formatter.py` 메시지 구조 변경 | ARCHITECTURE.md Data Flow | HTML 섹션 순서 |
| `image_generator.py` 템플릿 변경 | ARCHITECTURE.md + DEVELOPMENT_GUIDE.md | 템플릿 변수 목록 |
| `requirements.txt` 변경 | CLAUDE.md Tech Stack | 버전 |
| `.env.example` 변경 | README.md Env Vars | 변수 + 필수 여부 |
| LaunchAgent plist 변경 | CLAUDE.md Quick Reference | 경로/스케줄 |
| 새 버그 패턴 발견 | DEVELOPMENT_GUIDE.md | 패턴 + 검색 쿼리 |
| 아키텍처 결정 | SYSTEM_OVERVIEW.md ADR | 결정 기록 |
| 작업 완료 | SYSTEM_OVERVIEW.md Phase History | 단계 추가 |

## Change Log

| 날짜 | 변경 | 이유 |
|---|---|---|
| 2026-04-15 | 초기 생성 | docs-init (canton-bot 분리 후 재작성) |
| 2026-06-02 | 재기동 보충 발송 로직 추가 (`bot.py`) | 절전으로 10시 스케줄 놓치면 당일 리포트 누락 → 재기동 시 `.last_sent` 기준 1회 자동 보충 |
