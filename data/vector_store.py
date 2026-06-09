# data/vector_store.py
# ChromaDB 벡터 저장소 관리
# 과거 심사 이력을 벡터DB에 저장하고 유사사례 검색

import logging
import pandas as pd
import chromadb
from chromadb.config import Settings
from tqdm import tqdm
from core.embedder import get_embedding
from config.settings import VECTOR_DB_DIR

logger = logging.getLogger(__name__)

# ChromaDB 컬렉션 이름
COLLECTION_NAME = "dtro_safety_audit"


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


def build_vector_store(df: pd.DataFrame) -> bool:
    """
    DataFrame을 벡터DB에 저장
    :param df: 전처리된 심사 이력 DataFrame
    :return: 성공 여부
    """
    try:
        collection = get_or_create_collection()

        # 기존 데이터 초기화
        client = get_chroma_client()
        client.delete_collection(COLLECTION_NAME)
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
            text = str(row.get("analysis_text", ""))
            if not text or text == "nan":
                continue

            embedding = get_embedding(text)
            if not embedding:
                continue

            ids.append(str(idx))
            embeddings.append(embedding)
            documents.append(text)
            metadatas.append({
                "year":       str(row.get("year", "")),
                "title":      str(row.get("title", "")),
                "department": str(row.get("department", "")),
                "audit_type": str(row.get("audit_type", "")),
                "ai_part":    str(row.get("ai_part", "")),
            })

        # 배치로 저장 (100건씩)
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            collection.add(
                ids=ids[i:i+batch_size],
                embeddings=embeddings[i:i+batch_size],
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size]
            )
            logger.info(f"저장 완료: {min(i+batch_size, len(ids))}/{len(ids)}")

        logger.info(f"벡터DB 구축 완료: {len(ids)}건")
        return True

    except Exception as e:
        logger.error(f"벡터DB 구축 오류: {e}")
        return False


def search_similar(
    query_text: str,
    top_k: int = 3,
    filter_part: str = None
) -> list[dict]:
    """
    유사 사례 검색
    :param query_text: 검색할 텍스트
    :param top_k: 반환할 결과 수
    :param filter_part: 특정 파트로 필터링
    :return: 유사 사례 리스트
    """
    try:
        collection = get_or_create_collection()

        if collection.count() == 0:
            return []

        query_embedding = get_embedding(query_text)
        if not query_embedding:
            return []

        where = {"ai_part": filter_part} if filter_part else None

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


def get_vector_store_status() -> dict:
    """벡터DB 현황 반환"""
    try:
        collection = get_or_create_collection()
        return {
            "total": collection.count(),
            "ready": collection.count() > 0
        }
    except Exception as e:
        return {"total": 0, "ready": False}