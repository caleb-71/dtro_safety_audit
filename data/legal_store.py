# data/legal_store.py
# 법령/규정 PDF 벡터DB 관리
# PDF 파싱 → 청크 분할 → 임베딩 → ChromaDB 저장

import logging
from pathlib import Path

import chromadb
import fitz  # pymupdf
from chromadb.config import Settings
from tqdm import tqdm

from config.settings import (
    LEGAL_DB_DIR,
    LEGAL_DOCS_DIR,
    LEGAL_CATEGORIES,
    LEGAL_CHUNK_SIZE,
    LEGAL_CHUNK_OVERLAP,
    LEGAL_TOP_K,
    EMBEDDING_MODEL,
)
from core.embedder import get_embedding

logger = logging.getLogger(__name__)

LEGAL_COLLECTION = "dtro_legal_docs"


# ─────────────────────────────────────────
# ChromaDB 클라이언트
# ─────────────────────────────────────────
def get_legal_client() -> chromadb.ClientAPI:
    LEGAL_DB_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(LEGAL_DB_DIR),
        settings=Settings(anonymized_telemetry=False)
    )


def get_legal_collection() -> chromadb.Collection:
    client = get_legal_client()
    return client.get_or_create_collection(
        name=LEGAL_COLLECTION,
        metadata={"description": "DTRO 법령/규정 문서"}
    )


# ─────────────────────────────────────────
# PDF 텍스트 추출
# ─────────────────────────────────────────
def extract_pdf_text(pdf_path: Path) -> str:
    """PDF에서 전체 텍스트 추출"""
    try:
        doc  = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()
    except Exception as e:
        logger.error(f"PDF 추출 오류 [{pdf_path.name}]: {e}")
        return ""


# ─────────────────────────────────────────
# 텍스트 청크 분할
# ─────────────────────────────────────────
def split_into_chunks(
    text: str,
    chunk_size: int = LEGAL_CHUNK_SIZE,
    overlap:    int = LEGAL_CHUNK_OVERLAP
) -> list[str]:
    """
    텍스트를 일정 크기의 청크로 분할
    overlap: 청크 간 겹치는 부분 (문맥 유지)
    """
    chunks = []
    start  = 0
    length = len(text)

    while start < length:
        end   = min(start + chunk_size, length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap

    return chunks


# ─────────────────────────────────────────
# 법령 벡터DB 구축
# ─────────────────────────────────────────
def build_legal_store(
    progress_callback=None
) -> dict:
    """
    legal_docs 폴더의 모든 PDF를 벡터DB에 저장
    :param progress_callback: 진행률 콜백
    :return: 결과 딕셔너리
    """
    # 기존 컬렉션 초기화
    client = get_legal_client()
    try:
        client.delete_collection(LEGAL_COLLECTION)
    except Exception:
        pass

    collection = client.create_collection(
        name=LEGAL_COLLECTION,
        metadata={"description": "DTRO 법령/규정 문서"}
    )

    # 전체 PDF 파일 수집
    all_pdfs = []
    for folder_en, folder_ko in LEGAL_CATEGORIES.items():
        folder_path = LEGAL_DOCS_DIR / folder_en
        if folder_path.exists():
            pdfs = list(folder_path.glob("*.pdf"))
            for pdf in pdfs:
                all_pdfs.append((pdf, folder_en, folder_ko))

    if not all_pdfs:
        logger.warning("PDF 파일이 없습니다.")
        return {"success": False, "total_chunks": 0, "files": 0}

    logger.info(f"법령 벡터DB 구축 시작: {len(all_pdfs)}개 파일")

    ids        = []
    embeddings = []
    documents  = []
    metadatas  = []
    chunk_idx  = 0
    file_results = []

    for file_no, (pdf_path, cat_en, cat_ko) in enumerate(all_pdfs):
        if progress_callback:
            progress_callback(file_no + 1, len(all_pdfs), pdf_path.name)

        # PDF 텍스트 추출
        text = extract_pdf_text(pdf_path)
        if not text:
            logger.warning(f"텍스트 없음: {pdf_path.name}")
            continue

        # 청크 분할
        chunks = split_into_chunks(text)
        logger.info(f"{pdf_path.name}: {len(chunks)}개 청크")

        # 각 청크 임베딩
        file_chunk_count = 0
        for c_idx, chunk in enumerate(chunks):
            embedding = get_embedding(chunk)
            if not embedding:
                continue

            chunk_id = f"{pdf_path.stem}_{c_idx}"
            ids.append(chunk_id)
            embeddings.append(embedding)
            documents.append(chunk)
            metadatas.append({
                "file_name":   pdf_path.name,
                "file_stem":   pdf_path.stem,
                "category":    cat_en,
                "category_ko": cat_ko,
                "chunk_index": str(c_idx),
                "total_chunks": str(len(chunks)),
            })
            file_chunk_count += 1
            chunk_idx += 1

        file_results.append({
            "file":   pdf_path.name,
            "cat":    cat_ko,
            "chunks": file_chunk_count
        })

    if not ids:
        return {"success": False, "total_chunks": 0, "files": 0}

    # 배치 저장 (100건씩)
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i:i + batch_size],
            embeddings=embeddings[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size]
        )
        logger.info(f"법령 저장: {min(i+batch_size, len(ids))}/{len(ids)}")

    logger.info(f"법령 벡터DB 구축 완료: {len(ids)}개 청크")
    return {
        "success":      True,
        "total_chunks": len(ids),
        "files":        len(file_results),
        "file_results": file_results
    }


