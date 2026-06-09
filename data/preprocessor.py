# data/preprocessor.py
# DTRO 자체종합안전심사 AI 분석 시스템 - 데이터 전처리
# 벡터화 텍스트: 제목 + 현황및문제점 + 개선방안 + 추진실적 (확장)

import logging
import pandas as pd
from config.settings import PROCESSED_DIR

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 메인 전처리 함수
# ─────────────────────────────────────────
def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """
    로드된 DataFrame 전처리 수행
    :param df: 원본 DataFrame
    :return: 전처리된 DataFrame
    """
    logger.info("데이터 전처리 시작")

    df = df.copy()
    df = _clean_whitespace(df)
    df = _fill_empty_values(df)
    df = _create_analysis_text(df)
    df = _normalize_year(df)
    df = _normalize_audit_type(df)

    logger.info(f"전처리 완료: {len(df)}건")
    return df


# ─────────────────────────────────────────
# 공백/특수문자 정리
# ─────────────────────────────────────────
def _clean_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """불필요한 공백, 특수문자 정리"""
    text_cols = [
        "title", "problem", "improvement",
        "action_plan", "action_result", "future_plan"
    ]

    for col in text_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .str.replace(r"\s+", " ", regex=True)      # 연속 공백 → 1개
                .str.replace(r"[○❍●▶]", "", regex=True)    # 특수 기호 제거
                .str.strip()
            )
    return df


# ─────────────────────────────────────────
# 빈값 채우기
# ─────────────────────────────────────────
def _fill_empty_values(df: pd.DataFrame) -> pd.DataFrame:
    """빈 셀을 의미있는 기본값으로 채우기"""
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
# AI 분석용 통합 텍스트 생성
# ─────────────────────────────────────────
def _create_analysis_text(df: pd.DataFrame) -> pd.DataFrame:
    """
    AI 및 RAG 벡터화에 사용할 통합 텍스트 생성

    ── 벡터화 포함 컬럼 ──────────────────────────
    [제목]      title          핵심 분류 기준
    [문제점]    problem        상세 내용 (AI 분류 핵심)
    [개선방안]  improvement    해결책 패턴 파악
    [추진실적]  action_result  완료/미완료 패턴 학습 (신규 추가)

    ── 벡터화 제외 컬럼 (메타데이터로만 활용) ────
    seq, year, mgmt_no, detail_no
    audit_type, department
    → 코드/숫자값이라 벡터화 시 노이즈 발생
    → ChromaDB 메타데이터로 저장해 필터 검색에 활용
    """
    def combine(row) -> str:
        parts = []

        # 제목
        title = str(row.get("title", "")).strip()
        if title and title != "nan":
            parts.append(f"[제목] {title}")

        # 현황및문제점
        problem = str(row.get("problem", "")).strip()
        if problem and problem not in ("nan", "내용 없음"):
            parts.append(f"[문제점] {problem}")

        # 개선방안
        improvement = str(row.get("improvement", "")).strip()
        if improvement and improvement not in ("nan", "내용 없음"):
            parts.append(f"[개선방안] {improvement}")

        # 추진실적 (신규 추가)
        # 과거 완료 사례의 해결 패턴을 AI가 학습
        # → 유사사례 검색 시 "어떻게 해결했는지" 까지 참고 가능
        action_result = str(row.get("action_result", "")).strip()
        if action_result and action_result not in ("nan", "내용 없음"):
            parts.append(f"[추진실적] {action_result}")

        return " | ".join(parts)

    df["analysis_text"] = df.apply(combine, axis=1)
    return df


# ─────────────────────────────────────────
# 연도 정규화
# ─────────────────────────────────────────
def _normalize_year(df: pd.DataFrame) -> pd.DataFrame:
    """연도 컬럼 정수형으로 통일"""
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df["year"] = df["year"].fillna(0).astype(int)
    return df


# ─────────────────────────────────────────
# 심사구분 정규화
# ─────────────────────────────────────────
def _normalize_audit_type(df: pd.DataFrame) -> pd.DataFrame:
    """심사구분 값 통일 (공백/오타 등 보정)"""
    if "audit_type" in df.columns:
        df["audit_type"] = df["audit_type"].str.strip()
        df["audit_type"] = df["audit_type"].replace({
            "개선 권고": "개선권고",
            "현지 시정": "현지시정",
        })
    return df


# ─────────────────────────────────────────
# 전처리 결과 저장
# ─────────────────────────────────────────
def save_processed(
    df: pd.DataFrame,
    filename: str = "processed_data.csv"
) -> None:
    """전처리된 데이터를 CSV로 저장"""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    save_path = PROCESSED_DIR / filename
    df.to_csv(save_path, index=False, encoding="utf-8-sig")
    logger.info(f"전처리 데이터 저장 완료: {save_path}")