# core/legal_engine.py
# 법령 검색 엔진
# 지적사항에 대한 법령 근거 자동 생성

import logging
from core.llm_client import llm_chat
from config.settings import OLLAMA_MODEL
from data.legal_store import search_legal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 법령 근거 생성
# ─────────────────────────────────────────
def find_legal_basis(
    title:      str,
    problem:    str = "",
    audit_type: str = "",
    top_k:      int = 3,
) -> dict:
    """
    지적사항에 대한 법령 근거 자동 검색 및 생성
    :param title:      지적사항 제목
    :param problem:    현황 및 문제점
    :param audit_type: 심사구분
    :return: 법령 근거 딕셔너리
    """
    query = f"{title} {problem}".strip()

    # 법령 검색
    legal_results = search_legal(query, top_k=top_k)

    if not legal_results:
        return {
            "found":   False,
            "basis":   "",
            "sources": [],
            "results": []
        }

    # 검색된 법령 컨텍스트 구성
    context = _build_legal_context(legal_results)

    # AI로 근거 문장 생성
    basis = _generate_basis_text(title, problem, audit_type, context)

    # 출처 정보 추출
    sources = _extract_sources(legal_results)

    return {
        "found":   True,
        "basis":   basis,
        "sources": sources,
        "results": legal_results
    }


# ─────────────────────────────────────────
# 법령 컨텍스트 구성
# ─────────────────────────────────────────
def _build_legal_context(legal_results: list[dict]) -> str:
    """검색된 법령 결과를 컨텍스트 텍스트로 변환"""
    parts = []
    for i, result in enumerate(legal_results, 1):
        meta     = result.get("metadata", {})
        text     = result.get("text", "")
        file_name = meta.get("file_stem", "")
        cat_ko   = meta.get("category_ko", "")
        sim      = result.get("similarity", 0)

        parts.append(
            f"[참고문서 {i}] {file_name} ({cat_ko}) "
            f"(관련도: {sim:.0%})\n{text[:400]}"
        )

    return "\n\n".join(parts)


# ─────────────────────────────────────────
# AI 근거 문장 생성
# ─────────────────────────────────────────
def _generate_basis_text(
    title:      str,
    problem:    str,
    audit_type: str,
    context:    str
) -> str:
    """AI를 활용하여 법령 근거 문장 생성"""
    try:
        prompt = f"""당신은 철도안전관리체계 법령 전문가입니다.
아래 지적사항에 대한 법령/규정 근거를 찾아 간결하게 설명하세요.

[지적사항]
제목: {title}
내용: {problem}
심사구분: {audit_type}

[관련 법령/규정 자료]
{context}

[작성 지침]
1. 위 자료에서 가장 관련성 높은 조항을 인용하세요
2. "○○법 제○조에 의거..." 형식으로 작성하세요
3. 없으면 "관련 법령 조항을 찾을 수 없습니다"라고 하세요
4. 3문장 이내로 간결하게 작성하세요
5. 한국어로 작성하세요

법령 근거:"""

        response = llm_chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        return response["message"]["content"].strip()

    except Exception as e:
        logger.error(f"법령 근거 생성 오류: {e}")
        return "법령 근거 생성 중 오류가 발생했습니다."


# ─────────────────────────────────────────
# 출처 정보 추출
# ─────────────────────────────────────────
def _extract_sources(legal_results: list[dict]) -> list[str]:
    """검색 결과에서 출처 파일명 추출"""
    sources = []
    seen    = set()
    for result in legal_results:
        meta  = result.get("metadata", {})
        fname = meta.get("file_name", "")
        cat   = meta.get("category_ko", "")
        if fname and fname not in seen:
            sources.append(f"{cat}: {fname}")
            seen.add(fname)
    return sources


# ─────────────────────────────────────────
# 빠른 법령 검색 (질의응답용)
# ─────────────────────────────────────────
def quick_legal_search(
    query:           str,
    top_k:           int = 5,
    filter_category: str = None,
) -> str:
    """
    자연어 질의에 대한 법령 검색 결과 텍스트 반환
    AI 질의응답 화면에서 활용
    """
    results = search_legal(
        query_text=query,
        top_k=top_k,
        filter_category=filter_category
    )

    if not results:
        return "관련 법령/규정을 찾을 수 없습니다."

    context = _build_legal_context(results)

    try:
        prompt = f"""다음 법령/규정 자료를 바탕으로
아래 질문에 정확하게 답변하세요.

[질문]
{query}

[관련 법령/규정 자료]
{context}

[답변 지침]
1. 반드시 위 자료에 있는 내용만 답변하세요
2. AI 의 일반 지식(학습 데이터)이 자료 내용과 다르더라도
   반드시 위 자료의 내용을 따르세요
3. 법령명, 조항, 문서명을 명확히 인용하세요
   예) "안전보건경영지침서 제16장 6.4에 따르면..."
4. 자료에 없는 내용은 절대 추측하지 말고
   "해당 내용을 등록된 문서에서 찾을 수 없습니다"라고 답하세요
5. 한국어로 작성하세요

답변:"""

        response = llm_chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        return response["message"]["content"].strip()

    except Exception as e:
        logger.error(f"법령 질의 오류: {e}")
        return "법령 검색 중 오류가 발생했습니다."