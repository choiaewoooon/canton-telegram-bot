"""
Twitter/X 데이터 수집 모듈
RapidAPI Twttr API (twitter241.p.rapidapi.com)를 사용하여 Canton 관련 계정의
최근 트윗을 수집합니다.

흐름:
1. /user?username=<name> → rest_id 조회 (한 번 성공하면 프로세스 수명 동안 메모리 캐시)
2. /user-replies?user=<rest_id>&count=40 → 본인 트윗 + 리플라이 포함 타임라인
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import httpx

import config

logger = logging.getLogger(__name__)

RAPIDAPI_HOST = "twitter241.p.rapidapi.com"
USER_URL = f"https://{RAPIDAPI_HOST}/user"
USER_REPLIES_URL = f"https://{RAPIDAPI_HOST}/user-replies"


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


# Process-lifetime cache: screen_name → Twitter numeric user_id (rest_id).
# Avoids an extra /user lookup every 15-minute collection cycle.
_user_id_cache: dict[str, str] = {}


class TwitterCollector:
    """RapidAPI Twttr API 기반 트위터 수집기"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15,
            headers={
                "x-rapidapi-host": RAPIDAPI_HOST,
                "x-rapidapi-key": config.RAPIDAPI_KEY,
            },
        )

    async def _resolve_user_id(self, username: str) -> str | None:
        """username → rest_id. 첫 호출만 네트워크, 이후는 메모리 캐시."""
        cached = _user_id_cache.get(username)
        if cached:
            return cached
        try:
            resp = await self.client.get(USER_URL, params={"username": username})
            resp.raise_for_status()
            data = resp.json()
            rest_id = (
                data.get("result", {})
                .get("data", {})
                .get("user", {})
                .get("result", {})
                .get("rest_id")
            )
            if rest_id:
                _user_id_cache[username] = rest_id
                return rest_id
        except Exception as e:
            logger.error(f"@{username} rest_id 조회 실패: {e}")
        return None

    def _iter_tweet_entries(self, payload: dict):
        """타임라인 응답에서 개별 tweet_results.result 노드를 순회.

        응답 구조: result.timeline.instructions[] 중
        - TimelineAddEntries.entries[] (리스트)
        - 또는 entry 단일 (pinned)
        각 entry의 content가 TimelineTimelineItem(단일 트윗) 혹은
        TimelineTimelineModule(대화 스레드 — items[] 포함)일 수 있음.
        """
        timeline = payload.get("result", {}).get("timeline", {})
        for ins in timeline.get("instructions", []):
            # Pinned 등 단일 entry
            single = ins.get("entry")
            if single:
                yield from self._extract_from_entry(single)
            for entry in ins.get("entries", []):
                yield from self._extract_from_entry(entry)

    def _extract_from_entry(self, entry: dict):
        content = entry.get("content", {})
        typ = content.get("__typename") or content.get("entryType")
        if typ in ("TimelineTimelineItem",):
            item = content.get("itemContent", {})
            tw = item.get("tweet_results", {}).get("result")
            if tw:
                yield tw
        elif typ in ("TimelineTimelineModule",):
            for sub in content.get("items", []):
                inner = sub.get("item", {}).get("itemContent", {})
                tw = inner.get("tweet_results", {}).get("result")
                if tw:
                    yield tw

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

        # Screen name from tweet author (usually same as owner, but Modules may
        # contain replies from other users — drop those).
        author = (
            tw.get("core", {}).get("user_results", {}).get("result", {}).get("core", {})
        )
        screen_name = author.get("screen_name") or owner_username
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

        rest_id = await self._resolve_user_id(username)
        if not rest_id:
            return []

        try:
            resp = await self.client.get(
                USER_REPLIES_URL, params={"user": rest_id, "count": 40}
            )
            resp.raise_for_status()
            payload = resp.json()

            tweets: list[TweetData] = []
            for tw_node in self._iter_tweet_entries(payload):
                parsed = self._parse_tweet(tw_node, owner_username=username)
                if parsed is None:
                    continue
                if parsed.created_at < cutoff:
                    continue
                tweets.append(parsed)

            logger.info(f"@{username}: {len(tweets)}개 트윗 수집 완료 (rest_id={rest_id})")
            return tweets

        except Exception as e:
            logger.error(f"@{username} 트윗 수집 실패: {e}")
            return []

    async def collect_all(self) -> dict[str, list[TweetData]]:
        """모든 대상 계정의 트윗 수집"""
        if not config.RAPIDAPI_KEY:
            logger.warning("RAPIDAPI_KEY가 설정되지 않았습니다.")
            return {}

        results: dict[str, list[TweetData]] = {}
        for account in config.TWITTER_ACCOUNTS:
            tweets = await self.collect_recent_tweets(account)
            results[account] = tweets
            await asyncio.sleep(1)  # Rate limit 방지
        return results

    async def close(self):
        await self.client.aclose()
