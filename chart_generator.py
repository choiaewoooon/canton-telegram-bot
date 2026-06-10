"""
$CC 24시간 가격 차트 생성
CoinGecko OHLC 데이터 → matplotlib 캔들스틱 차트 → base64 이미지
"""
import base64
import logging
from io import BytesIO
from datetime import datetime, timezone, timedelta

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch

import config

logger = logging.getLogger(__name__)

# 다크 테마 색상 (이미지 카드와 통일)
BG_COLOR = "#0a0a0a"
GRID_COLOR = "#1a1a1a"
TEXT_COLOR = "#777777"
UP_COLOR = "#c8e64a"
DOWN_COLOR = "#ff5a5a"
LINE_COLOR = "#c8e64a"


def _parse_hub_time(s: str) -> datetime:
    """canton-hub의 '%m/%d %H:%M' 문자열을 UTC datetime으로 복원.

    연도가 빠져 있어 현재 연도를 부여하되, 연말/연초 경계에서 미래로
    튀면(>2일) 직전 연도로 롤백한다.
    """
    now = datetime.now(timezone.utc)
    dt = datetime.strptime(s, "%m/%d %H:%M").replace(year=now.year, tzinfo=timezone.utc)
    if dt - now > timedelta(days=2):
        dt = dt.replace(year=now.year - 1)
    return dt


async def fetch_ohlc_from_canton_hub() -> list[dict]:
    """canton-hub 로컬 백엔드의 캐시된 OHLC 조회 (1차 소스).

    canton-hub는 파일 캐시 폴백을 갖고 있어 CoinGecko 429에도 마지막
    정상 데이터를 서빙한다. 가격 수집과 동일하게 직통 호출을 회피한다.
    """
    url = f"{config.CANTON_HUB_API_URL}/api/chart/price"
    params = {"period": "24h"}

    async with httpx.AsyncClient(timeout=3) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        raw = resp.json()

    candles = []
    for item in raw:
        candles.append({
            "time": _parse_hub_time(item["time"]),
            "open": item["open"],
            "high": item["high"],
            "low": item["low"],
            "close": item["close"],
        })
    return candles


async def fetch_ohlc_data() -> list[dict]:
    """CoinGecko에서 24시간 OHLC 데이터 가져오기"""
    url = f"{config.COINGECKO_API_URL}/coins/{config.COINGECKO_COIN_ID}/ohlc"
    params = {"vs_currency": "usd", "days": "1"}

    headers = {"Accept": "application/json"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        raw = resp.json()

    candles = []
    for item in raw:
        ts, o, h, l, c = item
        candles.append({
            "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        })

    return candles


def render_chart(candles: list[dict]) -> str:
    """캔들스틱 차트를 base64 PNG로 렌더링"""
    if not candles:
        return ""

    fig, ax = plt.subplots(figsize=(7.2, 2.8), dpi=150)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    times = [c["time"] for c in candles]
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    # 캔들 폭 계산
    if len(times) >= 2:
        width = (times[1] - times[0]).total_seconds() / 86400 * 0.6
    else:
        width = 0.01

    for i in range(len(candles)):
        color = UP_COLOR if closes[i] >= opens[i] else DOWN_COLOR

        # 심지 (wick)
        ax.plot(
            [times[i], times[i]], [lows[i], highs[i]],
            color=color, linewidth=0.8, solid_capstyle="round"
        )

        # 몸통 (body)
        body_low = min(opens[i], closes[i])
        body_high = max(opens[i], closes[i])
        body_height = max(body_high - body_low, (highs[i] - lows[i]) * 0.01)

        rect = plt.Rectangle(
            (mdates.date2num(times[i]) - width / 2, body_low),
            width, body_height,
            facecolor=color, edgecolor=color, linewidth=0.5,
            alpha=0.9
        )
        ax.add_patch(rect)

    # 스타일링
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    ax.tick_params(colors=TEXT_COLOR, labelsize=7, length=0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.4f}"))

    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.grid(True, axis="y", color=GRID_COLOR, linewidth=0.5, alpha=0.5)
    ax.grid(True, axis="x", color=GRID_COLOR, linewidth=0.3, alpha=0.3)

    # 현재가 점선
    last_price = closes[-1]
    ax.axhline(y=last_price, color=LINE_COLOR, linewidth=0.6, linestyle="--", alpha=0.5)

    # 여백
    plt.subplots_adjust(left=0.12, right=0.98, top=0.95, bottom=0.15)

    # PNG → base64
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)

    b64 = base64.b64encode(buf.read()).decode("utf-8")
    logger.info(f"차트 이미지 생성 완료 ({len(candles)}개 캔들)")
    return b64


async def generate_chart_base64() -> str:
    """OHLC 데이터 가져와서 base64 차트 반환.

    1차: canton-hub 로컬 캐시 (파일 캐시 폴백 보유, 429 내성)
    2차: CoinGecko 직통 (canton-hub 미가동 시 폴백)
    """
    # 1차: canton-hub 로컬 백엔드
    try:
        candles = await fetch_ohlc_from_canton_hub()
        if candles:
            chart = render_chart(candles)
            if chart:
                return chart
    except Exception as e:
        logger.warning(f"canton-hub 차트 조회 실패, CoinGecko 직통으로 폴백: {e}")

    # 2차: CoinGecko 직통
    try:
        candles = await fetch_ohlc_data()
        return render_chart(candles)
    except Exception as e:
        logger.error(f"차트 생성 실패: {e}")
        return ""
