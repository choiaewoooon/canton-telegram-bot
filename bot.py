"""
Canton Telegram Bot - 메인 실행 파일
매일 아침 9시(KST)에 Canton 네트워크 일일 리포트를 텔레그램 채널에 포스팅합니다.

사용법:
  python bot.py          # 스케줄러 모드 (매일 9시 자동 실행)
  python bot.py --now    # 즉시 1회 실행 (테스트용)
"""
import asyncio
import argparse
import logging
import re
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError


def _strip_html(text: str) -> str:
    """HTML 파싱 실패 시 최후 폴백: 모든 태그 제거 + 엔티티 복원 → 평문."""
    t = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    return (
        t.replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&")
    )

import config
from collectors import TwitterCollector, CantonScanCollector, PriceCollector
from formatter import build_daily_report
from chart_generator import generate_chart_base64
from image_generator import generate_daily_card
from tweet_summarizer import summarize_tweets

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("canton_bot")

# 이미지 카드 생성·전송 재시도 설정.
# 순간 네트워크 블립(2026-07-08: httpx.ConnectError로 sendPhoto 1회 실패 → 그날 이미지 누락)에
# 대비해, 이미지가 캡션과 함께 항상 한 덩어리로 나가도록 생성/전송을 backoff 재시도한다.
IMAGE_MAX_ATTEMPTS = 3      # 생성·전송 각각 최대 시도 횟수
IMAGE_RETRY_BASE_SEC = 3    # backoff 기준(초): 시도 사이 3s, 6s 대기 (마지막 시도 뒤엔 대기 없음)

# 마지막으로 리포트를 성공 발송한 KST 날짜(YYYY-MM-DD)를 기록하는 상태 파일.
# 절전/재기동으로 스케줄 시각을 놓쳤을 때 당일 1회 보충 발송을 판단하는 근거.
STATE_FILE = Path(__file__).resolve().parent / ".last_sent"


def _read_last_sent_date() -> str:
    """마지막 발송 날짜(YYYY-MM-DD) 반환. 없으면 빈 문자열."""
    try:
        return STATE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.warning(f"상태 파일 읽기 실패: {e}")
        return ""


def _write_last_sent_date(date_str: str) -> None:
    """발송 성공 시 오늘 날짜를 기록. 실패해도 파이프라인은 죽이지 않음."""
    try:
        STATE_FILE.write_text(date_str, encoding="utf-8")
    except Exception as e:
        logger.warning(f"상태 파일 기록 실패: {e}")


async def _send_daily_post(bot, channel_id, message: str, image_bytes: bytes | None) -> None:
    """이미지 카드 + 캡션(내용+트윗요약)을 항상 한 덩어리로 전송한다.

    순간 네트워크 블립(httpx.ConnectError → telegram NetworkError)으로 이미지가 빠지지
    않도록 전송을 backoff 재시도한다. 이미지·내용·요약은 함께 나가며, 재시도까지 모두
    실패한 극단적 경우에만 텍스트 폴백으로 당일 리포트를 발송한다(사용자 선택 2026-07-08).
    """
    if image_bytes:
        for attempt in range(1, IMAGE_MAX_ATTEMPTS + 1):
            try:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=BytesIO(image_bytes),
                    caption=message,
                    parse_mode=ParseMode.HTML,
                )
                logger.info("이미지 + 텍스트 전송 완료")
                return
            except BadRequest as e:
                # HTML 캡션 파싱 오류(미허용 태그 등) → 재시도해도 동일. 평문 폴백으로.
                logger.warning(f"HTML 캡션 파싱 오류로 이미지 전송 실패 → 평문 폴백: {e}")
                break
            except NetworkError as e:
                # 일시적 네트워크 오류(ConnectError/타임아웃) → backoff 후 재시도
                logger.warning(
                    f"이미지 전송 네트워크 오류, 재시도 (시도 {attempt}/{IMAGE_MAX_ATTEMPTS}): {e}"
                )
                if attempt < IMAGE_MAX_ATTEMPTS:
                    await asyncio.sleep(attempt * IMAGE_RETRY_BASE_SEC)
            except Exception as e:
                # 비일시적 오류(권한 등) → 재시도 무의미. 텍스트 폴백으로.
                logger.warning(f"이미지 전송 실패(비일시적) → 텍스트 폴백: {e!r}")
                break
        else:
            # for-else: break 없이 모든 재시도 소진(네트워크 오류만 반복)
            logger.error(f"이미지 전송 {IMAGE_MAX_ATTEMPTS}회 모두 실패 → 텍스트 폴백(최후)")

    # 최후 폴백: 이미지가 끝내 실패하면 텍스트라도 반드시 발송
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        logger.warning(f"HTML 파싱 실패 → 평문으로 재전송: {e}")
        await bot.send_message(
            chat_id=channel_id,
            text=_strip_html(message),
            disable_web_page_preview=True,
        )


