# DATA_GUIDE.md — canton-telegram-bot

> **Update Triggers**: WHEN a collector is added/removed, a dataclass field changes, an API endpoint or fallback chain changes, or rate-limit behavior is observed → UPDATE this document in the same commit.

---

## 1. Storage Overview

**This bot is a stateless one-shot pipeline.** It has no database, no cache, no persistent key-value store, and no message queue.

| Concern | Status | Notes |
|---|---|---|
| Database | NONE | No Postgres, SQLite, Redis, etc. |
| Cache | NONE | Every run refetches from source |
| Session state | NONE | Each `bot.py --now` run is fully independent |
| Logs | `bot.log` + `launchd_stdout.log` | Only forensic trail on disk |
| "Previous day" data | Telegram channel history | Operators scroll the channel manually |

**Lifecycle**: launchd fires at 09:00 KST → `bot.py --now` starts → collects fresh → posts to Telegram → process exits. No daemon, no server, no retained memory.

**Implication**: WHEN you need to compare today vs yesterday → you cannot. There is nowhere to read yesterday's data from. IF cross-day diffs become a product requirement → add a tiny SQLite file or read the Telegram channel message history via Bot API.

---

## 2. Data Sources

| Source | Type | Frequency | Collector | Output Dataclass | Fallback Chain |
|---|---|---|---|---|---|
| CoinGecko API v3 | REST (JSON) | 1x/day at fire time | `collectors/price_collector.py` | `PriceData` | `/coins/markets` → `/simple/price` |
| CantonScan | REST + HTML + Playwright | 1x/day at fire time | `collectors/cantonscan_collector.py` | `CantonScanData` | `/api/*` → HTML parse (`/stats`) → Playwright render |
| RapidAPI Twitter API45 | REST (JSON) | 1x/day at fire time | `collectors/twitter_collector.py` | `dict[username, list[TweetData]]` | `user_tweets` endpoint → `search` endpoint |

**Independence**: All three sources are independent of `canton-hub` (the web backend). This bot does NOT read from canton-hub's database, API, or cache. It goes directly to upstream providers.

---

## 3. Data Models

All models are Python `@dataclass` definitions. Every model carries a `fetched: bool` flag so downstream code can detect partial failure without try/except.

### 3.1 `PriceData`

| Field | Type | Source | Notes |
|---|---|---|---|
| `current_price_usd` | float | CoinGecko | USD spot price |
| `price_change_24h` | float | CoinGecko | Absolute USD delta |
| `price_change_percentage_24h` | float | CoinGecko | Percent delta |
| `high_24h` | float | CoinGecko | 24h high USD |
| `low_24h` | float | CoinGecko | 24h low USD |
| `market_cap` | float | CoinGecko | USD market cap |
| `total_volume_24h` | float | CoinGecko | USD traded volume |
| `circulating_supply` | float | CoinGecko | Token count |
| `fetched` | bool | collector | `False` on any failure |

### 3.2 `CantonScanData`

| Field | Type | Source | Notes |
|---|---|---|---|
| `daily_burn` | float | CantonScan `/stats` | Tokens burned in last 24h |
| `daily_mint` | float | CantonScan `/stats` | Tokens minted in last 24h |
| `burn_mint_ratio` | float | derived | `daily_burn / daily_mint` |
| `total_burned` | float | CantonScan | Cumulative burned |
| `total_supply` | float | CantonScan | Current total supply |
| `daily_transactions` | int | CantonScan | 24h tx count |
| `daily_active_addresses` | int | CantonScan | 24h unique addresses |
| `app_rewards` | float | CantonScan | 24h app rewards minted |
| `validator_rewards` | float | CantonScan | 24h validator rewards minted |
| `sv_rewards` | float | CantonScan | 24h super-validator rewards |
| `burned_from_fees` | float | CantonScan | 24h burn from tx fees |
| `burned_from_traffic` | float | CantonScan | 24h burn from traffic |
| `avg_amulet_price` | float | CantonScan | 24h average Amulet price |
| `cumulative_mint` | float | CantonScan | All-time mint |
| `cumulative_burn` | float | CantonScan | All-time burn |
| `raw_data` | dict | CantonScan | Full raw payload for debugging |
| `fetched` | bool | collector | `False` on any failure |

### 3.3 `TweetData`

| Field | Type | Source | Notes |
|---|---|---|---|
| `username` | str | Twitter API45 | Without `@` |
| `text` | str | Twitter API45 | Full tweet body |
| `created_at` | datetime | Twitter API45 | UTC |
| `url` | str | Twitter API45 | Canonical tweet URL |
| `likes` | int | Twitter API45 | Like count at fetch time |
| `retweets` | int | Twitter API45 | Retweet count |
| `replies` | int | Twitter API45 | Reply count |
| `views` | int | Twitter API45 | Impression count |
| `media_urls` | list[str] | Twitter API45 | Image/video URLs |

---

## 4. ETL Flow

