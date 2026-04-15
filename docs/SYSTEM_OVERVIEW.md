# SYSTEM_OVERVIEW.md

> **업데이트 트리거**: 새 Phase 진입 / ADR 추가·변경 / Known Issue 해결·추가 / Lessons Learned 갱신 시 이 문서를 먼저 수정한다.
> **읽는 순서**: Overview → Phase History → ADRs → Known Issues → Lessons Learned → Change Log

---

## 1. Project Overview

Canton Telegram Bot은 Canton Network 데이터를 하루 1회 수집하여 HTML+이미지 기반 리포트를 Telegram 채널에 게시하는 Python 파이프라인이다. 2026-04-15 legacy `canton-bot/`에서 분리되어 독립 배포 단위가 되었으며, 웹 대시보드(`canton-hub/`)와는 독립된 `collectors/` 사본을 유지한다. 목적은 단순·결정론적 1일 1회 리포트 전달이며, 웹 API나 실시간 기능은 범위 밖이다.

---

## 2. Phase History

| 날짜 | Phase | 내용 |
|------|-------|------|
| 2026-03-31 | P0 — Initial | Daily Canton report bot 최초 생성, 첫 버전 출시 |
| 2026-04-XX | P1 — Image | Jinja2 HTML 템플릿 → PNG 이미지 생성 추가 (Telegram 리치 포스트) |
| 2026-04-XX | P2 — Chart | matplotlib 기반 price chart 생성기 (base64) 추가 |
| 2026-04-XX | P3 — Summarizer | Canton 트윗 AI 요약 (tweet summarizer) 추가 |
| 2026-04-XX | P4 — Web expand | `canton-bot/` 리포에 FastAPI 백엔드 + Next.js 프론트엔드 확장 (웹 대시보드가 봇과 공존) |
| 2026-04-XX | P5 — Incident | **9am KST CoinGecko 429 incident** — 웹 scheduler와 bot이 Home Mac IP를 공유, CoinGecko rate limit 동시 히트, 봇 실패 |
| 2026-04-14 | P6 — RCA | Root cause 식별: 공유 `collectors/` 디렉토리 + 공유 rate limit |
| 2026-04-15 | P7 — Split | **Folder split** — `canton-bot/`을 `canton-hub/` (web) + `canton-telegram-bot/` (this bot)로 분리, 각자 독립 `collectors/` 사본 보유 |
| 2026-04-15 | P8 — Docs | docs-init 실행, AI Native 문서 체계 확립 |

---

## 3. Architecture Decision Records (ADRs)

### ADR-001: One-shot launchd (not APScheduler keep-alive)

| 항목 | 내용 |
|------|------|
| Status | Planned migration (현재 legacy KeepAlive 유지) |
| Decision | `StartCalendarInterval` + one-shot process 선호, `KeepAlive=true` + APScheduler 지양 |
| Reason | One-shot이 단순하고 추론이 쉬우며, bot.py crash 시 무한 재시작 없음 |
| Impact | 마이그레이션 시 plist 업데이트 필요 |
| Rule | 새로운 스케줄링 경로는 반드시 launchd cron 스타일로 작성 |

### ADR-002: Collectors never raise

| 항목 | 내용 |
|------|------|
| Status | Active |
| Decision | 모든 collector는 자체 예외를 catch하고 empty dataclass 반환 |
| Reason | 외부 API 1개의 실패가 daily report 전체를 중단시켜서는 안 됨 |
| Rule | `collectors/` 하위에서 `raise` **금지**. 대신 `logger.warning(...)` + empty return |
| 검증 | `grep -rn "raise " collectors/` → 0건이어야 함 |

### ADR-003: Image generation has text fallback

| 항목 | 내용 |
|------|------|
| Status | Active |
| Decision | 이미지 카드 전송 시도 → 실패 시 text-only 메시지로 fallback |
| Before | 이미지 실패 시 리포트 전체 abort |
| After | `bot.py`의 이미지 경로를 try/except로 감싸고 `send_message`로 fallback |
| Rule | 이미지는 nice-to-have, **텍스트가 계약(contract)** |

