# data/preprocessor.py
# DTRO 자체종합안전심사 AI 분석 시스템 - 데이터 전처리

import re
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
    text_cols = ["title", "problem", "improvement",
                 "action_plan", "action_result", "future_plan"]

    for col in text_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .str.replace(r"\s+", " ", regex=True)  # 연속 공백 → 1개
                .str.replace(r"[○❍●▶]", "", regex=True)  # 특수 기호 제거
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
    AI에게 보낼 통합 분석 텍스트 생성
    제목 + 현황및문제점 + 개선방안 을 하나로 합침
    """
    def combine(row):
        parts = []
        if row.get("title"):
            parts.append(f"[제목] {row['title']}")
        if row.get("problem") and row["problem"] != "내용 없음":
            parts.append(f"[문제점] {row['problem']}")
        if row.get("improvement") and row["improvement"] != "내용 없음":
            parts.append(f"[개선방안] {row['improvement']}")
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
        # 유사값 통일
        df["audit_type"] = df["audit_type"].replace({
            "개선 권고": "개선권고",
            "현지 시정": "현지시정",
        })
    return df


# ─────────────────────────────────────────
# 전처리 결과 저장
# ─────────────────────────────────────────
def save_processed(df: pd.DataFrame, filename: str = "processed_data.csv") -> None:
    """전처리된 데이터를 CSV로 저장"""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    save_path = PROCESSED_DIR / filename
    df.to_csv(save_path, index=False, encoding="utf-8-sig")
    logger.info(f"전처리 데이터 저장 완료: {save_path}")