```
09:00 KST (launchd fires)
  |
  v
bot.py --now
  |
  v
asyncio.gather in parallel:
  +-- TwitterCollector.collect_all()   -> dict[username, list[TweetData]]
  +-- CantonScanCollector.collect()    -> CantonScanData
  +-- PriceCollector.collect()         -> PriceData
  |
  v
summarize_tweets(tweets)               -> tweet_summary: str
  |
  v
build_daily_report(price, canton, tweet_summary)
                                       -> HTML message
  |
  v
generate_chart_base64(price, canton)   -> chart PNG (base64)
  |
  v
generate_daily_card(...)               -> image PNG (bytes)
  |
  v
bot.send_photo(caption=message) OR bot.send_message(text=message)
  |
  v
launchd_stdout.log written
  |
  v
Process exits (one-shot)
```

**Key property**: the three collectors run in parallel via `asyncio.gather`. WHEN one collector fails → the other two still complete and the report is still sent (with the failed section replaced by a warning placeholder).

---

## 5. Fallback Chains

### 5.1 PriceCollector

```
Step 1: GET https://api.coingecko.com/api/v3/coins/markets?ids=canton-network
        -> if 200 and payload non-empty: populate PriceData, return
Step 2: GET https://api.coingecko.com/api/v3/simple/price?ids=canton-network&vs_currencies=usd
        -> if 200: populate PriceData with current_price_usd only, fill rest with 0
Step 3: return PriceData(fetched=False)
```

### 5.2 CantonScanCollector

```
Step 1: GET https://cantonscan.com/api/*  (JSON endpoints)
        -> if 200 and parseable: populate CantonScanData, return
Step 2: GET https://cantonscan.com/stats  (HTML)
        -> parse with BeautifulSoup, extract visible numbers, return
Step 3: Playwright headless render of https://cantonscan.com/stats
        -> wait for JS hydration, scrape DOM, return
Step 4: return CantonScanData(fetched=False)
```

### 5.3 TwitterCollector

```
For each username in TWITTER_ACCOUNTS:
  Step 1: GET /user_tweets?username={u}&limit={MAX_TWEETS_PER_ACCOUNT}
          -> filter to last TWEET_HOURS_LOOKBACK hours, return list[TweetData]
  Step 2: GET /search?query=from:{u}&limit={MAX_TWEETS_PER_ACCOUNT}
          -> same filter, return list[TweetData]
  Step 3: return [] for this username
```

**Config** (in `config.py`):

| Constant | Value |
|---|---|
| `TWITTER_ACCOUNTS` | `["CantonNetwork", "CantonFdn"]` |
| `MAX_TWEETS_PER_ACCOUNT` | `10` |
| `TWEET_HOURS_LOOKBACK` | `24` |

---

## 6. Rate Limit Management

| Source | Known Limit | Bot Consumption | Risk |
|---|---|---|---|
| CoinGecko (free tier) | ~10-30 req/min | 1-2 req per daily run | Negligible |
| RapidAPI Twitter API45 | Per subscription plan | 2-4 req per daily run (1 per account, +1 per fallback) | Check plan quota monthly |
| CantonScan | Unofficial, no documented limit | 1-3 req per daily run (+ Playwright worst case) | Low; be polite |

### Independence from canton-hub

**As of 2026-04-15**, canton-hub (web backend) runs on Fly.io Tokyo with a different egress IP than this bot, which runs on a home Mac. There is **no shared IP rate-limit surface** between the two systems.

**Historical note**: BEFORE the 2026-04-15 split, both canton-hub and this bot ran from the same home IP and collided at 09:00 KST on 2026-04-XX, causing the upstream incident. The split resolved this. WHEN designing future collectors → keep this bot's upstream calls independent from canton-hub, even if the data overlaps.

---

## 7. Data Quality Rules

All collectors MUST obey these rules. The entire daily report depends on it.

| Rule | Rationale | Enforcement |
|---|---|---|
| MUST catch own exceptions | One bad source must not break the report | `try/except Exception` at `collect()` top level |
| MUST return empty dataclass with `fetched=False` on failure | Downstream code branches on `fetched` flag, never on exceptions | Every `except` returns `PriceData(fetched=False)` / `CantonScanData(fetched=False)` / `{}` |
| MUST NEVER raise out of `collect()` | `asyncio.gather` would propagate and kill the run | Verified by reading each collector's top-level `except` |
| MUST use `httpx.AsyncClient(timeout=15)` | Home Mac IP means slow networks must fail fast | `timeout=15` in every collector |
| MUST close httpx clients | Prevents socket exhaustion on launchd retries | `bot.py` closes `cantonscan` and `price` clients in `finally` |
| MUST log the failure reason | `bot.log` is the only forensic trail | `logger.warning` / `logger.error` before returning empty |

### Validation checklist (manual)

```bash
# 1. Dry-run a single collector
python -c "import asyncio; from collectors.price_collector import PriceCollector; \
           print(asyncio.run(PriceCollector().collect()))"

# 2. Confirm fetched flag on failure by blocking network
# (e.g. disable wifi, run the above) -> should print fetched=False, not raise

# 3. Full pipeline dry-run
python bot.py --now

# 4. Inspect log
tail -n 50 bot.log
```

---

## 8. Change Log

| 날짜 | 변경 | 이유 |
|---|---|---|
| 2026-04-14 | 초기 생성 | docs-init으로 자동 생성 |
