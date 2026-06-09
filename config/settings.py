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
# AI 모델 설정 (Ollama)
# ─────────────────────────────────────────
OLLAMA_MODEL     = "llama3.1:8b"       # 분류 AI 모델
EMBEDDING_MODEL  = "nomic-embed-text"  # RAG 임베딩 모델
OLLAMA_TIMEOUT   = 120                 # 응답 대기 시간 (초)

# ─────────────────────────────────────────
# 분류 파트 정의
# ─────────────────────────────────────────
AUDIT_PARTS = ["안전계획", "안전보건", "재난안전"]

# 리스크 등급
RISK_LEVELS = {
    "상": 3,
    "중": 2,
    "하": 1
}

# ─────────────────────────────────────────
# 엑셀 컬럼 매핑
# (실제 엑셀 헤더명과 내부 변수명 연결)
# ─────────────────────────────────────────
EXCEL_COLUMNS = {
    "순번":        "seq",
    "심사년도":    "year",
    "개선요구일":  "request_date",
    "관리번호":    "mgmt_no",
    "세부번호":    "detail_no",
    "심사구분":    "audit_type",
    "심사유형":    "audit_category",
    "제목":        "title",
    "장소":        "location",
    "현황및문제점": "problem",
    "관련근거":    "legal_basis",
    "추진구분":    "progress_type",
    "개선방안":    "improvement",
    "추진계획":    "action_plan",
    "추진실적":    "action_result",
    "향후계획":    "future_plan",
    "첨부파일":    "attachment",
    "담당부서":    "department",
    "등록일":      "reg_date"
}

# ─────────────────────────────────────────
# 분석 설정
# ─────────────────────────────────────────
# RAG 검색 시 유사 사례 몇 개 가져올지
RAG_TOP_K = 3

# 배치 처리 크기 (한 번에 AI에게 보낼 건수)
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