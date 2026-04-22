"""
Canton Telegram Bot - 설정 파일
.env 파일에서 환경변수를 로드합니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Telegram 설정
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")  # 예: "@my_canton_channel" 또는 "-100xxxx"

# ============================================================
# Twitter/X 설정 (RapidAPI - Twitter API45)
# ============================================================
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

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
