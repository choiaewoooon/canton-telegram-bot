"""
트윗 요약 모듈
다중 경로 LLM 래퍼 llmq로 수집된 트윗을 한국어로 번역·요약합니다.
체인 'daily' = ChatGPT(Codex, gpt-5.6-luna) → Claude(Antigravity) → Gemini 순으로 자동 전환.

- 2026-09-23: Gemini 구독 해지로 gemq 전 모델 429 → gptq(gpt-reserve) 단일 경로로 교체.
- 2026-09-24: gpt-reserve 모델 전용 한도가 하루 만에 소진돼 또 폴백 발송.
  → 단일 경로 의존을 끊고 llmq(경로 자동 전환 + 한도 걸린 경로 쿨다운)로 교체.
  모든 경로 실패 시 Mac 알림을 띄워 조용한 실패를 막는다.
아래 'Gemini' 서술은 그 이전 연혁이다.

왜 Gemini인가 (2026-07-01 교체):
- 과거엔 `claude -p`(구독 OAuth, macOS Keychain)를 썼으나, OAuth 로그인이 만료되면
  헤드리스에서 자동 재로그인이 안 돼 요약이 통째로 실패했다. 그러면 영어 트윗 원문이
  '요약'인 척 그대로 채널에 나가는 사고가 발생(2026-07-01 캔톤 데일리).
- gemq는 무료 Gemini 구독 기반이라 인증이 안정적이고(만료·재로그인 이슈 없음),
  번역·요약은 전역 오프로드 규약상 원래 Gemini 담당이다.

실패해도(모든 재시도 소진) 영어 원문을 요약인 척 내보내지 않는다 → 한국어 안내 + 원문 링크만.
"""
import asyncio
import logging
import re

from collectors import TweetData

# 텔레그램 HTML이 허용하는 태그만. 나머지는 제거한다(내부 텍스트는 보존).
# https://core.telegram.org/bots/api#html-style
_TG_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "blockquote", "span", "tg-spoiler",
}

logger = logging.getLogger(__name__)

GEMQ_PATH = "/Users/choejaewon/.local/bin/llmq"   # 변수명은 호환 유지, 실제로는 다중 경로 래퍼
GEMQ_MODEL = "daily"    # codex(gpt-5.6-luna) → claude → gemini. gpt-6-astra는 비싸서 쓰지 않음
CALL_TIMEOUT = 420      # 초. llmq 경로별 타임아웃 합(90+120+180)보다 약간 길게
MAX_ATTEMPTS = 2        # 일시적 실패 대비 재시도 횟수

INSTRUCTION = """아래(===== 처리할 내용 =====)는 Canton Network 트위터 계정들의 최근 24시간 트윗이다.
이걸 한국어로 번역·요약해서 텔레그램 채널 공지에 들어갈 '트위터 소식 정리'를 작성해라.

톤앤매너 (코블린 @cobling 채널 스타일):
- 반말 + "~됨/~함/~인 듯/~하는 중" 체의 간결한 구어체
- 팩트 나열 위주, 과장이나 실러 톤 없이 건조하게
- 감상은 짧게 1문장 이내, 자조적 유머 OK ("제발ㅋㅋ", "ㅇㄱㅈ" 등)
- 이모지 최소한. 거의 안 씀

포맷 규칙:
- 반드시 한국어로 써라. 영어 원문을 그대로 두지 마라.
- 텔레그램 HTML 태그만 사용 (<b>, <a href="URL">텍스트</a> 만 가능. 마크다운·코드펜스 금지)
- 핵심 3-5개 항목만. 비슷한 내용은 하나로 합쳐라
- 각 항목 앞에 · 사용
- 각 항목 사이에 빈 줄 한 줄을 반드시 넣어 시각적으로 분리 (항목 구분 = \\n\\n)
- 각 항목 문장 끝에 해당 트윗 원문 링크를 넣어라. 형식: <a href="트윗URL">원문</a>
- 반응(likes/views) 높은 트윗에 가중치
- 항목별 길이는 자유롭게(빈 줄 포함 8~12줄 가능)
- 앞뒤에 제목·설명·코드펜스(```) 붙이지 말고 요약 본문 HTML만 출력해라"""


