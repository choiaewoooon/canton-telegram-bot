"""
Twitter/X 데이터 수집 모듈
ScrapeCreators API (api.scrapecreators.com)를 사용하여 Canton 관련 계정의
최근 트윗을 수집합니다.

흐름:
1. GET /v1/twitter/user-tweets?handle=<name> → 해당 계정의 최근 트윗(평면 리스트)
   - rest_id 조회 단계 불필요(핸들을 직접 받음)
   - 응답 트윗 노드는 여전히 tweet_results.result와 동일한 legacy/core 구조

교체 이력(2026-07-17): 기존 RapidAPI twitter241("Twttr API")가 게이트웨이
레벨로 전면 405("provider has disabled request access")를 반환 —
twitter241 개별 문제가 아니라 RapidAPI(Nokia 인수 후 방치) 전역 장애.
키·구독과 무관하게 모든 요청 차단됨. ScrapeCreators는 응답 스키마가
twitter241과 동일(legacy/core/views)해 파서를 거의 그대로 재사용.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import httpx

import config

logger = logging.getLogger(__name__)

SCRAPECREATORS_BASE = "https://api.scrapecreators.com"
USER_TWEETS_URL = f"{SCRAPECREATORS_BASE}/v1/twitter/user-tweets"


@dataclass
class TweetData:
    """수집된 트윗 데이터"""
    username: str
    text: str
    created_at: datetime
    url: str
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    media_urls: list = field(default_factory=list)


class TwitterCollector:
    """ScrapeCreators API 기반 트위터 수집기"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=20,
            headers={
                "x-api-key": config.SCRAPECREATORS_API_KEY,
            },
        )

    def _iter_tweet_nodes(self, payload: dict):
        """ScrapeCreators 응답에서 개별 트윗 노드를 순회.

        응답: {"success": bool, "credits_remaining": int, "tweets": [<node>, ...]}
        각 node는 twitter241의 tweet_results.result와 동일한 구조
        (rest_id / legacy / core / views 보유).
        """
        for node in payload.get("tweets", []) or []:
            if isinstance(node, dict):
                yield node

    def _parse_tweet(self, tw: dict, owner_username: str) -> TweetData | None:
        legacy = tw.get("legacy", {})
        full_text = legacy.get("full_text")
        created_raw = legacy.get("created_at")
        tweet_id = tw.get("rest_id") or legacy.get("id_str")
        if not (full_text and created_raw and tweet_id):
            return None

        try:
            created_at = parsedate_to_datetime(created_raw)
        except Exception:
            return None
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Screen name from tweet author. ScrapeCreators nests it under
        # core.user_results.result.legacy.screen_name (twitter241 used
        # ...result.core.screen_name). Try both, fall back to owner.
        user_result = (
            tw.get("core", {}).get("user_results", {}).get("result", {})
        )
        screen_name = (
            user_result.get("legacy", {}).get("screen_name")
            or user_result.get("core", {}).get("screen_name")
            or owner_username
        )
        # Modules/replies may carry other users' tweets — drop those.
        if screen_name.lower() != owner_username.lower():
            return None

        media_urls: list[str] = []
        for m in legacy.get("extended_entities", {}).get("media", []):
            u = m.get("media_url_https")
            if u:
                media_urls.append(u)

        views_val = tw.get("views", {}).get("count") or 0
        try:
            views = int(views_val)
        except Exception:
            views = 0

        return TweetData(
            username=screen_name,
            text=full_text,
            created_at=created_at,
            url=f"https://x.com/{screen_name}/status/{tweet_id}",
            likes=legacy.get("favorite_count", 0) or 0,
            retweets=legacy.get("retweet_count", 0) or 0,
            replies=legacy.get("reply_count", 0) or 0,
            views=views,
            media_urls=media_urls,
        )

    async def collect_recent_tweets(self, username: str) -> list[TweetData]:
        """특정 계정의 최근 트윗 수집 (지난 N시간)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=config.TWEET_HOURS_LOOKBACK)

        try:
            resp = await self.client.get(
                USER_TWEETS_URL, params={"handle": username}
            )
            resp.raise_for_status()
            payload = resp.json()

            tweets: list[TweetData] = []
            for tw_node in self._iter_tweet_nodes(payload):
                parsed = self._parse_tweet(tw_node, owner_username=username)
                if parsed is None:
                    continue
                # 고정(pinned) 트윗이 리스트 선두로 오는 경우가 있어 오래된 고정글이
                # 섞일 수 있음 — cutoff로 자연스럽게 걸러짐.
                if parsed.created_at < cutoff:
                    continue
                tweets.append(parsed)

            credits = payload.get("credits_remaining")
            logger.info(
                f"@{username}: {len(tweets)}개 트윗 수집 완료"
                + (f" (credits={credits})" if credits is not None else "")
            )
            return tweets

        except Exception as e:
            logger.error(f"@{username} 트윗 수집 실패: {e}")
            return []

    async def collect_all(self) -> dict[str, list[TweetData]]:
        """모든 대상 계정의 트윗 수집"""
        if not config.SCRAPECREATORS_API_KEY:
            logger.warning("SCRAPECREATORS_API_KEY가 설정되지 않았습니다.")
            return {}

        results: dict[str, list[TweetData]] = {}
        for account in config.TWITTER_ACCOUNTS:
            tweets = await self.collect_recent_tweets(account)
            results[account] = tweets
            await asyncio.sleep(1)  # Rate limit 방지
        return results

    async def close(self):
        await self.client.aclose()
