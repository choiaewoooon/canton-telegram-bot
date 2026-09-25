# Canton Telegram Bot

매일 아침 10시(KST) Canton Network ($CC) 일일 리포트를 텔레그램 채널에 자동 포스팅하는 Python 파이프라인. CoinGecko / CantonScan / ScrapeCreators(트위터)에서 데이터를 병렬 수집하고, HTML 텔레그램 메시지 + 이미지 카드를 생성해서 `python-telegram-bot` SDK로 전송한다. (2026-07-17까지는 RapidAPI twitter241을 썼으나 게이트웨이 전역 장애로 교체 — Change Log 참조)

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
│   └── twitter_collector.py    # ScrapeCreators (구 RapidAPI twitter241)
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
| 스케줄러 모드 (수동, launchd 미사용) | `python bot.py` (APScheduler 상주). **주의: launchd는 이 모드를 쓰지 않는다** — 아래 참조 |
| LaunchAgent 로드 | `launchctl load ~/Library/LaunchAgents/com.cobling.canton-bot.plist` |
| LaunchAgent 언로드 | `launchctl unload ~/Library/LaunchAgents/com.cobling.canton-bot.plist` |
| 수동 발사 (LaunchAgent 경유) | `launchctl kickstart gui/$(id -u)/com.cobling.canton-bot` |
| plist 변경 후 반영 | unload → load (kickstart는 plist 재읽기 안 함) |

> **실행 모델 (2026-07-02 변경)**: launchd는 **`bot.py --now`(1회 실행 후 종료)를 `StartCalendarInterval`로 매일 10시 KST에 새 프로세스로 띄운다.** 장수명 APScheduler 데몬이 아니다. 이유: 상주 데몬은 코드를 고쳐도 재시작 전까지 옛 코드를 메모리에 물고 있어, 파일만 고치고 데몬을 안 껐다 켜면 반영이 안 되는 사고가 났다(2026-07-02, 요약이 계속 영어로 나감). 1회성 실행은 **매번 최신 코드**라 이 함정이 없다. 코드 수정 후 별도 재시작 불필요.
| 로그 확인 | `tail -f launchd_stdout.log launchd_stderr.log bot.log` |
| **Playwright 브라우저 점검·복구** | `bash scripts/ensure-playwright.sh` (매일 09:45 자동 실행, 로그 `logs/ensure-playwright.log`) |
| 브라우저 재설치 (수동) | `PLAYWRIGHT_BROWSERS_PATH=../.playwright-browsers ./venv/bin/playwright install chromium` |