# ─────────────────────────────────────────
# 법령 검색
# ─────────────────────────────────────────
def search_legal(
    query_text:      str,
    top_k:           int  = LEGAL_TOP_K,
    filter_category: str  = None,
) -> list[dict]:
    """
    관련 법령/규정 검색
    :param query_text:      검색할 텍스트 (지적사항 내용)
    :param top_k:           반환할 결과 수
    :param filter_category: 카테고리 필터 (laws/regulations 등)
    :return: 관련 법령 청크 리스트
    """
    try:
        collection = get_legal_collection()
        if collection.count() == 0:
            return []

        query_embedding = get_embedding(query_text)
        if not query_embedding:
            return []

        where = None
        if filter_category:
            where = {"category": {"$eq": filter_category}}

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"]
        )

        legal_results = []
        for i in range(len(results["ids"][0])):
            legal_results.append({
                "text":       results["documents"][0][i],
                "metadata":   results["metadatas"][0][i],
                "similarity": round(1 - results["distances"][0][i], 3)
            })

        return legal_results

    except Exception as e:
        logger.error(f"법령 검색 오류: {e}")
        return []


# ─────────────────────────────────────────
# 법령DB 현황
# ─────────────────────────────────────────
def get_legal_store_status() -> dict:
    """법령 벡터DB 현황"""
    try:
        collection = get_legal_collection()
        count      = collection.count()

        # 파일별 청크 수 집계
        if count > 0:
            results = collection.get(include=["metadatas"])
            files   = {}
            for meta in results["metadatas"]:
                fname = meta.get("file_name", "unknown")
                cat   = meta.get("category_ko", "")
                if fname not in files:
                    files[fname] = {"category": cat, "chunks": 0}
                files[fname]["chunks"] += 1
        else:
            files = {}

        return {
            "ready":        count > 0,
            "total_chunks": count,
            "total_files":  len(files),
            "files":        files
        }
    except Exception as e:
        logger.error(f"법령DB 상태 오류: {e}")
        return {
            "ready": False,
            "total_chunks": 0,
            "total_files":  0,
            "files":        {}
        }


# ─────────────────────────────────────────
# PDF 파일 목록 조회
# ─────────────────────────────────────────
def get_pdf_file_list() -> dict:
    """legal_docs 폴더의 PDF 파일 목록"""
    result = {}
    for folder_en, folder_ko in LEGAL_CATEGORIES.items():
        folder_path = LEGAL_DOCS_DIR / folder_en
        if folder_path.exists():
            pdfs = sorted(folder_path.glob("*.pdf"))
            result[folder_en] = {
                "name_ko": folder_ko,
                "files":   [p.name for p in pdfs],
                "count":   len(pdfs)
            }
        else:
            result[folder_en] = {
                "name_ko": folder_ko,
                "files":   [],
                "count":   0
            }
    return result