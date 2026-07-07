# data/preprocessor.py

import re
import logging
import pandas as pd
from config.settings import PROCESSED_DIR

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 형식적 완료 문구 목록 (벡터화 제외용)
# ─────────────────────────────────────────
TRIVIAL_RESULT_PATTERNS = [
    "조치완료", "조치 완료", "이행완료", "이행 완료",
    "시행완료", "시행 완료", "완료", "처리완료",
    "해당없음", "해당 없음", "없음",
]


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("데이터 전처리 시작")
    df = df.copy()

    # ── 개선 1: 불필요 컬럼 제거
    df = _drop_unnecessary_columns(df)

    df = _clean_whitespace(df)
    df = _fill_empty_values(df)
    df = _create_analysis_text(df)
    df = _normalize_year(df)
    df = _normalize_audit_type(df)

    logger.info(f"전처리 완료: {len(df)}건")
    return df


# ─────────────────────────────────────────
# 개선 1: 불필요 컬럼 제거 (신규)
# ─────────────────────────────────────────
def _drop_unnecessary_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    임베딩/분석에 불필요한 컬럼 제거
    - Source.Name: 파워쿼리 자동 생성, 분석 무관
    - attachment:  첨부파일명, 임베딩 노이즈
    """
    drop_cols = ["Source.Name", "attachment"]
    existing  = [c for c in drop_cols if c in df.columns]
    if existing:
        df = df.drop(columns=existing)
        logger.info(f"불필요 컬럼 제거: {existing}")
    return df


# ─────────────────────────────────────────
# 공백/특수문자 정리 (기존 + 개선)
# ─────────────────────────────────────────
def _clean_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """불필요한 공백, 특수문자 정리"""
    text_cols = [
        "title", "problem", "improvement",
        "action_plan", "action_result", "future_plan",
        "department", "location",   # ← 개선: 부서/장소 추가
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .str.replace(r"\r\n|\r|\n", " ", regex=True)  # 줄바꿈 → 공백
                .str.replace(r"\s+", " ", regex=True)          # 연속 공백 → 1개
                .str.replace(r"[○❍●▶→ㅇ\*]", "", regex=True)  # 특수기호 제거
                .str.strip()
            )
    return df


# ─────────────────────────────────────────
# 빈값 채우기 (기존 유지)
# ─────────────────────────────────────────
def _fill_empty_values(df: pd.DataFrame) -> pd.DataFrame:
    defaults = {
        "problem":       "내용 없음",
        "improvement":   "내용 없음",
        "action_plan":   "내용 없음",
        "action_result": "내용 없음",
        "future_plan":   "내용 없음",
        "location":      "미기재",
        "department":    "미기재",
        "legal_basis":   "미기재",
    }
    for col, default in defaults.items():
        if col in df.columns:
            df[col] = df[col].replace("", default)
    return df


# ─────────────────────────────────────────
# AI 분석용 통합 텍스트 생성 (개선)
# ─────────────────────────────────────────
def _create_analysis_text(df: pd.DataFrame) -> pd.DataFrame:
    """
    벡터화 텍스트 생성

    ── 포함 컬럼 ─────────────────────────────────
    [제목]      title         핵심 분류 기준       전체
    [문제점]    problem       상세 내용            최대 300자
    [개선방안]  improvement   해결책 패턴          최대 200자
    [추진실적]  action_result 완료 패턴 학습       최대 150자 (형식적 완료 제외)
    [관련근거]  legal_basis   법령명 → 분류 정확도 최대 100자 (신규)

    ── 제외 컬럼 ─────────────────────────────────
    Source.Name, attachment   → 이미 제거됨
    seq, year, mgmt_no 등     → 메타데이터 활용
    action_plan, future_plan  → 미래 계획, 분류 무관
    """
    def _is_trivial(text: str) -> bool:
        """형식적 완료 문구 여부 판단"""
        t = text.strip()
        # 20자 이하이고 완료 문구 포함 시 형식적 문구로 판단
        if len(t) <= 20:
            for pattern in TRIVIAL_RESULT_PATTERNS:
                if pattern in t:
                    return True
        return False

    def combine(row) -> str:
        parts = []

        # 제목 (전체)
        title = str(row.get("title", "")).strip()
        if title and title != "nan":
            parts.append(f"[제목] {title}")

        # 현황및문제점 (최대 300자)
        problem = str(row.get("problem", "")).strip()
        if problem and problem not in ("nan", "내용 없음"):
            parts.append(f"[문제점] {problem[:300]}")

        # 개선방안 (최대 200자)
        improvement = str(row.get("improvement", "")).strip()
        if improvement and improvement not in ("nan", "내용 없음"):
            parts.append(f"[개선방안] {improvement[:200]}")

        # 추진실적 (최대 150자, 형식적 완료 문구 제외)
        action_result = str(row.get("action_result", "")).strip()
        if (action_result
                and action_result not in ("nan", "내용 없음")
                and not _is_trivial(action_result)):
            parts.append(f"[추진실적] {action_result[:150]}")

        # 관련근거 (최대 100자, 신규 추가)
        # 법령명이 포함되면 법령 기반 파트 분류 정확도 향상
        legal_basis = str(row.get("legal_basis", "")).strip()
        if legal_basis and legal_basis not in ("nan", "미기재", "내용 없음"):
            parts.append(f"[관련근거] {legal_basis[:100]}")

        return " | ".join(parts)

    df["analysis_text"] = df.apply(combine, axis=1)
    return df


# ─────────────────────────────────────────
# 연도 정규화 (기존 유지)
# ─────────────────────────────────────────
def _normalize_year(df: pd.DataFrame) -> pd.DataFrame:
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df["year"] = df["year"].fillna(0).astype(int)
    return df


# ─────────────────────────────────────────
# 심사구분 정규화 (기존 유지)
# ─────────────────────────────────────────
def _normalize_audit_type(df: pd.DataFrame) -> pd.DataFrame:
    if "audit_type" in df.columns:
        df["audit_type"] = df["audit_type"].str.strip()
        df["audit_type"] = df["audit_type"].replace({
            "개선 권고": "개선권고",
            "현지 시정": "현지시정",
        })
    return df


# ─────────────────────────────────────────
# 전처리 결과 저장 (기존 유지)
# ─────────────────────────────────────────
def save_processed(
    df: pd.DataFrame,
    filename: str = "processed_data.csv"
) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    save_path = PROCESSED_DIR / filename
    df.to_csv(save_path, index=False, encoding="utf-8-sig")
    logger.info(f"전처리 데이터 저장 완료: {save_path}")