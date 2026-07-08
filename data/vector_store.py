# data/vector_store.py
# ChromaDB 벡터 저장소 관리
# 과거 심사 이력을 벡터DB에 저장하고 유사사례 검색
# 벡터화 텍스트: 제목 + 문제점 + 개선방안 + 추진실적
# 메타데이터: 순번, 심사년도, 관리번호, 세부번호, 심사구분, 담당부서 추가

import logging
import pandas as pd
import chromadb
from chromadb.config import Settings
from tqdm import tqdm
from core.embedder import get_embedding
from config.settings import VECTOR_DB_DIR

logger = logging.getLogger(__name__)

COLLECTION_NAME = "dtro_safety_audit"


# ─────────────────────────────────────────
# ChromaDB 클라이언트
# ─────────────────────────────────────────
def get_chroma_client() -> chromadb.ClientAPI:
    """ChromaDB 클라이언트 반환 (로컬 저장)"""
    VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(VECTOR_DB_DIR),
        settings=Settings(anonymized_telemetry=False)
    )
    return client


def get_or_create_collection() -> chromadb.Collection:
    """컬렉션 가져오기 또는 생성"""
    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        # hnsw:space="cosine" : 유사도를 코사인 방식으로 계산하도록 지정
        # (미지정 시 기본값 L2 가 사용되어 similarity = 1 - distance 값이
        #  큰 음수가 되는 버그가 있었음. cosine 은 distance 가 0~2 범위라
        #  1 - distance 가 -1~1 의 의미 있는 유사도가 됨)
        metadata={"description": "DTRO 자체종합안전심사 이력",
                  "hnsw:space": "cosine"}
    )
    return collection


# ─────────────────────────────────────────
# 벡터화 텍스트 생성
# ─────────────────────────────────────────

# 형식적 완료 문구 목록 (벡터화 제외용)
_TRIVIAL_RESULTS = {
    "조치완료", "조치 완료", "이행완료", "이행 완료",
    "시행완료", "시행 완료", "완료", "처리완료",
    "해당없음", "해당 없음", "없음",
}

def _build_vector_text(row: pd.Series) -> str:
    """
    벡터화할 텍스트 생성

    ── 포함 컬럼 ──────────────────────────────────
    [제목]      title         핵심 분류 기준       전체
    [문제점]    problem       상세 내용            최대 300자
    [개선방안]  improvement   해결책 패턴          최대 200자
    [추진실적]  action_result 완료 패턴 학습       최대 150자
                              (형식적 완료 문구 제외)
    [관련근거]  legal_basis   법령명 → 분류 정확도 최대 100자 (신규)

    ── 제외 컬럼 (메타데이터로만 활용) ────────────
    Source.Name, attachment   → 분석 무관, 전처리 시 제거
    seq, year, mgmt_no 등     → 숫자/코드값, 필터 검색에 활용
    audit_type, department    → 메타데이터 필터 활용
    action_plan, future_plan  → 미래 계획, 분류 무관
    """

    def _is_trivial(text: str) -> bool:
        """형식적 완료 문구 여부 — 20자 이하 + 완료 키워드 포함"""
        if len(text) <= 20:
            return any(p in text for p in _TRIVIAL_RESULTS)
        return False

    def _safe(val, max_len: int = 0) -> str:
        """None/nan 제거 + 길이 제한"""
        v = str(val).strip()
        if v in ("nan", "None", "NaN", "내용 없음", "미기재"):
            return ""
        return v[:max_len] if max_len else v

    parts = []

    # 제목 (전체 — 핵심 분류 기준)
    title = _safe(row.get("title", ""))
    if title:
        parts.append(f"[제목] {title}")

    # 현황및문제점 (최대 300자)
    problem = _safe(row.get("problem", ""), max_len=300)
    if problem:
        parts.append(f"[문제점] {problem}")

    # 개선방안 (최대 200자)
    improvement = _safe(row.get("improvement", ""), max_len=200)
    if improvement:
        parts.append(f"[개선방안] {improvement}")

    # 추진실적 (최대 150자, 형식적 완료 문구 제외)
    # "조치완료" 같은 단순 문구는 노이즈 → 제외
    # 구체적인 조치 내용이 있는 경우만 포함
    action_result = _safe(row.get("action_result", ""), max_len=150)
    if action_result and not _is_trivial(action_result):
        parts.append(f"[추진실적] {action_result}")

    # 관련근거 (최대 100자, 신규 추가)
    # 법령명이 벡터에 포함되면 법령 기반 파트 분류 정확도 향상
    # 예) "산업안전보건기준에 관한 규칙 제133조" → 안전보건 분류에 기여
    legal_basis = _safe(row.get("legal_basis", ""), max_len=100)
    if legal_basis:
        parts.append(f"[관련근거] {legal_basis}")

    return " | ".join(parts)


