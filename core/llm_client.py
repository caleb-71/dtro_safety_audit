# core/llm_client.py
# 통합 LLM 클라이언트 (신규, 2026-07)
#
# [역할]
# settings.OLLAMA_MODE 값에 따라 LLM 호출을 자동 라우팅합니다.
#   "local"   → 내 PC의 Ollama (기존 방식 그대로)
#   "network" → 사내망 AI 서버 (Spring 게이트웨이, SSE 스트리밍)
#
# [설계 원칙]
# 1. ollama.chat() 과 동일한 입력/출력 형태 유지
#    → 기존 호출부는 `ollama.chat(` 을 `llm_chat(` 으로 바꾸기만 하면 됨
#    → 반환값도 동일하게 response["message"]["content"] 로 접근
# 2. 오류는 예외로 올려보냄 (기존 호출부의 try/except 가 그대로 동작)
# 3. 사내망 서버는 스트리밍 전용 백엔드이므로 항상 stream=true 로 호출해
#    SSE 조각을 모아 완성된 텍스트로 반환 (비스트리밍 응답 포맷 불확실성 회피)
#
# [사내망 API 규격] (ai_agent_llm_api.py 분석 결과)
#   POST {NETWORK_LLM_URL}/llm/model
#     - Form 데이터(@RequestParam): model, prompt, stream, num_ctx, session
#     - 응답: SSE 스트림, 각 줄 "data: {json}" 형태이며 content 키에 텍스트 조각
#     - 종료 신호: "data: [DONE]"
#   GET {NETWORK_LLM_URL}/llm/list
#     - 응답: 공백 구분 모델명 문자열 (예: "llama3.1:8b qwen2.5:7b")

import json
import logging
import uuid

