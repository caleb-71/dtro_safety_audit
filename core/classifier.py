# core/classifier.py
# AI 분류 엔진 (llama3.1:8b + RAG)
# 지적사항을 3개 파트로 분류하고 리스크 등급 판정

import re
import logging
import ollama
from config.settings import OLLAMA_MODEL, AUDIT_PARTS, OLLAMA_TIMEOUT
from config.keywords import STRONG_INDICATORS, PART_KEYWORDS, AUDIT_TYPE_WEIGHT

logger = logging.getLogger(__name__)


def classify_item(
    title: str,
    problem: str,
    audit_type: str = "",
    similar_cases: list[dict] = None
) -> dict:
    """
    단일 지적사항 AI 분류
    :param title: 제목
    :param problem: 현황및문제점
    :param audit_type: 심사구분
    :param similar_cases: RAG 유사사례
    :return: 분류 결과 dict
    """
    combined_text = f"{title} {problem}".strip()

    # ─────────────────────────────────────
    # 1단계: STRONG_INDICATORS 빠른 판별
    # ─────────────────────────────────────
    quick_result = _quick_classify(combined_text)
    if quick_result:
        risk = _determine_risk(combined_text, audit_type)
        return {
            "part":       quick_result,
            "risk":       risk,
            "reason":     f"키워드 확정 분류: {quick_result}",
            "confidence": "high",
            "method":     "keyword"
        }

    # ─────────────────────────────────────
    # 2단계: AI (llama3.1) 분류
    # ─────────────────────────────────────
    ai_result = _ai_classify(
        title, problem, audit_type, similar_cases
    )
    return ai_result


def _quick_classify(text: str) -> str | None:
    """STRONG_INDICATORS 기반 빠른 분류"""
    for part, indicators in STRONG_INDICATORS.items():
        for keyword in indicators:
            if keyword in text:
                logger.debug(f"키워드 매칭: '{keyword}' → {part}")
                return part
    return None


def _ai_classify(
    title: str,
    problem: str,
    audit_type: str,
    similar_cases: list[dict] = None
) -> dict:
    """llama3.1 AI 분류"""
    try:
        # 유사사례 컨텍스트 구성
        context = ""
        if similar_cases:
            context = "\n\n[참고: 유사 과거 사례]\n"
            for i, case in enumerate(similar_cases[:3], 1):
                meta = case.get("metadata", {})
                context += (
                    f"{i}. {meta.get('title','')}"
                    f" → {meta.get('ai_part','미분류')}\n"
                )

        prompt = f"""당신은 철도안전관리체계 전문가입니다.
아래 지적사항을 반드시 3개 파트 중 하나로만 분류하세요.

[분류 기준]
- 안전계획: 철도사고, 철도준사고, 운행장애, 열차운행, 기관사, 관제 관련
- 안전보건: 산업안전보건법, TBM, MSDS, 근로자 보건, 작업환경, 교육 관련
- 재난안전: 자연재난(호우/태풍/지진/대설/폭염/한파 등), 재난대응, 비상훈련 관련
{context}

[분류할 지적사항]
제목: {title}
내용: {problem}
심사구분: {audit_type}

[응답 형식 - 반드시 아래 형식으로만 답하세요]
파트: (안전계획/안전보건/재난안전 중 하나)
이유: (한 문장)
리스크: (상/중/하 중 하나)"""

        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )

        result_text = response["message"]["content"]
        return _parse_ai_response(result_text, audit_type)

    except Exception as e:
        logger.error(f"AI 분류 오류: {e}")
        return _fallback_classify(title, audit_type)


def _parse_ai_response(text: str, audit_type: str) -> dict:
    """AI 응답 파싱"""
    part   = "미분류"
    reason = ""
    risk   = "중"

    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("파트:"):
            raw = line.replace("파트:", "").strip()
            for p in AUDIT_PARTS:
                if p in raw:
                    part = p
                    break
        elif line.startswith("이유:"):
            reason = line.replace("이유:", "").strip()
        elif line.startswith("리스크:"):
            raw = line.replace("리스크:", "").strip()
            if "상" in raw:
                risk = "상"
            elif "하" in raw:
                risk = "하"
            else:
                risk = "중"

    # 심사구분으로 리스크 보정
    if audit_type in AUDIT_TYPE_WEIGHT:
        type_risk = AUDIT_TYPE_WEIGHT[audit_type]
        if type_risk == "상":
            risk = "상"

    return {
        "part":       part,
        "risk":       risk,
        "reason":     reason,
        "confidence": "medium",
        "method":     "ai"
    }


def _determine_risk(text: str, audit_type: str) -> str:
    """리스크 등급 결정"""
    from config.keywords import RISK_HIGH_KEYWORDS
    for kw in RISK_HIGH_KEYWORDS:
        if kw in text:
            return "상"
    if audit_type in AUDIT_TYPE_WEIGHT:
        return AUDIT_TYPE_WEIGHT[audit_type]
    return "중"


def _fallback_classify(title: str, audit_type: str) -> dict:
    """AI 오류 시 키워드 점수 기반 폴백"""
    scores = {part: 0 for part in AUDIT_PARTS}
    for part, keywords in PART_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                scores[part] += 1

    best_part = max(scores, key=scores.get)
    if scores[best_part] == 0:
        best_part = "안전보건"

    return {
        "part":       best_part,
        "risk":       AUDIT_TYPE_WEIGHT.get(audit_type, "중"),
        "reason":     "키워드 점수 기반 분류 (AI 오류 폴백)",
        "confidence": "low",
        "method":     "fallback"
    }