async def collect_and_post():
    """데이터 수집 후 텔레그램 포스팅"""
    kst = ZoneInfo(config.TIMEZONE)
    logger.info(f"=== 일일 리포트 시작 ({datetime.now(kst).strftime('%Y-%m-%d %H:%M')}) ===")

    # ── 수집기 초기화 ──
    twitter = TwitterCollector()
    cantonscan = CantonScanCollector()
    price = PriceCollector()

    try:
        # ── 데이터 수집 (병렬) ──
        logger.info("데이터 수집 시작...")

        tweets, scan_data, price_data = await asyncio.gather(
            twitter.collect_all(),
            cantonscan.collect(),
            price.collect(),
            return_exceptions=True,
        )

        # 예외 처리
        if isinstance(tweets, Exception):
            logger.error(f"트위터 수집 오류: {tweets}")
            tweets = {}
        if isinstance(scan_data, Exception):
            logger.error(f"CantonScan 수집 오류: {scan_data}")
            from collectors import CantonScanData
            scan_data = CantonScanData()
        if isinstance(price_data, Exception):
            logger.error(f"가격 수집 오류: {price_data}")
            from collectors import PriceData
            price_data = PriceData()

        # ── 트윗 AI 요약 ──
        tweet_summary = ""
        if tweets:
            tweet_summary = await summarize_tweets(tweets)

        # ── 메시지 생성 ──
        message = build_daily_report(tweets, scan_data, price_data, tweet_summary)
        logger.info(f"메시지 생성 완료 ({len(message)} chars)")

        # ── 텔레그램 전송 ──
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
            logger.info("--- 미리보기 ---")
            # HTML 태그 제거한 미리보기
            import re
            preview = re.sub(r"<[^>]+>", "", message)
            print(preview)
            return

        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

        if not config.TELEGRAM_CHANNEL_ID:
            logger.error("TELEGRAM_CHANNEL_ID가 설정되지 않았습니다!")
            return

        # 이미지 카드 생성(재시도) + 캡션으로 단일 게시물 전송.
        # 이미지·내용·트윗요약은 항상 한 덩어리로 나간다(_send_daily_post).
        kst_now = datetime.now(kst)
        date_str = kst_now.strftime("%Y.%m.%d %a")

        # ── 이미지 카드 생성 (일시적 실패 대비 재시도) ──
        image_bytes = None
        try:
            chart_b64 = await generate_chart_base64()
            for attempt in range(1, IMAGE_MAX_ATTEMPTS + 1):
                image_bytes = await generate_daily_card(
                    scan_data, price_data, date_str, chart_b64
                )
                if image_bytes:
                    break
                logger.warning(f"이미지 카드 생성 실패 (시도 {attempt}/{IMAGE_MAX_ATTEMPTS})")
                if attempt < IMAGE_MAX_ATTEMPTS:
                    await asyncio.sleep(attempt * IMAGE_RETRY_BASE_SEC)
        except Exception as e:
            logger.warning(f"차트/이미지 생성 중 예외 → 텍스트 폴백: {e!r}")

        # ── 전송: 이미지+내용+요약을 한 덩어리로(재시도). 끝내 실패 시 텍스트 폴백 ──
        await _send_daily_post(bot, config.TELEGRAM_CHANNEL_ID, message, image_bytes)

        logger.info(f"텔레그램 전송 완료 -> {config.TELEGRAM_CHANNEL_ID}")
        # 발송 성공 → 오늘 날짜 기록 (재기동 시 중복 발송 방지 + 보충 발송 판단 근거)
        _write_last_sent_date(kst_now.strftime("%Y-%m-%d"))

    except Exception as e:
        logger.error(f"리포트 처리 중 오류: {e}", exc_info=True)

    finally:
        await cantonscan.close()
        await price.close()

    logger.info("=== 일일 리포트 완료 ===")


def run_scheduler():
    """APScheduler로 매일 지정 시간에 실행"""
    kst = ZoneInfo(config.TIMEZONE)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    scheduler = AsyncIOScheduler(timezone=kst, event_loop=loop)
    scheduler.add_job(
        collect_and_post,
        trigger="cron",
        hour=config.SCHEDULE_HOUR,
        minute=config.SCHEDULE_MINUTE,
        id="daily_canton_report",
        name="Canton Daily Report",
        misfire_grace_time=3600,  # 최대 1시간 지연 허용
    )

    scheduler.start()
    logger.info(
        f"스케줄러 시작: 매일 {config.SCHEDULE_HOUR:02d}:{config.SCHEDULE_MINUTE:02d} KST 실행"
    )

    # ── 재기동 보충 발송 ──
    # 절전/재시작으로 오늘 스케줄 시각을 놓쳤고 아직 미발송이면 즉시 1회 보충.
    # APScheduler는 프로세스가 죽어 있던 동안의 미스파이어를 자동 보충하지 않으므로 필요.
    now_kst = datetime.now(kst)
    today_str = now_kst.strftime("%Y-%m-%d")
    scheduled_today = now_kst.replace(
        hour=config.SCHEDULE_HOUR, minute=config.SCHEDULE_MINUTE, second=0, microsecond=0
    )
    if now_kst >= scheduled_today and _read_last_sent_date() != today_str:
        logger.info("재기동 감지: 오늘 리포트 미발송 → 즉시 보충 실행")
        scheduler.add_job(collect_and_post, trigger="date", id="catch_up_report")

    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("봇 종료")
        scheduler.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Canton Telegram Bot")
    parser.add_argument("--now", action="store_true", help="즉시 1회 실행 (테스트용)")
    args = parser.parse_args()

    # 설정 검증
    warnings = []
    if not config.TELEGRAM_BOT_TOKEN:
        warnings.append("TELEGRAM_BOT_TOKEN 미설정 (미리보기 모드로 동작)")
    if not config.TELEGRAM_CHANNEL_ID:
        warnings.append("TELEGRAM_CHANNEL_ID 미설정")
    if not config.RAPIDAPI_KEY:
        warnings.append("RAPIDAPI_KEY 미설정 (트윗 수집 불가)")

    for w in warnings:
        logger.warning(f"[설정] {w}")

    if args.now:
        logger.info("즉시 실행 모드")
        asyncio.run(collect_and_post())
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
