"""
일일 리포트 데이터 카드 이미지 생성
HTML 템플릿 + Playwright 스크린샷 방식
"""
import base64
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
# config를 먼저 로드해 PLAYWRIGHT_BROWSERS_PATH(전용 브라우저 경로)를 보장한다.
# bot.py를 거치지 않고 이 모듈만 단독으로 import하는 경우에도 격리가 깨지지 않도록 하기 위함.
import config  # noqa: F401
from playwright.async_api import async_playwright

from collectors import CantonScanData, PriceData

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
ASSETS_DIR = TEMPLATE_DIR / "assets"


def _load_image_b64(filename: str) -> str:
    """assets 폴더의 이미지를 base64 data URI로 변환"""
    path = ASSETS_DIR / filename
    if not path.exists():
        return ""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = path.suffix.lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return f"data:{mime};base64,{b64}"


def _fmt_cc(n: float | None) -> str:
    if n is None:
        return "N/A"
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:,.2f}B CC"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:,.1f}M CC"
    return f"{n:,.0f} CC"


def _fmt_usd(n: float | None) -> str:
    if n is None:
        return "N/A"
    if n >= 1:
        return f"${n:,.2f}"
    return f"${n:.4f}"


def _fmt_large_usd(n: float | None) -> str:
    if n is None:
        return "N/A"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:,.2f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:,.1f}M"
    return f"${n:,.0f}"


async def generate_daily_card(
    scan_data: CantonScanData,
    price_data: PriceData,
    date_str: str,
    chart_b64: str = "",
) -> bytes | None:
    """데이터 카드 이미지 생성, PNG bytes 반환"""

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("daily_card.html")

    bm_ratio = scan_data.burn_mint_ratio or 0

    profile_b64 = _load_image_b64("profile.jpg")
    logo_b64 = _load_image_b64("canton_logo.jpg")

    # 가격 등락에 따른 스티커
    pct = price_data.price_change_percentage_24h or 0
    sticker_b64 = _load_image_b64("gm.webp") if pct >= 0 else _load_image_b64("rekt.webp")
    sticker_text = "GM" if pct >= 0 else "개물림"

    html = template.render(
        date_str=date_str,
        profile_b64=profile_b64,
        logo_b64=logo_b64,
        sticker_b64=sticker_b64,
        sticker_text=sticker_text,
        price=price_data,
        price_usd=_fmt_usd(price_data.current_price_usd),
        price_change_pct=price_data.price_change_percentage_24h or 0,
        low_24h=_fmt_usd(price_data.low_24h),
        high_24h=_fmt_usd(price_data.high_24h),
        volume_24h=_fmt_large_usd(price_data.total_volume_24h),
        market_cap=_fmt_large_usd(price_data.market_cap),
        avg_amulet_price=_fmt_usd(scan_data.avg_amulet_price),
        scan=scan_data,
        bm_ratio=bm_ratio,
        mint_cc=_fmt_cc(scan_data.daily_mint),
        burn_cc=_fmt_cc(scan_data.daily_burn),
        chart_b64=chart_b64,
        app_rewards=_fmt_cc(scan_data.app_rewards),
        val_rewards=_fmt_cc(scan_data.validator_rewards),
        total_minted=_fmt_cc(scan_data.cumulative_mint),
        total_burned=_fmt_cc(scan_data.cumulative_burn),
        cum_burn_ratio=(
            (scan_data.cumulative_burn / scan_data.cumulative_mint * 100)
            if scan_data.cumulative_mint and scan_data.cumulative_burn
            else 0
        ),
    )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": 800, "height": 600},
                device_scale_factor=2,
            )
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(500)

            # wrapper div 높이 + body padding 포함
            card_height = await page.evaluate("""
                () => {
                    const wrapper = document.getElementById('card-wrapper');
                    const body = document.body;
                    const bodyStyle = getComputedStyle(body);
                    const padTop = parseFloat(bodyStyle.paddingTop);
                    const padBot = parseFloat(bodyStyle.paddingBottom);
                    return wrapper.getBoundingClientRect().height + padTop + padBot;
                }
            """)
            card_height = int(card_height) + 2
            await page.set_viewport_size({"width": 800, "height": card_height})
            image_bytes = await page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": 800, "height": card_height},
            )
            await browser.close()

        logger.info(f"데이터 카드 이미지 생성 완료 ({len(image_bytes):,} bytes)")
        return image_bytes

    except Exception as e:
        logger.error(f"이미지 생성 실패: {e}")
        return None