> **Playwright 브라우저는 공용 캐시를 쓰지 않는다 (2026-09-09)**: 브라우저는 `PLAYWRIGHT_BROWSERS_PATH`로 지정한 **`Ozzycanton/.playwright-browsers`** 에 있다(canton-hub와 공유). 경로 정의의 단일 진실원은 `config.py`이고, LaunchAgent plist에도 같은 값이 들어 있다. 공용 캐시(`~/Library/Caches/ms-playwright`)로 되돌리지 말 것 — 같은 맥의 다른 프로젝트(gstack 등)가 더 최신 Playwright로 `playwright install`을 돌리면 자기가 참조하지 않는 구버전 빌드를 청소해버린다.

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
- LaunchAgent가 10시에 안 뜸 → Mac이 자고 있었을 가능성. **launchd `StartCalendarInterval`이 처리함**: 절전으로 10시를 놓치면 깨어날 때 launchd가 그 1회를 실행해줌(별도 코드 불필요). (참고: `bot.py`의 내부 `.last_sent` 보충 로직은 상주 스케줄러 모드용 잔존 코드이며, 현재 launchd `--now` 경로에선 쓰이지 않음.)

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
| 2026-07-01 | 트윗 요약 엔진 `claude -p` → `gemq`(Gemini) 교체 + 폴백 개선 | claude CLI OAuth 로그인 만료로 요약 실패 시 영어 원문이 채널에 그대로 송출된 사고. gemq(무료 Gemini, 인증 안정)로 교체하고, 실패 시 영어 덤프 대신 한국어 안내+원문 링크 폴백. stdout까지 로깅 + 재시도 2회 |
| 2026-07-02 | launchd 실행 모델: 상주 APScheduler 데몬 → `bot.py --now` 1회성 + `StartCalendarInterval` | 07-01 코드 수정이 상주 데몬에 반영 안 돼(재시작 누락) 요약이 다시 영어로 나감. 1회성 실행은 매번 새 프로세스라 항상 최신 코드 → stale-code 함정 제거. KeepAlive/RunAtLoad 제거, plist 백업=`*.bak.20260702` |
| 2026-07-04 | 텔레그램 HTML 태그 정제 + 평문 폴백 추가 | Gemini가 요약에 `<br>` 넣어 텔레그램 400(unsupported tag)으로 이미지·텍스트 둘 다 미전송 → 07-04 포스팅 누락. `tweet_summarizer._clean_html`이 비허용 태그 제거(`<br>`→줄바꿈), `bot.py`는 HTML 전송 실패 시 `_strip_html`로 평문 재전송(반드시 발송) |
| 2026-07-08 | 이미지 생성·전송 재시도(backoff) 추가 + 전송 로직 `_send_daily_post`로 분리 | 07-08 10:00 이미지 카드는 정상 생성(258KB)됐으나 `sendPhoto`가 순간 네트워크 블립(`httpx.ConnectError`→`NetworkError`)으로 1회 실패, **즉시** 텍스트 폴백해 그날 이미지 누락(1초 뒤 같은 호스트로 텍스트 전송은 성공 = 일회성 블립, 역대 82회 중 유일). 이제 이미지 생성/전송을 각 최대 3회 backoff 재시도(3s·6s)해 이미지+내용+요약을 항상 한 덩어리로 발송하고, 재시도까지 모두 실패한 극단적 경우에만 텍스트 폴백. `BadRequest`(내용 오류)는 재시도 안 함(구 07-04 경로 유지). 회귀 테스트 `test_send_retry.py`(mock, 12케이스, pytest 불필요) |
| 2026-07-17 | 트위터 소스 RapidAPI twitter241 → **ScrapeCreators**(`/v1/twitter/user-tweets`) 교체 + 트윗 0개 시 캡션 상태 표시 추가 | 07-17 10:00 twitter241이 전 엔드포인트 405("provider has disabled request access") 반환 → 트윗 0개로 반쪽 리포트(133자) 발송. **twitter241 개별 문제가 아니라 RapidAPI 게이트웨이 전역 장애**(무관한 weatherapi/jsearch/exercisedb도 동일 405, 키 없이·가짜 키도 동일 = 인증 이전 차단; Nokia 인수 후 방치 정황). 대안 조사 결과 last30days가 이미 쓰는 ScrapeCreators가 응답 스키마 동일(`legacy`/`core`/`views`)이라 `_parse_tweet` 거의 그대로 재사용, 크레딧 9천+(≈수년치) 선불됨. `SCRAPECREATORS_API_KEY`는 `~/.config/last30days/.env`와 동일 키 공유(같은 크레딧 풀). rest_id 조회 단계 제거(핸들 직접), 트윗 평면 리스트라 타임라인 순회 로직 삭제. `screen_name`은 `core.user_results.result.legacy.screen_name`(twitter241은 `.core.screen_name`)이라 양쪽 폴백. 고정 트윗이 선두로 오지만 24h cutoff가 자연 필터. **RAPIDAPI_KEY는 미사용이나 복구 대비 잔존**. `formatter.py`: 트윗 0개일 때 "수집에 실패" 한 줄 명시(조용한 반쪽 발송 방지). 미리보기 검증: @CantonNetwork 8 / @CantonFdn 3개 수집, 요약 918자, 회귀테스트 12/12 |
| 2026-09-09 | Playwright 브라우저를 공용 캐시에서 **전용 경로로 격리**(`PLAYWRIGHT_BROWSERS_PATH=Ozzycanton/.playwright-browsers`) + 09:45 사전 점검 LaunchAgent `com.cobling.playwright-ensure` 신설 | 09-08·09-09 이틀간 이미지 카드 없이 텍스트만 발송된 사고. 원인은 봇 코드가 아니라 **공용 브라우저 캐시의 버전 충돌** — `~/Library/Caches/ms-playwright`를 playwright 1.58.0(이 봇·허브)과 1.62.1(gstack)이 공유하는데, 최신 쪽이 `playwright install`을 돌리면 자기가 참조하지 않는 구버전 빌드를 청소한다. 이 봇이 쓰는 **1208 빌드가 09-07 10:00~09-08 10:00 사이에 사라졌다**. ⚠️ **정확한 트리거 이벤트는 특정하지 못했다** — 캐시에 남은 1234 설치 기록(09-08 22:59)은 첫 실패(09-08 10:00)보다 13시간 뒤라 그 설치가 범인은 아니고, 그 이전의 다른 install/prune으로 추정만 된다. 다만 메커니즘(공유 캐시+버전 편차→청소)은 확인됐고 처방은 트리거와 무관하게 유효하다. 봇은 3회 재시도 후 설계대로 텍스트 폴백해 발송 자체는 살아 있었고, canton-hub도 같은 브라우저를 써서 거래소 스크래핑 폴백이 **222회 조용히 실패**하고 있었다. 조치: ① `config.py`가 `PLAYWRIGHT_BROWSERS_PATH`를 `setdefault`로 지정(단일 진실원, 수동 실행에서도 적용) + `image_generator.py`가 `config`를 먼저 import해 단독 진입점에서도 격리 보장 ② `com.cobling.canton-bot.plist`에 같은 env 추가(백업 `*.bak.20260909-191940`) ③ `scripts/ensure-playwright.sh` — 빌드 번호를 하드코딩하지 않고 **실제 헤드리스 실행을 시도**해 실패 시 자동 재설치(나중에 pip으로 playwright를 올려 요구 빌드가 바뀌어도 그대로 동작). 검증: 공용 캐시의 1208을 지운 상태에서 데일리 카드 정상 생성(235,915 bytes), 브라우저 삭제 재현 후 스크립트가 `REPAIRED` 자동 복구, launchd 경유 실행 exit 0 |
| 2026-09-23 | 트윗 요약 엔진 `gemq`(Gemini) → `gptq`(ChatGPT, Codex CLI · ChatGPT 구독, 모델 `gpt-reserve`, 추론 low) | 09-20·22·23 요약 실패 — Gemini 구독 해지로 전 모델 429 "Individual quota reached"(호출당 ~2.5분 대기 후 실패 ×2회). 설계대로 한국어 폴백(원문 링크)으로 발송은 됐음. OpenAI API 키는 없고 Codex CLI가 ChatGPT 구독 로그인 상태라 그 경로 사용(토큰 과금 없음). `gpt-6-astra`는 비싸서 제외. 래퍼 `~/.local/bin/gptq`(gemq와 같은 사용법, 빈 임시폴더·read-only 샌드박스·PATH 보강). 검증: launchd 유사 최소 env로 미리보기 실행 → 요약 15초·661자 한국어 정상 |
| 2026-09-24 | 요약 엔진 `gptq` 단일 경로 → **`llmq` 다중 경로**(`daily` 체인: ChatGPT `gpt-5.6-luna` → Claude(Antigravity) → Gemini) + 한도 걸린 경로 쿨다운 + 전 경로 실패 시 Mac 알림 + 실패 로그를 stderr **끝부분**으로 기록 | 09-24 10:00 또 폴백 발송. 원인은 계정 한도가 아니라 **`gpt-reserve` 모델 전용 한도** 소진(앱 기준 공용 한도 96% 남음, 같은 계정 luna/terra/astra 정상) — 09-23의 모델 선택 실수. 로그가 stderr 앞 300자(프롬프트 반향)만 남겨 원인이 가려졌었다. 교훈: 구독 LLM은 언제든 한도/해지로 막히므로 단일 경로·단일 모델에 의존하지 않는다. 래퍼 `~/.local/bin/llmq`(`llmq --status`로 경로별 쿨다운 확인, 호출 기록 `~/.cache/llmq/llmq.log`). 검증: launchd 유사 최소 env 미리보기 → codex 경로 15초·868자 한국어, 쿨다운 강제 시 claude로 자동 전환, 회귀테스트 12/12 |
