#!/usr/bin/env python3
"""_send_daily_post 재시도/폴백 회귀 테스트 (pytest 불필요, 단독 실행).

실행:  venv/bin/python test_send_retry.py

검증 대상 (2026-07-08 이미지 누락 사고 회귀):
  1) 이미지 전송이 일시적 네트워크 오류(NetworkError=httpx.ConnectError) 후 재시도해서
     '이미지+캡션'이 한 덩어리로 나간다. (예전엔 1회 실패 즉시 텍스트만 발송 → 그날 이미지 누락)
  2) 재시도까지 다 실패하면 최후 폴백으로 텍스트가 발송된다(사용자 선택).
  3) BadRequest(내용 오류)는 재시도하지 않고 곧장 폴백.
  4) 이미지가 없으면(None) 텍스트만 발송.
  5) 정상: 첫 시도 성공 시 photo 1회, message 0회.
"""
import asyncio
import logging
logging.basicConfig = lambda *a, **k: None  # bot import 시 bot.log FileHandler 부착 방지(운영 로그 오염 방지)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from unittest.mock import AsyncMock, patch
from telegram.error import NetworkError, BadRequest

import bot as botmod

CHANNEL = "@test_channel"
MSG = "일일 리포트 본문 <b>내용</b> + 트윗요약"
IMG = b"\x89PNG_fake_image_bytes"

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def make_bot():
    b = AsyncMock()
    b.send_photo = AsyncMock()
    b.send_message = AsyncMock()
    return b


async def _run(coro):
    # backoff sleep을 no-op으로 만들어 테스트를 즉시 끝낸다.
    with patch.object(botmod.asyncio, "sleep", new=AsyncMock()):
        return await coro


async def main():
    # 1) 일시적 오류 → 재시도 후 이미지+캡션 전송 (핵심 회귀)
    b = make_bot()
    b.send_photo.side_effect = [NetworkError("httpx.ConnectError: "), None]  # 1회 실패 후 성공
    await _run(botmod._send_daily_post(b, CHANNEL, MSG, IMG))
    check("일시적 오류 후 재시도로 이미지 전송 성공 (photo 2회)", b.send_photo.await_count == 2)
    check("재시도 성공 시 텍스트 폴백 안 함 (message 0회)", b.send_message.await_count == 0)
    _, kw = b.send_photo.await_args
    check("이미지+캡션 번들 전송 (caption=본문, photo 존재)",
          kw.get("caption") == MSG and kw.get("photo") is not None)

    # 2) 재시도 모두 실패 → 최후 텍스트 폴백
    b = make_bot()
    b.send_photo.side_effect = NetworkError("httpx.ConnectError: ")  # 항상 실패
    await _run(botmod._send_daily_post(b, CHANNEL, MSG, IMG))
    check(f"네트워크 계속 실패 시 photo를 {botmod.IMAGE_MAX_ATTEMPTS}회 시도",
          b.send_photo.await_count == botmod.IMAGE_MAX_ATTEMPTS)
    check("모두 실패하면 최후 텍스트 폴백 발송 (message 1회)", b.send_message.await_count == 1)
    _, kw = b.send_message.await_args
    check("폴백 텍스트가 본문", kw.get("text") == MSG)

    # 3) BadRequest → 재시도 없이 폴백
    b = make_bot()
    b.send_photo.side_effect = BadRequest("Can't parse entities")
    await _run(botmod._send_daily_post(b, CHANNEL, MSG, IMG))
    check("BadRequest는 재시도 안 함 (photo 1회)", b.send_photo.await_count == 1)
    check("BadRequest 후 텍스트 폴백 (message 1회)", b.send_message.await_count == 1)

    # 4) 이미지 None → 텍스트만
    b = make_bot()
    await _run(botmod._send_daily_post(b, CHANNEL, MSG, None))
    check("이미지 없으면 photo 시도 안 함 (photo 0회)", b.send_photo.await_count == 0)
    check("이미지 없으면 텍스트 발송 (message 1회)", b.send_message.await_count == 1)

    # 5) 정상 첫 시도 성공
    b = make_bot()
    await _run(botmod._send_daily_post(b, CHANNEL, MSG, IMG))
    check("정상: photo 1회", b.send_photo.await_count == 1)
    check("정상: 텍스트 폴백 없음 (message 0회)", b.send_message.await_count == 0)


asyncio.run(main())

_failed = [n for n, ok in _results if not ok]
print()
print(f"{len(_results) - len(_failed)}/{len(_results)} passed")
if _failed:
    print("FAILED:", _failed)
    sys.exit(1)
print("ALL PASS")