async def summarize_tweets(tweets: dict[str, list[TweetData]]) -> str:
    """수집된 트윗들을 LLM(llmq)으로 한국어 요약 + 원문 링크 포함하여 반환 (HTML)"""

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

    # 트윗 URL 매핑 (AI가 링크를 달 수 있게)
    tweet_refs = [
        f"[{i + 1}] @{tw.username}: {tw.text[:100]} → {tw.url}"
        for i, tw in enumerate(all_tweets)
    ]
    ref_text = "\n".join(tweet_refs)

    data_text = f"트윗 원문 (번호 → URL):\n{raw_text}\n\nURL 참조:\n{ref_text}"

    summary = await _run_gemq(data_text)
    if summary:
        logger.info(f"트윗 요약 완료 ({len(summary)} chars)")
        return summary

    # 모든 재시도 실패 → 영어 원문 덤프 대신 정직한 한국어 폴백(링크만)
    logger.error("트윗 요약 실패 — 한국어 폴백(원문 링크)으로 대체")
    _notify_failure()
    return _fallback_format(all_tweets)


async def _run_gemq(data_text: str) -> str:
    """gemq 서브프로세스 호출. 성공 시 정리된 HTML, 실패 시 빈 문자열."""
    process = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            process = await asyncio.create_subprocess_exec(
                GEMQ_PATH, GEMQ_MODEL, INSTRUCTION,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=data_text.encode()),
                timeout=CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"gemq 타임아웃 (시도 {attempt}/{MAX_ATTEMPTS})")
            if process is not None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            continue
        except FileNotFoundError:
            logger.error(f"gemq 실행 파일을 찾을 수 없음: {GEMQ_PATH}")
            return ""
        except Exception as e:
            logger.warning(f"gemq 호출 예외 (시도 {attempt}/{MAX_ATTEMPTS}): {e!r}")
            continue

        out = stdout.decode().strip()
        err = stderr.decode().strip()
        if process.returncode == 0 and out:
            return _clean_html(out)

        # 실패: stdout·stderr 둘 다 남긴다.
        # (claude 시절엔 stderr만 로그해서, 에러가 stdout으로 나가는 인증 실패의 원인을 놓쳤다.)
        logger.warning(
            f"gemq 실패 (시도 {attempt}/{MAX_ATTEMPTS}) "
            f"rc={process.returncode} stdout={out[-300:]!r} stderr(끝)={err[-500:]!r}"
        )

    return ""


def _notify_failure() -> None:
    """모든 LLM 경로 실패 시 Mac 알림. 알림 실패는 무시(발송 파이프라인에 영향 없음)."""
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             'display notification "모든 LLM 경로 실패 — 폴백으로 발송됨. llmq --status 확인" '
             'with title "캔톤 데일리 요약 실패" sound name "Basso"'],
            timeout=10, capture_output=True,
        )
    except Exception:
        pass


def _clean_html(text: str) -> str:
    """AI 출력에서 코드펜스와 텔레그램 비허용 태그를 제거한다.

    Gemini가 프롬프트를 어겨 `<br>`·`<p>` 등을 넣으면 텔레그램이 HTML 파싱을
    거부(400 unsupported tag)해 메시지가 통째로 미전송된다(2026-07-04 사고).
    → 발송 전에 여기서 걸러 낸다.
    """
    t = text.strip()
    # 1) 코드펜스(```html ... ```) 제거
    if t.startswith("```"):
        lines = t.split("\n")
        lines = lines[1:]  # 첫 ``` 줄 제거
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # 끝 ``` 줄 제거
        t = "\n".join(lines).strip()
    # 2) <br>, </p>, </div> 계열 → 줄바꿈
    t = re.sub(r"<\s*br\s*/?\s*>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<\s*/\s*(p|div|li|h[1-6])\s*>", "\n", t, flags=re.IGNORECASE)
    # 3) 텔레그램 비허용 태그 제거(허용 태그와 그 속성은 그대로 둠)
    def _keep_allowed(m: "re.Match") -> str:
        return m.group(0) if m.group(1).lower() in _TG_ALLOWED_TAGS else ""
    t = re.sub(r"<\s*/?\s*([a-zA-Z0-9-]+)[^>]*>", _keep_allowed, t)
    # 4) 과도한 빈 줄 정리
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _fallback_format(all_tweets: list[TweetData]) -> str:
    """AI 요약 실패 시: 영어 원문을 요약인 척 내보내지 않고, 한국어 안내 + 원문 링크만."""
    top = sorted(all_tweets, key=lambda t: (t.likes + t.views), reverse=True)[:5]
    lines = ["· 오늘 트위터 자동 요약 생성에 실패함. 원문 링크만 첨부:"]
    for tw in top:
        when = tw.created_at.strftime("%m/%d %H:%M")
        lines.append(f'· @{tw.username} ({when}) <a href="{tw.url}">원문</a>')
    return "\n\n".join(lines)
