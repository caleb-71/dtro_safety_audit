# data/loader.py
# DTRO 자체종합안전심사 AI 분석 시스템 - 데이터 로더
# 연도별 엑셀 파일을 읽어 통합 DataFrame으로 반환

import logging
from pathlib import Path
from typing import Optional
import pandas as pd
from config.settings import (
    RAW_DIR, EXCEL_COLUMNS, LOG_FILE, LOG_DIR
)

# ─────────────────────────────────────────
# 로거 설정
# ─────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 단일 엑셀 파일 로드
# ─────────────────────────────────────────
def load_single_excel(file_path: Path) -> Optional[pd.DataFrame]:
    """
    단일 엑셀 파일을 읽어 DataFrame으로 반환
    :param file_path: 엑셀 파일 경로
    :return: DataFrame 또는 None
    """
    try:
        logger.info(f"파일 로드 시작: {file_path.name}")

        df = pd.read_excel(
            file_path,
            dtype=str,          # 모든 컬럼 문자열로 읽기
            keep_default_na=False  # NaN 대신 빈 문자열 유지
        )

        # 컬럼명 공백 제거
        df.columns = df.columns.str.strip()

        # 실제 컬럼과 설정 컬럼 비교
        expected = set(EXCEL_COLUMNS.keys())
        actual   = set(df.columns.tolist())
        missing  = expected - actual

        if missing:
            logger.warning(f"누락된 컬럼: {missing}")

        # 컬럼명 한글 → 영문 변환
        df = df.rename(columns=EXCEL_COLUMNS)

        # 파일명에서 연도 추출 (예: 2023_심사이력.xlsx → 2023)
        year_from_filename = _extract_year_from_filename(file_path.name)
        if year_from_filename and "year" not in df.columns:
            df["year"] = str(year_from_filename)

        # 소스 파일명 기록 (추적용)
        df["source_file"] = file_path.name

        logger.info(f"로드 완료: {len(df)}건 — {file_path.name}")
        return df

    except FileNotFoundError:
        logger.error(f"파일을 찾을 수 없음: {file_path}")
        return None
    except Exception as e:
        logger.error(f"파일 로드 오류 [{file_path.name}]: {e}")
        return None


# ─────────────────────────────────────────
# 여러 연도 파일 통합 로드
# ─────────────────────────────────────────
def load_all_excel(data_dir: Path = RAW_DIR) -> pd.DataFrame:
    """
    raw 폴더의 모든 엑셀 파일을 읽어 하나의 DataFrame으로 통합
    :param data_dir: 엑셀 파일이 있는 폴더
    :return: 통합 DataFrame
    """
    excel_files = sorted(data_dir.glob("*.xlsx"))

    if not excel_files:
        logger.error(f"엑셀 파일 없음: {data_dir}")
        raise FileNotFoundError(f"엑셀 파일이 없습니다: {data_dir}")

    logger.info(f"총 {len(excel_files)}개 파일 발견")

    dfs = []
    for file_path in excel_files:
        df = load_single_excel(file_path)
        if df is not None:
            dfs.append(df)

    if not dfs:
        raise ValueError("로드된 데이터가 없습니다.")

    # 전체 통합
    combined_df = pd.concat(dfs, ignore_index=True)
    logger.info(f"전체 통합 완료: 총 {len(combined_df)}건")

    return combined_df


# ─────────────────────────────────────────
# 특정 연도 파일만 로드
# ─────────────────────────────────────────
def load_by_year(year: int, data_dir: Path = RAW_DIR) -> Optional[pd.DataFrame]:
    """
    특정 연도 파일만 로드
    :param year: 연도 (예: 2025)
    :param data_dir: 엑셀 파일 폴더
    :return: DataFrame 또는 None
    """
    # 연도가 파일명에 포함된 파일 검색
    matched = [f for f in data_dir.glob("*.xlsx") if str(year) in f.name]

    if not matched:
        logger.warning(f"{year}년 파일을 찾을 수 없습니다.")
        return None

    return load_single_excel(matched[0])


# ─────────────────────────────────────────
# 내부 유틸리티
# ─────────────────────────────────────────
def _extract_year_from_filename(filename: str) -> Optional[int]:
    """파일명에서 연도(4자리 숫자) 추출"""
    import re
    match = re.search(r"(20\d{2})", filename)
    if match:
        return int(match.group(1))
    return None


# ─────────────────────────────────────────
# 로드 결과 요약 출력
# ─────────────────────────────────────────
def print_load_summary(df: pd.DataFrame) -> None:
    """로드된 데이터 요약 정보 출력"""
    print("\n" + "=" * 50)
    print("📊 데이터 로드 요약")
    print("=" * 50)
    print(f"  총 건수     : {len(df)}건")

    if "year" in df.columns:
        year_counts = df["year"].value_counts().sort_index()
        print(f"  연도별 건수 :")
        for year, count in year_counts.items():
            print(f"    {year}년 → {count}건")

    if "department" in df.columns:
        dept_counts = df["department"].value_counts()
        print(f"  부서 수     : {dept_counts.shape[0]}개 부서")

    if "audit_type" in df.columns:
        type_counts = df["audit_type"].value_counts()
        print(f"  심사구분    :")
        for t, c in type_counts.items():
            print(f"    {t} → {c}건")
    print("=" * 50 + "\n")