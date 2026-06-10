"""
트윗 요약 모듈
Claude Code headless를 사용하여 수집된 트윗을 깔끔하게 요약합니다.
"""
import asyncio
import logging

from collectors import TweetData

logger = logging.getLogger(__name__)


async def summarize_tweets(tweets: dict[str, list[TweetData]]) -> str:
    """수집된 트윗들을 AI로 요약 + 원문 링크 포함하여 반환 (HTML)"""

    total = sum(len(tw_list) for tw_list in tweets.values())
    if total == 0:
        return ""

    # 트윗 원문을 프롬프트용 텍스트로 변환
    raw_lines = []
    all_tweets: list[TweetData] = []
    for account, tw_list in tweets.items():
        for tw in sorted(tw_list, key=lambda t: t.created_at, reverse=True):
            all_tweets.append(tw)
            raw_lines.append(
                f"@{tw.username} ({tw.created_at.strftime('%m/%d %H:%M')}): "
                f"{tw.text} "
                f"[likes:{tw.likes} RT:{tw.retweets} views:{tw.views}]"
            )

    raw_text = "\n".join(raw_lines)

    # 트윗 URL 매핑 (프롬프트에 포함시켜 AI가 링크를 달 수 있게)
    tweet_refs = []
    for i, tw in enumerate(all_tweets):
        tweet_refs.append(f"[{i+1}] @{tw.username}: {tw.text[:100]} → {tw.url}")

    ref_text = "\n".join(tweet_refs)

    prompt = f"""아래는 Canton Network 트위터 계정들의 최근 24시간 트윗이다.

텔레그램 채널 공지에 들어갈 트위터 요약을 작성해라.

톤앤매너 (코블린 @cobling 채널 스타일):
- 반말 + "~됨/~함/~인 듯/~하는 중" 체의 간결한 구어체
- 팩트 나열 위주, 과장이나 실러 톤 없이 건조하게
- 감상은 짧게 1문장 이내, 자조적 유머 OK ("제발ㅋㅋ", "ㅇㄱㅈ" 등)
- 이모지 최소한. 거의 안 씀

포맷 규칙:
- 텔레그램 HTML 태그만 사용 (<b>, <a href="URL">텍스트</a> 만 가능. 마크다운 금지)
- 핵심 3-5개 항목만. 비슷한 내용은 하나로 합쳐라
- 각 항목 앞에 · 사용
- 각 항목 사이에 빈 줄 한 줄을 반드시 넣어 시각적으로 분리 (즉, 항목 구분은 \n\n)
- 각 항목 문장 끝에 해당 트윗 원문 링크를 넣어라. 형식: <a href="트윗URL">원문</a>
- 반응(likes/views) 높은 트윗에 가중치
- 항목별 길이는 자유롭게(빈 줄 포함 8~12줄 가능)
- 앞뒤에 빈 줄이나 제목 붙이지 마라. 요약 본문만 출력해라

트윗 원문 (번호 → URL):
{raw_text}

URL 참조:
{ref_text}"""

    try:
        process = await asyncio.create_subprocess_exec(
            "/opt/homebrew/bin/claude", "-p", prompt,
            "--output-format", "text",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Claude 호출 실패: {stderr.decode()}")
            summary = _fallback_format(all_tweets)
        else:
            summary = stdout.decode().strip()
            logger.info(f"트윗 요약 완료 ({len(summary)} chars)")

    except FileNotFoundError:
        logger.warning("claude CLI를 찾을 수 없습니다. 기본 포맷으로 대체합니다.")
        summary = _fallback_format(all_tweets)
    except Exception as e:
        logger.error(f"트윗 요약 실패: {e}")
        summary = _fallback_format(all_tweets)

    return summary


def _fallback_format(all_tweets: list[TweetData]) -> str:
    """Claude 실패 시 기본 포맷"""
    lines = []
    for tw in all_tweets[:5]:
        text = tw.text.replace("<", "&lt;").replace(">", "&gt;")
        if len(text) > 120:
            text = text[:117] + "..."
        lines.append(f"· {text}")
    return "\n\n".join(lines)
