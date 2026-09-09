"""
Canton Telegram Bot - 설정 파일
.env 파일에서 환경변수를 로드합니다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Playwright 브라우저 격리 (2026-09-09)
# ============================================================
# 공용 캐시(~/Library/Caches/ms-playwright)를 여러 프로젝트가 나눠 쓰면, 더 최신 Playwright가
# `playwright install`을 돌릴 때 자기가 참조하지 않는 구버전 빌드를 청소해버린다.
# 실제 사고: gstack(playwright 1.62.1)이 chromium 1234를 깔면서 여기서 쓰는 1208을 지웠고,
# 2026-09-08~09 이틀간 이미지 카드 렌더가 실패했다(봇은 텍스트 폴백으로 계속 발송됨).
# → Ozzycanton 전용 경로로 격리해 외부 도구의 청소 대상에서 제외한다.
# LaunchAgent plist에도 같은 값을 넣어두지만, 수동 실행 등 다른 진입점에서도 보장되도록 여기서 설정한다.
_OZZY_BROWSERS = Path(__file__).resolve().parent.parent / ".playwright-browsers"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_OZZY_BROWSERS))

# ============================================================
# Telegram 설정
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")  # 예: "@my_canton_channel" 또는 "-100xxxx"

# ============================================================
# Twitter/X 설정 (ScrapeCreators API)
# ============================================================
# 2026-07-17 RapidAPI twitter241 게이트웨이 전역 장애로 ScrapeCreators로 교체.
# RAPIDAPI_KEY는 복구/폴백 대비 남겨둠(현재 미사용).
SCRAPECREATORS_API_KEY = os.getenv("SCRAPECREATORS_API_KEY", "")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")  # deprecated (twitter241 사망)

# 모니터링 대상 트위터 계정
TWITTER_ACCOUNTS = ["CantonNetwork", "CantonFdn"]

# ============================================================
# CoinGecko 설정
# ============================================================
COINGECKO_COIN_ID = "canton-network"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
# CoinGecko Demo API Key (무료, 선택사항 - 레이트 리밋 완화)
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# ============================================================
# CantonScan 설정
# ============================================================
CANTONSCAN_STATS_URL = "https://www.cantonscan.com/stats"
CANTONSCAN_BASE_URL = "https://www.cantonscan.com"

# ============================================================
# canton-hub 로컬 백엔드 (가격 1차 소스, CoinGecko 직통은 폴백)
# ============================================================
CANTON_HUB_API_URL = os.getenv("CANTON_HUB_API_URL", "http://127.0.0.1:8000")

# ============================================================
# 스케줄 설정
# ============================================================
# 매일 아침 9시 (KST)
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "9"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")

# ============================================================
# 기타 설정
# ============================================================
# 트위터에서 가져올 최근 트윗 수
MAX_TWEETS_PER_ACCOUNT = 10
# 24시간 이내의 트윗만 수집
TWEET_HOURS_LOOKBACK = 24