from config.settings import (
    OLLAMA_MODE,
    OLLAMA_MODEL,
    NETWORK_LLM_URL,
    NETWORK_LLM_MODEL,
    NETWORK_LLM_NUM_CTX,
    NETWORK_LLM_TIMEOUT,
    NETWORK_LLM_SESSION,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 공개 API — 기존 ollama.chat 과 동일한 사용법
# ─────────────────────────────────────────
def llm_chat(model: str = None, messages: list = None, options: dict = None) -> dict:
    """
    ollama.chat() 호환 통합 호출 함수.
    :param model: 모델명 (생략 시 모드별 기본 모델)
    :param messages: [{"role": "...", "content": "..."}] 형식
    :param options: {"temperature": 0.1} 등 — network 모드에서는 서버가
                    temperature 파라미터를 받지 않으므로 무시됨 (로그만 남김)
    :return: {"message": {"content": "..."}} — ollama.chat 과 동일 구조
    """
    if OLLAMA_MODE == "network":
        return _network_chat(model, messages, options)
    return _local_chat(model, messages, options)


def llm_status() -> dict:
    """
    현재 LLM 연결 상태 확인 (UI 표시·사전 점검용).
    :return: {"mode": "...", "model": "...", "ok": bool, "detail": "..."}
    """
    if OLLAMA_MODE == "network":
        try:
            import httpx
            resp = httpx.get(f"{NETWORK_LLM_URL}/llm/list", timeout=5.0)
            resp.raise_for_status()
            models = resp.text.strip().split()
            return {
                "mode": "network", "model": NETWORK_LLM_MODEL, "ok": True,
                "detail": f"사내망 서버 연결됨 — 사용 가능 모델: {', '.join(models) if models else '(없음)'}",
            }
        except Exception as e:
            return {
                "mode": "network", "model": NETWORK_LLM_MODEL, "ok": False,
                "detail": f"사내망 AI 서버({NETWORK_LLM_URL}) 연결 실패: {e}",
            }
    else:
        try:
            import ollama
            ollama.list()
            return {
                "mode": "local", "model": OLLAMA_MODEL, "ok": True,
                "detail": "로컬 Ollama 연결됨",
            }
        except Exception as e:
            return {
                "mode": "local", "model": OLLAMA_MODEL, "ok": False,
                "detail": f"로컬 Ollama 연결 실패: {e}",
            }


# ─────────────────────────────────────────
# local 모드 — 기존 방식 그대로
# ─────────────────────────────────────────
def _local_chat(model, messages, options) -> dict:
    import ollama
    return ollama.chat(
        model=model or OLLAMA_MODEL,
        messages=messages or [],
        options=options or {},
    )


# ─────────────────────────────────────────
# network 모드 — 사내망 SSE API
# ─────────────────────────────────────────
def _network_chat(model, messages, options) -> dict:
    import httpx

    if options:
        # 사내망 게이트웨이는 temperature 등 옵션 파라미터를 지원하지 않음
        logger.debug(f"network 모드에서 지원되지 않는 옵션 무시: {options}")

    # 주의: 호출부가 넘기는 model 은 로컬용 상수(OLLAMA_MODEL)이므로
    # network 모드에서는 항상 서버 설정(NETWORK_LLM_MODEL)을 사용한다.
    # ── 세션 ID 를 요청마다 고유하게 생성 (반복답변 버그 수정, 2026-07) ──
    # [문제] 고정 세션("dtro_audit")을 쓰면 사내망 서버가 세션별로
    #   자체 대화기록을 계속 누적함 → 클라이언트가 보내는 이력과 이중으로
    #   쌓여서, 새 질문에도 과거 답변(MSDS 등)을 그대로 복사해 응답하는
    #   심각한 반복답변 현상이 발생했음
    # [해결] 대화 맥락은 page_chat.py 가 직접 관리하므로
    #   서버 세션은 매 요청마다 새로 만들어 서버측 기억을 차단함
    unique_session = f"{NETWORK_LLM_SESSION}_{uuid.uuid4().hex[:8]}"

    payload = {
        "model":   NETWORK_LLM_MODEL,
        "prompt":  _messages_to_prompt(messages or []),
        "stream":  "true",                    # 서버 백엔드가 스트리밍 전용
        "num_ctx": str(NETWORK_LLM_NUM_CTX),  # 문자열 전송이 안전 (@RequestParam)
        "session": unique_session,
    }

    parts: list[str] = []
    timeout = httpx.Timeout(connect=10.0, read=NETWORK_LLM_TIMEOUT,
                            write=30.0, pool=10.0)

    with httpx.Client(timeout=timeout) as client:
        # 중요: 서버가 @RequestParam(Form) 방식이므로 json= 이 아닌 data= 로 전송
        with client.stream("POST", f"{NETWORK_LLM_URL}/llm/model",
                           data=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                content = _parse_sse_line(line)
                if content:
                    parts.append(content)

    text = "".join(parts).strip()
    if not text:
        raise RuntimeError("사내망 AI 서버가 빈 응답을 반환했습니다.")

    # ollama.chat 과 동일한 구조로 반환 → 기존 호출부 수정 최소화
    return {"message": {"content": text}}


def _messages_to_prompt(messages: list) -> str:
    """
    ollama 메시지 배열을 사내망 API의 단일 prompt 문자열로 변환.
    system 메시지는 지시문으로 앞에 배치하고, 대화 이력은 역할 표기로 이어붙임.
    """
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    dialog = [m for m in messages if m.get("role") != "system"]

    lines = []
    if system_parts:
        lines.append("[지시문]")
        lines.extend(system_parts)
        lines.append("")

    if len(dialog) == 1:
        # 단일 질문이면 역할 표기 없이 그대로 (분류·법령 프롬프트 등 대부분의 경우)
        lines.append(dialog[0]["content"])
    else:
        # 이전 대화가 있는 경우 — 모델이 과거 답변을 그대로 복사하지 않도록
        # 명시적으로 지시 (8b급 소형 모델은 이 지시가 없으면
        # 이력 마지막 답변을 반복하는 경향이 강함)
        lines.append("[이전 대화 — 맥락 참고용이며, 아래 마지막 질문에만 새로 답변할 것]")
        for m in dialog[:-1]:
            role = "사용자" if m.get("role") == "user" else "AI"
            lines.append(f"{role}: {m['content']}")
        lines.append("")
        lines.append("[마지막 질문 — 이 질문에만 답변하세요. 이전 답변을 복사하지 마세요]")
        lines.append(f"사용자: {dialog[-1]['content']}")
        lines.append("AI:")

    return "\n".join(lines)


def _parse_sse_line(line: str) -> str:
    """SSE 한 줄에서 텍스트 조각만 추출. (data: {json} / data: [DONE])"""
    if not line:
        return ""
    line = line.strip()
    if line.startswith("data: "):
        raw = line[6:]
    elif line.startswith("data:"):
        raw = line[5:]
    else:
        raw = line

    if not raw or raw == "[DONE]":
        return ""

    try:
        return json.loads(raw).get("content", "")
    except json.JSONDecodeError:
        # JSON 이 아니면 원문 그대로 (서버가 순수 텍스트를 보내는 경우 대비)
        return raw