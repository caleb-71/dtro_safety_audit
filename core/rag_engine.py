# core/rag_engine.py
# RAG 엔진 — 유사 과거 사례 검색 후 AI 분류에 활용

import logging
import pandas as pd
from data.vector_store import (
    build_vector_store,
    search_similar,
    get_vector_store_status
)
from core.classifier import classify_item
from config.settings import PROCESSED_DIR
from tqdm import tqdm

logger = logging.getLogger(__name__)


def initialize_rag(df: pd.DataFrame = None) -> bool:
    """
    RAG 초기화 — 벡터DB 구축
    :param df: 심사 이력 DataFrame (없으면 저장된 CSV 로드)
    :return: 성공 여부
    """
    if df is None:
        csv_path = PROCESSED_DIR / "processed_data.csv"
        if not csv_path.exists():
            logger.error("전처리 데이터 없음")
            return False
        df = pd.read_csv(csv_path, dtype=str)

    logger.info("RAG 벡터DB 구축 시작")
    return build_vector_store(df)


def classify_with_rag(row: pd.Series) -> dict:
    """
    단일 행에 대해 RAG 기반 AI 분류 수행
    :param row: DataFrame 행
    :return: 분류 결과
    """
    title      = str(row.get("title", ""))
    problem    = str(row.get("problem", ""))
    audit_type = str(row.get("audit_type", ""))
    text       = str(row.get("analysis_text", f"{title} {problem}"))

    # 유사 과거 사례 검색
    similar_cases = search_similar(text, top_k=3)

    # AI 분류
    result = classify_item(
        title=title,
        problem=problem,
        audit_type=audit_type,
        similar_cases=similar_cases
    )

    return result


def run_full_classification(
    df: pd.DataFrame,
    progress_callback=None
) -> pd.DataFrame:
    """
    전체 데이터 AI 분류 실행
    :param df: 전처리된 DataFrame
    :param progress_callback: 진행률 콜백 (Streamlit용)
    :return: 분류 결과가 추가된 DataFrame
    """
    df = df.copy()
    total = len(df)

    results = []
    for i, (idx, row) in enumerate(df.iterrows()):
        result = classify_with_rag(row)
        results.append(result)

        # Streamlit 진행률 업데이트
        if progress_callback:
            progress_callback(i + 1, total, row.get("title", ""))

    # 결과 컬럼 추가
    df["ai_part"]       = [r["part"]       for r in results]
    df["ai_risk"]       = [r["risk"]        for r in results]
    df["ai_reason"]     = [r["reason"]      for r in results]
    df["ai_confidence"] = [r["confidence"]  for r in results]
    df["ai_method"]     = [r["method"]      for r in results]

    return df


def get_rag_status() -> dict:
    """RAG 시스템 상태 반환"""
    status = get_vector_store_status()
    return {
        "vector_db_ready": status["ready"],
        "vector_db_count": status["total"],
    }