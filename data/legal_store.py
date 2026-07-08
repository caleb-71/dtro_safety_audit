# data/legal_store.py
# 법령/규정 PDF 벡터DB 관리
# PDF 파싱 → 청크 분할 → 임베딩 → ChromaDB 저장

import logging
import re
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
    LEGAL_SYNONYMS,
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
        # hnsw:space="cosine" : L2 기본값 버그 수정 — 코사인 유사도 사용
        metadata={"description": "DTRO 법령/규정 문서",
                  "hnsw:space": "cosine"}
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
# 조항 시작을 나타내는 패턴들
# 예) "제16장", "제5조", "6.4 사용중인...", "3.1.2 ..."
#     이런 지점에서 청크를 끊어야 "6.4 조항 전체" 가
#     하나의 청크에 온전히 들어가 검색 정확도가 올라감
_CLAUSE_PATTERN = re.compile(
    r"(?=\n\s*(?:"
    r"제\s*\d+\s*[장조절항]"      # 제16장, 제5조, 제2절, 제3항
    r"|\d{1,2}(?:\.\d{1,2}){1,3}\s"  # 6.4 / 3.1.2 뒤에 공백
    r"|[①-⑳]"                      # 원문자 항목
    r"))"
)


def split_into_chunks(
    text: str,
    chunk_size: int = LEGAL_CHUNK_SIZE,
    overlap:    int = LEGAL_CHUNK_OVERLAP
) -> list[str]:
    """
    텍스트를 청크로 분할 — 조항 경계 우선 방식 (개선, 2026-07)

    [기존 방식의 문제]
    500자마다 기계적으로 잘라서 "6.4 ..." 같은 조항이
    두 청크에 걸쳐 잘리거나, 무관한 조항들과 섞여
    임베딩 벡터가 희석되는 문제가 있었음 (MSDS 오답의 원인 중 하나)

    [개선 방식]
    1. 먼저 조항 번호 패턴(제N장/제N조/6.4 등)에서 텍스트를 분할
    2. 조항 하나가 chunk_size 이내면 그대로 하나의 청크로 사용
       → 조항 전체가 온전히 한 청크에 들어감
    3. 조항이 너무 길면 그 안에서만 기존 글자수 방식으로 세분화
    4. 너무 짧은 조각은 다음 조각과 합쳐 검색 노이즈 감소
    """
    # ── 1단계: 조항 경계로 1차 분할 ──
    sections = _CLAUSE_PATTERN.split(text)
    sections = [s.strip() for s in sections if s and s.strip()]

    # 조항 패턴이 하나도 없으면(일반 문서) 전체를 한 섹션으로
    if not sections:
        sections = [text.strip()]

    # ── 2단계: 짧은 조각은 앞 조각과 병합 (최소 80자) ──
    merged: list[str] = []
    for sec in sections:
        if merged and len(merged[-1]) < 80:
            merged[-1] = merged[-1] + "\n" + sec
        else:
            merged.append(sec)

    # ── 3단계: 긴 조항만 글자수 방식으로 세분화 ──
    chunks: list[str] = []
    for sec in merged:
        if len(sec) <= chunk_size:
            chunks.append(sec)
        else:
            start, length = 0, len(sec)
            while start < length:
                end   = min(start + chunk_size, length)
                piece = sec[start:end].strip()
                if piece:
                    chunks.append(piece)
                start += chunk_size - overlap

    return chunks


def _expand_query(query_text: str) -> str:
    """
    검색 질의에 동의어를 자동으로 덧붙입니다 (신규, 2026-07)

    예) "MSDS 갱신주기가 몇 년이야?"
        → "MSDS 갱신주기가 몇 년이야? (물질안전보건자료, 갱신, 개정, 현행화)"

    이렇게 하면 지침서 원문이 "물질안전보건자료" 로만 적혀 있어도
    임베딩 검색에서 해당 조항이 상위에 올라올 확률이 크게 높아집니다.
    동의어 사전은 config/settings.py 의 LEGAL_SYNONYMS 에서 관리합니다.
    """
    extra: list[str] = []
    for term, synonyms in LEGAL_SYNONYMS.items():
        if term in query_text:
            for s in synonyms:
                if s not in query_text and s not in extra:
                    extra.append(s)

    if extra:
        return f"{query_text} ({', '.join(extra)})"
    return query_text


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
        # hnsw:space="cosine" : L2 기본값 버그 수정 — 코사인 유사도 사용
        metadata={"description": "DTRO 법령/규정 문서",
                  "hnsw:space": "cosine"}
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

        # 동의어 확장: "MSDS" → "MSDS (물질안전보건자료...)" 형태로
        # 질의를 보강해서 용어 불일치로 인한 검색 실패를 방지
        expanded_query  = _expand_query(query_text)
        query_embedding = get_embedding(expanded_query)
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