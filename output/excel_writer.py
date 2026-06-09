# output/excel_writer.py
# 분류 결과 엑셀 저장

import logging
import pandas as pd
from pathlib import Path
from config.settings import OUTPUT_DIR, OUTPUT_EXCEL_NAME

logger = logging.getLogger(__name__)


def save_classified_excel(df: pd.DataFrame) -> Path:
    """분류 결과를 엑셀로 저장"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_path = OUTPUT_DIR / OUTPUT_EXCEL_NAME

    col_labels = {
        "year": "연도", "audit_type": "심사구분",
        "title": "제목", "department": "담당부서",
        "problem": "현황및문제점", "improvement": "개선방안",
        "ai_part": "AI분류파트", "ai_risk": "리스크등급",
        "ai_reason": "분류이유", "ai_method": "분류방법"
    }

    export_cols = [c for c in col_labels.keys() if c in df.columns]
    export_df = df[export_cols].copy()
    export_df.columns = [col_labels[c] for c in export_cols]

    export_df.to_excel(save_path, index=False, engine="openpyxl")
    logger.info(f"엑셀 저장 완료: {save_path}")
    return save_path