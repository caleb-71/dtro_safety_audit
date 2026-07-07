# core/classifier.py
# AI 분류 엔진 (llama3.1:8b + RAG + 법령DB 연계)
#
# 개선 내용:
# 1. 법령DB 1차 검색 → 법령명으로 파트 결정 (가장 정확)
# 2. 법령 미검색 시 기존 키워드 + AI 분류
# 3. 리스크 판정은 기존 로직 유지

import logging
from core.llm_client import llm_chat
from config.settings import OLLAMA_MODEL, AUDIT_PARTS
from config.keywords import (
    STRONG_INDICATORS,
    PART_KEYWORDS,
    AUDIT_TYPE_WEIGHT,
    RISK_UPGRADE_TO_HIGH,
    RISK_DOWNGRADE_TO_LOW,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 법령 파일명 → 파트 매핑 테이블
# 보유한 PDF 파일명 기준으로 작성
# 파일명에 아래 키워드가 포함되면 해당 파트로 확정
# ─────────────────────────────────────────
LEGAL_PART_MAP = {
    # 안전보건 관련 법령
    "산업안전보건":   "안전보건",
    "산업안전":       "안전보건",
    "중대재해":       "안전보건",
    "안전보건기준":   "안전보건",
    "물질안전보건":   "안전보건",
    "작업환경":       "안전보건",
    "보건관리":       "안전보건",

    # 안전계획 관련 법령
    "철도안전":       "안전계획",
    "철도운영":       "안전계획",
    "도시철도":       "안전계획",
    "철도사업":       "안전계획",
    "운행안전":       "안전계획",

    # 재난안전 관련 법령
    "재난":           "재난안전",
    "재난안전":       "재난안전",
    "자연재난":       "재난안전",
    "위기관리":       "재난안전",
    "비상대비":       "재난안전",
}


# ─────────────────────────────────────────
# 메인 분류 함수
# ─────────────────────────────────────────
def classify_item(
    title:         str,
    problem:       str,
    audit_type:    str        = "",
    similar_cases: list[dict] = None,
    repeat_count:  int        = 1,
) -> dict:
    """
    단일 지적사항 분류 — 3단계 판정

    1단계: 법령DB 검색 → 법령명으로 파트 확정 (신규, 가장 정확)
    2단계: STRONG_INDICATORS 키워드 매칭 (기존)
    3단계: llama3.1:8b AI 분류 — 법령 컨텍스트 포함 (기존 + 개선)
    """
    combined_text = f"{title} {problem}".strip()

    # ── 1단계: 법령DB 검색 기반 파트 결정
    legal_part, legal_context, legal_source = _classify_by_legal(combined_text)
    if legal_part:
        risk = _determine_risk(combined_text, audit_type, repeat_count)
        return {
            "part":       legal_part,
            "risk":       risk,
            "reason":     f"법령 근거 분류: {legal_source}",
            "confidence": "high",
            "method":     "legal"
        }

    # ── 2단계: STRONG_INDICATORS 키워드 매칭
    quick_part = _quick_classify(combined_text)
    if quick_part:
        risk = _determine_risk(combined_text, audit_type, repeat_count)
        return {
            "part":       quick_part,
            "risk":       risk,
            "reason":     f"키워드 확정 분류: {quick_part}",
            "confidence": "high",
            "method":     "keyword"
        }

    # ── 3단계: AI 분류 (법령 컨텍스트 포함)
    return _ai_classify(
        title, problem, audit_type,
        similar_cases, repeat_count, legal_context
    )


# ─────────────────────────────────────────
# 1단계: 법령DB 검색 기반 파트 결정 (신규)
# ─────────────────────────────────────────
def _classify_by_legal(text: str) -> tuple[str | None, str, str]:
    """
    법령DB에서 관련 법령 검색 후 파트 결정

    Returns:
        (파트명 또는 None, 법령 컨텍스트 텍스트, 법령 출처)
    """
    try:
        from data.legal_store import search_legal, get_legal_store_status

        # 법령DB 미구축 시 스킵
        status = get_legal_store_status()
        if not status.get("ready", False):
            return None, "", ""

        # 법령 검색 (유사도 높은 3건)
        legal_results = search_legal(text, top_k=3)
        if not legal_results:
            return None, "", ""

        # 컨텍스트 구성 (AI 프롬프트용)
        context_parts = []
        for r in legal_results:
            meta = r.get("metadata", {})
            sim  = r.get("similarity", 0)
            context_parts.append(
                f"[{meta.get('file_stem','')} / {meta.get('category_ko','')} / "
                f"관련도:{sim:.0%}]\n{r.get('text','')[:300]}"
            )
        legal_context = "\n\n".join(context_parts)

        # 유사도 임계값 — 0.55 이상인 결과만 파트 결정에 활용
        # (너무 낮으면 관련 없는 법령으로 오분류 위험)
        SIMILARITY_THRESHOLD = 0.55

        for result in legal_results:
            sim       = result.get("similarity", 0)
            meta      = result.get("metadata", {})
            file_stem = meta.get("file_stem", "")
            file_name = meta.get("file_name", "")

            if sim < SIMILARITY_THRESHOLD:
                continue

            # 파일명에서 파트 결정
            for keyword, part in LEGAL_PART_MAP.items():
                if keyword in file_stem or keyword in file_name:
                    source = f"{file_stem} (유사도 {sim:.0%})"
                    logger.info(f"법령 기반 분류: '{keyword}' in '{file_stem}' → {part}")
                    return part, legal_context, source

        # 임계값 통과 건이 없으면 컨텍스트만 반환 (AI 분류에 활용)
        return None, legal_context, ""

    except Exception as e:
        logger.warning(f"법령DB 검색 스킵 (오류): {e}")
        return None, "", ""


# ─────────────────────────────────────────
# 2단계: STRONG_INDICATORS 키워드 매칭
# ─────────────────────────────────────────
def _quick_classify(text: str) -> str | None:
    """STRONG_INDICATORS 기반 빠른 파트 분류"""
    for part, indicators in STRONG_INDICATORS.items():
        for keyword in indicators:
            if keyword in text:
                logger.debug(f"키워드 매칭: '{keyword}' → {part}")
                return part
    return None


# ─────────────────────────────────────────
# 3단계: AI 분류 (법령 컨텍스트 포함)
# ─────────────────────────────────────────
def _ai_classify(
    title:         str,
    problem:       str,
    audit_type:    str,
    similar_cases: list[dict] = None,
    repeat_count:  int        = 1,
    legal_context: str        = "",
) -> dict:
    """llama3.1 AI 분류 — 법령 컨텍스트 포함"""
    try:
        # 유사사례 컨텍스트
        similar_context = ""
        if similar_cases:
            similar_context = "\n\n[참고: 유사 과거 심사 사례]\n"
            for i, case in enumerate(similar_cases[:3], 1):
                meta = case.get("metadata", {})
                similar_context += (
                    f"{i}. {meta.get('title', '')}"
                    f" → {meta.get('ai_part', '미분류')}\n"
                )

        # 법령 컨텍스트 섹션
        legal_section = ""
        if legal_context:
            legal_section = f"""
[관련 법령/규정 검색 결과 - 파트 판단에 활용하세요]
{legal_context}

※ 검색된 법령이 산업안전보건 관련이면 → 안전보건
※ 검색된 법령이 철도안전 관련이면 → 안전계획
※ 검색된 법령이 재난안전 관련이면 → 재난안전
"""

        prompt = f"""당신은 철도안전관리체계 및 산업안전 법령 전문가입니다.
아래 지적사항을 반드시 3개 파트 중 하나로만 분류하세요.

[분류 기준]
- 안전계획: 철도사고, 철도준사고, 운행장애, 열차운행, 기관사, 관제, 철도안전법 관련
- 안전보건: 산업안전보건법, TBM, MSDS, 근로자 보건, 작업환경, 보호구, 리프트, 핸드리프트 관련
- 재난안전: 자연재난(호우/태풍/지진/대설/폭염/한파), 재난대응, 비상훈련, 재난매뉴얼 관련
{legal_section}{similar_context}

[분류할 지적사항]
제목: {title}
내용: {problem}
심사구분: {audit_type}

[응답 형식 - 반드시 아래 형식으로만 답하세요]
파트: (안전계획/안전보건/재난안전 중 하나)
이유: (법령 근거를 포함한 한 문장)"""

        response = llm_chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )

        result_text = response["message"]["content"]
        return _parse_ai_response(
            result_text, audit_type,
            f"{title} {problem}", repeat_count
        )

    except Exception as e:
        logger.error(f"AI 분류 오류: {e}")
        return _fallback_classify(title, audit_type, repeat_count)


