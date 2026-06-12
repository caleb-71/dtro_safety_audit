# config/settings.py
# DTRO 자체종합안전심사 AI 분석 시스템 - 전체 설정

from pathlib import Path

# ─────────────────────────────────────────
# 프로젝트 경로 설정
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR         = BASE_DIR / "data"
RAW_DIR          = DATA_DIR / "raw"
PROCESSED_DIR    = DATA_DIR / "processed"
VECTOR_DB_DIR    = DATA_DIR / "vector_db"
OUTPUT_DIR       = BASE_DIR / "output_files"
LOG_DIR          = BASE_DIR / "logs"

# ─────────────────────────────────────────
# 법령/규정 문서 경로 (신규)
# ─────────────────────────────────────────
LEGAL_DOCS_DIR   = DATA_DIR / "legal_docs"     # PDF 원본
LEGAL_DB_DIR     = DATA_DIR / "legal_db"       # 법령 벡터DB

# 법령 폴더 분류
LEGAL_CATEGORIES = {
    "laws":        "법률",
    "regulations": "규정",
    "guidelines":  "가이드라인",
    "sop":         "표준운영절차",
}

# 법령 청크 설정
LEGAL_CHUNK_SIZE    = 500   # 청크당 글자 수
LEGAL_CHUNK_OVERLAP = 100   # 청크 간 겹치는 글자 수
LEGAL_TOP_K         = 3     # 검색 시 반환할 결과 수

# ─────────────────────────────────────────
# AI 모델 설정 (Ollama)
# ─────────────────────────────────────────
OLLAMA_MODEL     = "llama3.1:8b"
EMBEDDING_MODEL  = "nomic-embed-text"
OLLAMA_TIMEOUT   = 120

# ─────────────────────────────────────────
# 분류 파트 정의
# ─────────────────────────────────────────
AUDIT_PARTS = ["안전계획", "안전보건", "재난안전"]

RISK_LEVELS = {
    "상": 3,
    "중": 2,
    "하": 1
}

# ─────────────────────────────────────────
# 엑셀 컬럼 매핑
# ─────────────────────────────────────────
EXCEL_COLUMNS = {
    "순번":         "seq",
    "심사년도":     "year",
    "개선요구일":   "request_date",
    "관리번호":     "mgmt_no",
    "세부번호":     "detail_no",
    "심사구분":     "audit_type",
    "심사유형":     "audit_category",
    "제목":         "title",
    "장소":         "location",
    "현황및문제점":  "problem",
    "관련근거":     "legal_basis",
    "추진구분":     "progress_type",
    "개선방안":     "improvement",
    "추진계획":     "action_plan",
    "추진실적":     "action_result",
    "향후계획":     "future_plan",
    "첨부파일":     "attachment",
    "담당부서":     "department",
    "등록일":       "reg_date"
}

# ─────────────────────────────────────────
# 분석 설정
# ─────────────────────────────────────────
RAG_TOP_K  = 3
BATCH_SIZE = 10

# ─────────────────────────────────────────
# 출력 파일명 설정
# ─────────────────────────────────────────
OUTPUT_EXCEL_NAME  = "심사분석결과.xlsx"
OUTPUT_REPORT_NAME = "종합안전심사_AI분석보고서.docx"

# ─────────────────────────────────────────
# 로그 설정
# ─────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE  = LOG_DIR / "audit_system.log"