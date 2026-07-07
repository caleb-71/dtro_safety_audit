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
LEGAL_TOP_K         = 8     # 검색 시 반환할 결과 수

# ─────────────────────────────────────────
# AI 모델 설정 (Ollama)
# ─────────────────────────────────────────
# ★ 여기만 변경하세요 ★
OLLAMA_MODE = "network"    # "local" = 내 PC Ollama / "network" = 사내망 서버 AI

# 공통
OLLAMA_MODEL     = "llama3.1:8b"
EMBEDDING_MODEL  = "nomic-embed-text"
OLLAMA_TIMEOUT   = 120

# 사내망 서버 AI 설정 (OLLAMA_MODE = "network" 일 때 사용)
NETWORK_LLM_URL     = "http://172.16.101.180:8080"   # 사내망 AI 서버 주소
NETWORK_LLM_MODEL   = "llama3.1:8b"                  # 서버에 설치된 모델명
NETWORK_LLM_NUM_CTX = 4096                           # 컨텍스트 길이
NETWORK_LLM_TIMEOUT = 300                            # 응답 대기 한도(초) — 긴 생성 대비
NETWORK_LLM_SESSION = "dtro_audit"                   # 서버 세션 구분자

# ※ 참고: 임베딩(벡터 검색용 nomic-embed-text)은 사내망 서버에 임베딩 API가
#   없으므로 모드와 무관하게 항상 로컬 Ollama를 사용합니다. (CPU로도 충분히 빠름)
#   network 모드에서 벡터 검색·RAG를 쓰려면 로컬 Ollama에
#   nomic-embed-text 모델만 설치되어 있으면 됩니다: ollama pull nomic-embed-text

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