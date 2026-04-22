"""
$CC 코인 가격 수집 모듈
CoinGecko API를 사용하여 Canton($CC) 토큰의 가격 데이터를 수집합니다.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)


@dataclass
class PriceData:
    """$CC 가격 데이터"""
    current_price_usd: Optional[float] = None
    price_change_24h: Optional[float] = None          # 24시간 변동 (USD)
    price_change_percentage_24h: Optional[float] = None  # 24시간 변동률 (%)
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    market_cap: Optional[float] = None
    total_volume_24h: Optional[float] = None
    circulating_supply: Optional[float] = None
    fetched: bool = False


class PriceCollector:
    """CoinGecko 가격 수집기"""

    def __init__(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": "CantonTelegramBot/1.0",
        }
        if config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

        self.client = httpx.AsyncClient(
            timeout=15,
            headers=headers,
        )

    async def collect(self) -> PriceData:
        """$CC 가격 데이터 수집"""
        data = PriceData()

        # 방법 1: canton-hub 로컬 API (같은 Mac의 백엔드가 이미 캐시 보유)
        try:
            data = await self._fetch_from_canton_hub()
            if data.fetched:
                return data
        except Exception as e:
            logger.warning(f"canton-hub API 실패, CoinGecko 직통으로 폴백: {e}")

        # 방법 2: CoinGecko /coins/markets (상세 데이터)
        try:
            data = await self._fetch_markets_data()
            if data.fetched:
                return data
        except Exception as e:
            logger.warning(f"markets API 실패: {e}")

        # 방법 3: CoinGecko /simple/price (기본 데이터, 최종 폴백)
        try:
            data = await self._fetch_simple_price()
        except Exception as e:
            logger.error(f"simple price API도 실패: {e}")

        return data

    async def _fetch_from_canton_hub(self) -> PriceData:
        """canton-hub 로컬 백엔드에서 가격 캐시 조회"""
        url = f"{config.CANTON_HUB_API_URL}/api/price"
        resp = await self.client.get(url, timeout=2)
        resp.raise_for_status()
        d = resp.json()

        if not d or d.get("current_price_usd") is None:
            return PriceData()

        data = PriceData(
            current_price_usd=d.get("current_price_usd"),
            price_change_24h=d.get("price_change_24h"),
            price_change_percentage_24h=d.get("price_change_percentage_24h"),
            high_24h=d.get("high_24h"),
            low_24h=d.get("low_24h"),
            market_cap=d.get("market_cap"),
            total_volume_24h=d.get("total_volume_24h"),
            circulating_supply=d.get("circulating_supply"),
            fetched=True,
        )
        logger.info(f"$CC 가격 수집 완료 (canton-hub): ${data.current_price_usd}")
        return data

    async def _fetch_markets_data(self) -> PriceData:
        """상세 마켓 데이터 가져오기"""
        url = f"{config.COINGECKO_API_URL}/coins/markets"
        params = {
            "ids": config.COINGECKO_COIN_ID,
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 1,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        }

        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        coins = resp.json()

        if not coins:
            logger.warning(f"CoinGecko에서 '{config.COINGECKO_COIN_ID}' 토큰을 찾을 수 없습니다.")
            return PriceData()

        coin = coins[0]
        data = PriceData(
            current_price_usd=coin.get("current_price"),
            price_change_24h=coin.get("price_change_24h"),
            price_change_percentage_24h=coin.get("price_change_percentage_24h"),
            high_24h=coin.get("high_24h"),
            low_24h=coin.get("low_24h"),
            market_cap=coin.get("market_cap"),
            total_volume_24h=coin.get("total_volume"),
            circulating_supply=coin.get("circulating_supply"),
            fetched=True,
        )

        logger.info(f"$CC 가격 수집 완료: ${data.current_price_usd} ({data.price_change_percentage_24h:+.2f}%)")
        return data

    async def _fetch_simple_price(self) -> PriceData:
        """간단한 가격 데이터 (폴백)"""
        url = f"{config.COINGECKO_API_URL}/simple/price"
        params = {
            "ids": config.COINGECKO_COIN_ID,
            "vs_currencies": "usd",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        }

        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        result = resp.json()

        coin_data = result.get(config.COINGECKO_COIN_ID, {})
        if not coin_data:
            return PriceData()

        data = PriceData(
            current_price_usd=coin_data.get("usd"),
            price_change_percentage_24h=coin_data.get("usd_24h_change"),
            market_cap=coin_data.get("usd_market_cap"),
            total_volume_24h=coin_data.get("usd_24h_vol"),
            fetched=True,
        )

        logger.info(f"$CC 가격 수집 완료 (simple): ${data.current_price_usd}")
        return data

    async def close(self):
        await self.client.aclose()