### ADR-004: Independent collectors copy (folder split, 2026-04-15)

| 항목 | 내용 |
|------|------|
| Status | Active |
| Decision | `canton-hub/collectors/`와 별개로 자체 `collectors/` 디렉토리 복제 보유 |
| Reason | 웹 scheduler와의 shared rate limit 제거, Home Mac ↔ Fly.io 독립 배포 가능, 한쪽 업데이트가 다른 쪽을 breaking하지 않음 |
| Before | 공유 `canton-bot/collectors/`를 `bot.py`와 `api/scheduler.py`가 함께 사용 |
| After | `canton-telegram-bot/collectors/` (this) + `canton-hub/collectors/` (web) 완전 독립 |
| Trade-off | 코드 중복 수용 — 배포 독립성이 DRY보다 우선 |
| Impact | 공통 버그 발견 시 수동 sync 또는 slight drift 수용 |

### ADR-005: Only 3 collectors (not all 11)

| 항목 | 내용 |
|------|------|
| Status | Active |
| Decision | 본 봇은 `twitter`, `cantonscan`, `price` 3개만 사용. `governance`, `holders`, `kr_companies`, `dex_oi`, `realtime_prices` 등은 drop |
| Reason | Daily report는 3개 지표만 필요, 나머지는 web dashboard 전용 |
| Rule | `canton-hub`의 collectors/에서 **import 금지**. 신규 collector 필요 시 로컬로 복사 |
| 검증 | `grep -rn "from canton_hub\|from canton-hub" .` → 0건 |

---

## 4. Known Issues

| ID | 이슈 | 심각도 | 상태 | 조치 |
|----|------|--------|------|------|
| KI-001 | LaunchAgent가 legacy KeepAlive 모드 — ADR-001대로 `StartCalendarInterval` one-shot으로 마이그레이션 필요 | Medium | Open | plist 재작성 예정 |
| KI-002 | 테스트 스위트 부재 — manual preview mode 검증만 가능 | Medium | Open | pytest 도입 TODO |
| KI-003 | Tweet summarizer의 AI API 의존성 미문서화 (openai? anthropic? TBD) | Low | Open | `summarizer/` 확인 후 ARCHITECTURE.md 반영 |
| KI-004 | `templates/daily_card.html`이 이전 문서에서 version-control되지 않음 (현재 ARCHITECTURE.md에만 기록) | Low | Resolved (2026-04-15) | ARCHITECTURE.md에 명시 완료 |

---

## 5. Lessons Learned

| # | Lesson | 배경 | 규칙 |
|---|--------|------|------|
| L1 | 공유 IP + 공유 API quota = 재앙 예약 | 9am KST CoinGecko 429 incident | 항상 rate-limited 리소스는 배포 단위로 분리 (ADR-004) |
| L2 | 텍스트는 **항상** 동작해야 함 — 리치 콘텐츠(이미지)는 optional | 이미지 실패로 리포트 전체 abort 사례 | ADR-003: fallback 필수 |
| L3 | launchd KeepAlive + 내부 scheduler는 launchd cron + one-shot보다 디버깅이 훨씬 어려움 | 무한 재시작 루프, 로그 추적 난이도 | ADR-001: one-shot 선호 |
| L4 | Collector 중복(`canton-hub` ↔ `canton-telegram-bot`)이 API consumer 리팩터보다 단순 | 배포 독립성이 DRY보다 중요한 scale | ADR-004: 중복 허용 |
| L5 | 개발 시 항상 preview mode(`TELEGRAM_BOT_TOKEN=`) 사용 — 프로덕션 채널 스팸 금지 | 과거 테스트 메시지 프로덕션 유출 | DEVELOPMENT_GUIDE.md에 preview mode 강제 |

---

## 6. Change Log

| 날짜 | 변경 | 이유 |
|------|------|------|
| 2026-04-14 | 초기 생성 | docs-init으로 자동 생성, `canton-bot/` 분리 후 첫 SYSTEM_OVERVIEW |