# ─────────────────────────────────────────
# AI 응답 파싱
# ─────────────────────────────────────────
def _parse_ai_response(
    text:          str,
    audit_type:    str,
    combined_text: str = "",
    repeat_count:  int = 1,
) -> dict:
    """AI 응답 파싱 — 리스크는 _determine_risk 로 결정"""
    part   = "미분류"
    reason = ""

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

    risk = _determine_risk(combined_text, audit_type, repeat_count)

    return {
        "part":       part,
        "risk":       risk,
        "reason":     reason,
        "confidence": "medium",
        "method":     "ai"
    }


# ─────────────────────────────────────────
# 리스크 등급 결정 (기존 유지)
# ─────────────────────────────────────────
def _determine_risk(
    text:         str,
    audit_type:   str,
    repeat_count: int = 1,
) -> str:
    """
    리스크 등급 결정 — 실무 기반 3단계
    Step 1: 완료/경미 → 하
    Step 2: 법령위반/인명사고 → 상
    Step 3: 시정명령 → 상
    Step 4: 반복 3회↑ → 상
    Step 5: 심사구분 기본값
    Step 6: 기본값 중
    """
    for kw in RISK_DOWNGRADE_TO_LOW:
        if kw in text:
            return "하"

    for kw in RISK_UPGRADE_TO_HIGH:
        if kw in text:
            return "상"

    if audit_type == "시정명령":
        return "상"

    from config.keywords import RISK_REPEAT_THRESHOLD_HIGH
    if repeat_count >= RISK_REPEAT_THRESHOLD_HIGH:
        return "상"

    if audit_type in AUDIT_TYPE_WEIGHT:
        return AUDIT_TYPE_WEIGHT[audit_type]

    return "중"


# ─────────────────────────────────────────
# 폴백 분류
# ─────────────────────────────────────────
def _fallback_classify(
    title:        str,
    audit_type:   str,
    repeat_count: int = 1,
) -> dict:
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
        "risk":       _determine_risk(title, audit_type, repeat_count),
        "reason":     "키워드 점수 기반 분류 (AI 오류 폴백)",
        "confidence": "low",
        "method":     "fallback"
    }