"""
텔레그램 메시지 포매터
수집된 데이터를 코블린 채널 톤앤매너에 맞게 변환합니다.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from collectors import TweetData, CantonScanData, PriceData
import config


def _fmt_cc(n: float | None) -> str:
    if n is None:
        return "N/A"
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:,.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:,.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:,.1f}K"
    return f"{n:,.0f}"


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
    if n >= 1_000:
        return f"${n / 1_000:,.0f}K"
    return f"${n:,.2f}"


def build_daily_report(
    tweets: dict[str, list[TweetData]],
    scan_data: CantonScanData,
    price_data: PriceData,
    tweet_summary: str = "",
) -> str:
    """일일 리포트 텔레그램 메시지 생성 (HTML 파싱 모드)"""

    kst = ZoneInfo(config.TIMEZONE)
    now = datetime.now(kst)
    date_str = now.strftime("%Y.%m.%d %a")

    lines = []

    # ── 헤더 ──
    lines.append(f"<b>Canton Daily | {date_str}</b>")
    lines.append("")

    # ── $CC 가격 (한 줄) ──
    if price_data.fetched:
        pct = price_data.price_change_percentage_24h
        if pct is not None:
            arrow = "+" if pct >= 0 else ""
            lines.append(
                f"<b>$CC {_fmt_usd(price_data.current_price_usd)}</b>"
                f"  ({arrow}{pct:.2f}%)"
            )
        else:
            lines.append(f"<b>$CC {_fmt_usd(price_data.current_price_usd)}</b>")
    else:
        lines.append("$CC 가격 데이터 수집 실패")

    # ── B/M Ratio + Mint/Burn ──
    if scan_data.fetched:
        if scan_data.burn_mint_ratio is not None:
            ratio = scan_data.burn_mint_ratio
            status = "디플레이션" if ratio >= 1 else "인플레이션"
            lines.append(f"\U0001f525 <b>B/M Ratio: {ratio:.4f}x</b> ({status})")
            if scan_data.daily_mint is not None and scan_data.daily_burn is not None:
                lines.append(
                    f"Mint {_fmt_cc(scan_data.daily_mint)} CC"
                    f" → Burn {_fmt_cc(scan_data.daily_burn)} CC"
                )
    else:
        lines.append("네트워크 데이터 수집 실패")
    lines.append("")

    # ── 트위터 소식 (AI 요약) ──
    total_tweets = sum(len(tw_list) for tw_list in tweets.values())
    if total_tweets > 0 and tweet_summary:
        lines.append(f"<b>\U0001f5de\ufe0f 트위터 소식 정리</b>")
        lines.append(f"<blockquote>{tweet_summary}</blockquote>")
        lines.append("")
    elif total_tweets > 0:
        lines.append(f"<b>\U0001f5de\ufe0f 트위터 소식 정리</b>")
        # 요약이 비어서 온 경우: 영어 원문을 그대로 덤프하지 않고 한국어 안내 + 원문 링크만.
        fallback_lines = ["· 오늘 트위터 요약을 불러오지 못함. 원문 링크만 첨부:"]
        for account, tw_list in tweets.items():
            if not tw_list:
                continue
            for tw in sorted(tw_list, key=lambda t: t.created_at, reverse=True)[:3]:
                when = tw.created_at.strftime("%m/%d %H:%M")
                fallback_lines.append(f'· @{tw.username} ({when}) <a href="{tw.url}">원문</a>')
        lines.append(f"<blockquote>{chr(10).join(fallback_lines)}</blockquote>")
        lines.append("")
    else:
        # 트윗 0개: 수집기가 조용히 실패했을 수 있음(2026-07-17 twitter241 사망 사고).
        # 아무 표시 없이 반쪽 리포트를 내보내지 않도록 명시적으로 상태를 남긴다.
        lines.append(f"<b>\U0001f5de️ 트위터 소식 정리</b>")
        lines.append("<blockquote>· 오늘은 새 트윗이 없거나 수집에 실패했습니다.</blockquote>")
        lines.append("")


    return "\n".join(lines)
