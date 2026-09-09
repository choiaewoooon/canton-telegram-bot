#!/bin/bash
# ensure-playwright.sh — 일일 리포트 발송 전 Playwright 브라우저 가용성 보장
#
# 배경(2026-09-08 사고):
#   Playwright 브라우저를 공용 캐시(~/Library/Caches/ms-playwright)에 두면, 같은 맥의 다른
#   프로젝트가 더 최신 Playwright로 `playwright install`을 돌릴 때 자기가 참조하지 않는
#   구버전 빌드를 청소해버린다. 실제로 gstack(1.62.1)이 chromium 1234를 깔면서 여기서 쓰는
#   1208을 지웠고, 이틀간 이미지 카드 없이 텍스트만 발송됐다.
#   1차 방어는 PLAYWRIGHT_BROWSERS_PATH 격리(config.py + plist), 이 스크립트는 2차 안전망이다.
#
# 하는 일:
#   1. 각 venv에서 실제로 헤드리스 브라우저를 띄워본다 (존재 확인이 아니라 진짜 실행 검증)
#   2. 실패하면 `playwright install chromium`으로 자동 복구하고 다시 검증한다
#   3. 결과를 로그에 남긴다
#
# 빌드 번호를 하드코딩하지 않으므로, 나중에 pip으로 playwright를 올려 요구 빌드가 바뀌어도
# 그대로 동작한다(다음 09:45에 새 빌드를 자동으로 받아둔다).
#
# 실행: 매일 09:45 KST — LaunchAgent com.cobling.playwright-ensure
#       수동: bash scripts/ensure-playwright.sh

set -uo pipefail

LOG="/Users/choejaewon/project/Ozzycanton/canton-telegram-bot/logs/ensure-playwright.log"
mkdir -p "$(dirname "$LOG")"

# 봇과 허브가 같은 격리 경로·같은 빌드를 공유하므로 한쪽 설치가 양쪽을 커버하지만,
# 버전이 갈릴 때를 대비해 둘 다 검증한다.
PROJECTS=(
  "/Users/choejaewon/project/Ozzycanton/canton-telegram-bot"
  "/Users/choejaewon/project/Ozzycanton/canton-hub"
)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# 헤드리스 크로미움을 실제로 띄워보는 검증 (성공 0 / 실패 1)
launch_ok() {
  "$1/venv/bin/python" - <<'PY' >/dev/null 2>&1
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await browser.close()
asyncio.run(main())
PY
}

overall=0
for proj in "${PROJECTS[@]}"; do
  name="$(basename "$proj")"
  py="$proj/venv/bin/python"

  if [[ ! -x "$py" ]]; then
    log "SKIP $name — venv 없음 ($py)"
    continue
  fi

  cd "$proj" || { log "SKIP $name — cd 실패"; continue; }

  # config.py가 정한 격리 경로를 그대로 사용한다 (경로 정의는 config.py가 단일 진실원)
  browsers_path="$("$py" -c 'import config, os; print(os.environ["PLAYWRIGHT_BROWSERS_PATH"])' 2>/dev/null)"
  if [[ -z "$browsers_path" ]]; then
    log "WARN $name — PLAYWRIGHT_BROWSERS_PATH를 config에서 읽지 못함, 기본 경로로 진행"
  else
    export PLAYWRIGHT_BROWSERS_PATH="$browsers_path"
  fi

  if launch_ok "$proj"; then
    log "OK $name — 브라우저 정상 (${PLAYWRIGHT_BROWSERS_PATH:-default})"
    continue
  fi

  log "REPAIR $name — 브라우저 실행 실패, 재설치 시작 (${PLAYWRIGHT_BROWSERS_PATH:-default})"
  if "$proj/venv/bin/playwright" install chromium >>"$LOG" 2>&1; then
    if launch_ok "$proj"; then
      log "REPAIRED $name — 재설치 후 정상"
    else
      log "FAIL $name — 재설치했으나 여전히 실행 실패 (수동 확인 필요)"
      overall=1
    fi
  else
    log "FAIL $name — playwright install 실패 (네트워크/권한 확인 필요)"
    overall=1
  fi
done

exit $overall
