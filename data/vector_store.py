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
        metadata={"description": "DTRO 자체종합안전심사 이력"}
    )
    return collection


# ─────────────────────────────────────────
# 벡터화 텍스트 생성
# ─────────────────────────────────────────
def _build_vector_text(row: pd.Series) -> str:
    """
    벡터화할 텍스트 생성
    포함 컬럼: 제목, 현황및문제점, 개선방안, 추진실적

    제외 컬럼 (메타데이터로만 활용):
    순번, 심사년도, 관리번호, 세부번호, 심사구분, 담당부서
    → 코드/숫자값이라 벡터화 시 노이즈
    → ChromaDB 메타데이터로 저장해 필터 검색에 활용
    """
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

    # 추진실적 (완료/미완료 패턴 학습용)
    action_result = str(row.get("action_result", "")).strip()
    if action_result and action_result not in ("nan", "내용 없음"):
        parts.append(f"[추진실적] {action_result}")

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
    """
    def safe_str(val) -> str:
        """None/nan/빈값을 빈 문자열로 변환"""
        v = str(val).strip()
        return "" if v in ("nan", "None", "NaN") else v

    return {
        # 기존 메타데이터
        "year":       safe_str(row.get("year", "")),
        "title":      safe_str(row.get("title", "")),
        "department": safe_str(row.get("department", "")),
        "audit_type": safe_str(row.get("audit_type", "")),
        "ai_part":    safe_str(row.get("ai_part", "")),

        # 추가 메타데이터
        "seq":        safe_str(row.get("seq", "")),        # 순번
        "mgmt_no":    safe_str(row.get("mgmt_no", "")),    # 관리번호
        "detail_no":  safe_str(row.get("detail_no", "")),  # 세부번호
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
            metadata={"description": "DTRO 자체종합안전심사 이력"}
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