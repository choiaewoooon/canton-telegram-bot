# Canton Telegram Bot

매일 아침 9시(KST)에 Canton Network ($CC) 일일 리포트를 텔레그램 채널에 자동 포스팅하는 Python 파이프라인.

홈 Mac의 `launchd` LaunchAgent에서 구동한다. 별도 클라우드 호스팅 없이 돈다.

운영하며 겪은 함정(텔레그램 포맷 400, LLM 폴백 사고 등)과 처방은 [claude-code-harness의 운영 노트](https://github.com/choiaewoooon/claude-code-harness/blob/main/patterns/llm-daily-bot-ops.md)에 정리했다.

## Tech Stack

| 카테고리 | 기술 | 용도 |
|---|---|---|
| 런타임 | Python 3.11+ | 메인 |
| 텔레그램 | python-telegram-bot 21+ | 채널 전송 |
| HTTP | httpx 0.25+ | 외부 API 비동기 호출 |
| HTML 파싱 | beautifulsoup4 4.12+ | CantonScan HTML |
| 동적 스크래핑 | Playwright 1.40+ | CantonScan SPA 폴백 |
| 스케줄 | APScheduler 3.10+ (선택) · launchd (실제) | 9시 KST 실행 |
| 이미지 | Jinja2 3.1 + matplotlib 3.8+ | 일일 카드 PNG 생성 |
| 설정 | python-dotenv 1.0+ | `.env` 로드 |

## Getting Started

### Prerequisites

- Python 3.11+
- Telegram Bot Token (BotFather)
- Telegram Channel ID (봇을 채널에 admin으로 추가)
- RapidAPI Twitter API45 구독
- (선택) CoinGecko Demo API Key

### Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Configuration

`.env.example`을 `.env`로 복사 후 값 채우기:

```bash
cp .env.example .env
# 편집: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, RAPIDAPI_KEY, COINGECKO_API_KEY (선택)
```

### Development / Manual Test

```bash
# 미리보기 모드 (텔레그램 전송 없음, stdout에 HTML 태그를 제거한 텍스트 출력)
TELEGRAM_BOT_TOKEN= python bot.py --now

# 실제 전송 1회 (테스트 채널 권장)
python bot.py --now

# 스케줄러 모드 (매일 9시 자동) — launchd 대신 쓸 수도 있음
python bot.py
```

### Production (launchd on macOS)

```bash
# 1. 기존 LaunchAgent 언로드 (있으면)
launchctl unload ~/Library/LaunchAgents/com.cobling.canton-bot.plist 2>/dev/null

# 2. plist를 올바른 경로로 수정해서 배치
# ProgramArguments 의 python + bot.py 경로가 이 프로젝트로 가도록
# WorkingDirectory 도 마찬가지

# 3. 로드
launchctl load ~/Library/LaunchAgents/com.cobling.canton-bot.plist

# 4. 수동 테스트 실행
launchctl kickstart gui/$(id -u)/com.cobling.canton-bot

# 5. 로그 확인
tail -f launchd_stdout.log launchd_stderr.log bot.log
```

## Environment Variables

`.env.example` 참조:

| 변수 | 설명 | 필수 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API 토큰 (BotFather 발급) | O |
| `TELEGRAM_CHANNEL_ID` | 대상 채널 ID (`@channelname` 또는 `-100...`) | O |
| `RAPIDAPI_KEY` | Twitter API45 키 | O |
| `COINGECKO_API_KEY` | Demo 키 (레이트 리밋 방지) | 권장 |
| `SCHEDULE_HOUR` | 스케줄러 모드 발사 시(hour) | 기본 9 |
| `SCHEDULE_MINUTE` | 스케줄러 모드 발사 분(minute) | 기본 0 |
| `TIMEZONE` | 스케줄러 TZ | 기본 `Asia/Seoul` |

## Project Structure

```
canton-telegram-bot/
├── bot.py                     # 엔트리포인트 (--now | 스케줄러)
├── formatter.py               # HTML 메시지 생성
├── chart_generator.py         # matplotlib 차트 base64
├── image_generator.py         # Jinja2 카드 → PNG
├── tweet_summarizer.py        # 트윗 AI 요약
├── collectors/
│   ├── price_collector.py
│   ├── cantonscan_collector.py
│   └── twitter_collector.py
├── templates/
│   ├── daily_card.html        # Jinja 템플릿
│   └── assets/                # 이미지/폰트
├── config.py
├── requirements.txt
└── .env.example
```

## Key Features

| 기능 | 설명 | 상태 |
|---|---|---|
| 9시 KST 자동 포스팅 | launchd로 매일 1회 실행 | 구현됨 |
| 텔레그램 메시지 | `$CC 가격 + B/M Ratio + mint/burn + 트윗 AI 요약` HTML | 구현됨 |
| 일일 카드 이미지 | Jinja2 HTML 템플릿 → matplotlib 차트 → PNG (send_photo caption) | 구현됨 |
| 텍스트 폴백 | 이미지 생성 실패 시 텍스트만 전송 | 구현됨 |
| 트윗 AI 요약 | `tweet_summarizer.py` | 구현됨 |
| 미리보기 모드 | `TELEGRAM_BOT_TOKEN=` 비워서 stdout 덤프 | 구현됨 |

## Related Docs

| 문서 | 설명 |
|---|---|
| [CLAUDE.md](./CLAUDE.md) | 에이전트 운영 매뉴얼 |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 파이프라인 설계 |
| [docs/DATA_GUIDE.md](./docs/DATA_GUIDE.md) | 외부 데이터 소스 |
| [docs/DEVELOPMENT_GUIDE.md](./docs/DEVELOPMENT_GUIDE.md) | 코딩 표준 |
| [docs/SYSTEM_OVERVIEW.md](./docs/SYSTEM_OVERVIEW.md) | 결정 기록 |
| [../canton-hub/](../canton-hub/) | 관련 프로젝트: Canton 웹 대시보드 (별도 레포) |
