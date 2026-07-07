# core/embedder.py
# 텍스트 임베딩 모듈 (nomic-embed-text 활용)
# RAG 검색의 핵심 — 텍스트를 벡터로 변환
#
# ※ OLLAMA_MODE 와 무관하게 임베딩은 항상 로컬 Ollama 를 사용한다.
#    사내망 AI 서버(/llm/model)는 채팅 전용이며 임베딩 API 가 없음.
#    network 모드에서도 로컬에 nomic-embed-text 만 설치돼 있으면 RAG 동작.

import logging
import ollama
from config.settings import EMBEDDING_MODEL

logger = logging.getLogger(__name__)


def get_embedding(text: str) -> list[float]:
    """
    단일 텍스트를 벡터로 변환
    :param text: 임베딩할 텍스트
    :return: 벡터 (float 리스트)
    """
    try:
        text = text.strip()
        if not text:
            logger.warning("빈 텍스트 임베딩 요청")
            return []

        response = ollama.embeddings(
            model=EMBEDDING_MODEL,
            prompt=text
        )
        return response["embedding"]

    except Exception as e:
        logger.error(f"임베딩 오류: {e}")
        return []


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    여러 텍스트 일괄 임베딩
    :param texts: 텍스트 리스트
    :return: 벡터 리스트
    """
    embeddings = []
    for i, text in enumerate(texts):
        embedding = get_embedding(text)
        embeddings.append(embedding)
        if (i + 1) % 10 == 0:
            logger.info(f"임베딩 진행: {i+1}/{len(texts)}")
    return embeddings


def test_embedding():
    """임베딩 모델 작동 테스트"""
    test_text = "MSDS 현행화 미흡"
    result = get_embedding(test_text)
    if result:
        logger.info(f"임베딩 테스트 성공: 벡터 차원 {len(result)}")
        return True
    else:
        logger.error("임베딩 테스트 실패")
        return False