# ─────────────────────────────────────────
# 메타데이터 생성
# ─────────────────────────────────────────
def _build_metadata(row: pd.Series) -> dict:
    """
    ChromaDB 메타데이터 생성
    필터 검색에 활용 가능한 컬럼들 저장

    활용 예시:
    - "2025년 개선권고 중 전력팀 건만 검색"
      → year="2025", audit_type="개선권고", department="전력팀"
    - "관리번호 106번 건 추적"
      → mgmt_no="106"
    - "종합청사 전기실 지적사항 검색"
      → location="종합청사 전기실"
    """
    def safe_str(val) -> str:
        """None/nan/빈값/미기재를 빈 문자열로 변환"""
        v = str(val).strip()
        return "" if v in ("nan", "None", "NaN", "미기재") else v

    return {
        # 기존 메타데이터
        "year":       safe_str(row.get("year", "")),
        "title":      safe_str(row.get("title", "")),
        "department": safe_str(row.get("department", "")),
        "audit_type": safe_str(row.get("audit_type", "")),
        "ai_part":    safe_str(row.get("ai_part", "")),

        # 기존 추가 메타데이터
        "seq":        safe_str(row.get("seq", "")),       # 순번
        "mgmt_no":    safe_str(row.get("mgmt_no", "")),   # 관리번호
        "detail_no":  safe_str(row.get("detail_no", "")), # 세부번호

        # 신규 추가
        "location":   safe_str(row.get("location", "")),  # 장소 (현장 검색용)
    }

# ─────────────────────────────────────────
# 벡터DB 구축
# ─────────────────────────────────────────
def build_vector_store(df: pd.DataFrame) -> bool:
    """
    DataFrame을 벡터DB에 저장
    :param df: 전처리된 심사 이력 DataFrame
    :return: 성공 여부
    """
    try:
        # 기존 컬렉션 초기화 후 재생성
        client = get_chroma_client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

        collection = client.create_collection(
            name=COLLECTION_NAME,
            # 재구축 시에도 반드시 cosine 방식으로 생성 (위 주석 참고)
            metadata={"description": "DTRO 자체종합안전심사 이력",
                      "hnsw:space": "cosine"}
        )

        logger.info(f"벡터DB 구축 시작: {len(df)}건")

        ids        = []
        embeddings = []
        documents  = []
        metadatas  = []

        for idx, row in tqdm(df.iterrows(), total=len(df), desc="벡터화"):

            # 벡터화 텍스트 생성
            text = _build_vector_text(row)
            if not text:
                logger.warning(f"빈 텍스트 건너뜀: idx={idx}")
                continue

            # 임베딩
            embedding = get_embedding(text)
            if not embedding:
                logger.warning(f"임베딩 실패 건너뜀: idx={idx}")
                continue

            ids.append(str(idx))
            embeddings.append(embedding)
            documents.append(text)
            metadatas.append(_build_metadata(row))

        if not ids:
            logger.error("벡터화된 데이터 없음")
            return False

        # 배치로 저장 (100건씩)
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            collection.add(
                ids=ids[i:i + batch_size],
                embeddings=embeddings[i:i + batch_size],
                documents=documents[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size]
            )
            logger.info(
                f"저장 완료: "
                f"{min(i + batch_size, len(ids))}/{len(ids)}"
            )

        logger.info(f"벡터DB 구축 완료: {len(ids)}건")
        return True

    except Exception as e:
        logger.error(f"벡터DB 구축 오류: {e}")
        return False


# ─────────────────────────────────────────
# 유사사례 검색
# ─────────────────────────────────────────
def search_similar(
    query_text: str,
    top_k: int = 3,
    filter_part: str = None,
    filter_year: str = None,
    filter_dept: str = None,
    filter_audit_type: str = None,
) -> list[dict]:
    """
    유사 사례 검색
    :param query_text:        검색할 텍스트
    :param top_k:             반환할 결과 수
    :param filter_part:       파트 필터 (안전계획/안전보건/재난안전)
    :param filter_year:       연도 필터 (예: "2025")
    :param filter_dept:       부서 필터 (예: "전력팀")
    :param filter_audit_type: 심사구분 필터 (예: "개선권고")
    :return: 유사 사례 리스트
    """
    try:
        collection = get_or_create_collection()

        if collection.count() == 0:
            return []

        query_embedding = get_embedding(query_text)
        if not query_embedding:
            return []

        # ── 필터 조건 구성 ──────────────────────
        # ChromaDB where 절: 여러 조건은 $and 로 결합
        filters = []
        if filter_part:
            filters.append({"ai_part": {"$eq": filter_part}})
        if filter_year:
            filters.append({"year": {"$eq": filter_year}})
        if filter_dept:
            filters.append({"department": {"$eq": filter_dept}})
        if filter_audit_type:
            filters.append({"audit_type": {"$eq": filter_audit_type}})

        if len(filters) == 0:
            where = None
        elif len(filters) == 1:
            where = filters[0]
        else:
            where = {"$and": filters}

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"]
        )

        similar_cases = []
        for i in range(len(results["ids"][0])):
            similar_cases.append({
                "text":       results["documents"][0][i],
                "metadata":   results["metadatas"][0][i],
                "similarity": round(1 - results["distances"][0][i], 3)
            })

        return similar_cases

    except Exception as e:
        logger.error(f"유사사례 검색 오류: {e}")
        return []


# ─────────────────────────────────────────
# 벡터DB 현황
# ─────────────────────────────────────────
def get_vector_store_status() -> dict:
    """벡터DB 현황 반환"""
    try:
        collection = get_or_create_collection()
        count = collection.count()
        return {
            "total": count,
            "ready": count > 0
        }
    except Exception as e:
        logger.error(f"벡터DB 상태 확인 오류: {e}")
        return {"total": 0, "ready": False}