# pages/page_chat.py
# 💬 AI 질의응답 — 메인 채팅 창구
# 대화 히스토리 파일 영구 저장

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.llm_client import llm_chat, llm_status
from core.legal_engine import quick_legal_search
from data.legal_store import get_legal_store_status

from config.settings import (
    OLLAMA_MODEL, PROCESSED_DIR, OUTPUT_DIR
)
from data.vector_store import search_similar

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 채팅 히스토리 저장 경로
# ─────────────────────────────────────────
CHAT_DIR      = OUTPUT_DIR / "chat_history"
CHAT_FILE     = CHAT_DIR / "chat_history.json"
MAX_HISTORY   = 100  # 최대 저장 대화 수


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("💬 AI 질의응답")
    st.markdown("심사 데이터에 대해 자유롭게 질문하세요.")
    st.markdown("---")

    # 데이터 로드
    df = _load_data()

    # 채팅 히스토리 초기화
    _init_chat_history()

    # 빠른 질의 버튼
    _render_quick_buttons(df)
    st.markdown("---")

    # 대화 화면
    _render_chat_area()

    # 입력창
    _render_input_area(df)


# ─────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────
def _load_data() -> pd.DataFrame | None:
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.warning("⚠️ 데이터가 없습니다. [데이터 업로드] 메뉴에서 업로드하세요.")
        return None
    return pd.read_csv(csv_path, dtype=str)


# ─────────────────────────────────────────
# 채팅 히스토리 초기화
# ─────────────────────────────────────────
def _init_chat_history():
    """session_state 및 파일 초기화"""
    CHAT_DIR.mkdir(parents=True, exist_ok=True)

    if "chat_messages" not in st.session_state:
        # 파일에서 불러오기
        if CHAT_FILE.exists():
            try:
                with open(CHAT_FILE, "r", encoding="utf-8") as f:
                    st.session_state["chat_messages"] = json.load(f)
            except Exception:
                st.session_state["chat_messages"] = []
        else:
            st.session_state["chat_messages"] = []


def _save_chat_history():
    """채팅 히스토리 파일 저장"""
    try:
        CHAT_DIR.mkdir(parents=True, exist_ok=True)
        messages = st.session_state.get("chat_messages", [])
        # 최대 저장 수 초과 시 오래된 것 삭제
        if len(messages) > MAX_HISTORY:
            messages = messages[-MAX_HISTORY:]
            st.session_state["chat_messages"] = messages
        with open(CHAT_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"채팅 저장 오류: {e}")


# ─────────────────────────────────────────
# 빠른 질의 버튼
# ─────────────────────────────────────────
def _render_quick_buttons(df: pd.DataFrame | None):
    st.subheader("⚡ 빠른 질의")

    col1, col2, col3, col4 = st.columns(4)
    col5, col6, col7, col8 = st.columns(4)

    buttons = [
        (col1, "📊 파트별 건수 현황",        "파트별 지적사항 건수와 비율을 알려줘"),
        (col2, "🔁 반복 지적 TOP10",          "반복 지적사항 TOP 10을 보여줘"),
        (col3, "🔴 리스크 상 목록",           "리스크 등급 상인 지적사항 목록을 보여줘"),
        (col4, "🏢 부서별 빈도 TOP10",        "부서별 지적사항 건수 TOP 10을 알려줘"),
        (col5, "🚇 안전계획 주요 항목",       "안전계획 파트의 주요 지적사항을 분석해줘"),
        (col6, "🏥 안전보건 주요 항목",       "안전보건 파트의 주요 지적사항을 분석해줘"),
        (col7, "🌪️ 재난안전 주요 항목",      "재난안전 파트의 주요 지적사항을 분석해줘"),
        (col8, "📋 시정명령 현황",            "시정명령 건수와 해당 부서 목록을 알려줘"),
    ]

    for col, label, question in buttons:
        with col:
            if st.button(label, use_container_width=True, key=f"quick_{label}"):
                st.session_state["pending_question"] = question


# ─────────────────────────────────────────
# 대화 화면 렌더링
# ─────────────────────────────────────────
def _render_chat_area():
    messages = st.session_state.get("chat_messages", [])

    if not messages:
        st.info(
            "💡 아직 대화 내역이 없습니다.\n\n"
            "위의 빠른 질의 버튼을 누르거나 "
            "아래 입력창에 직접 질문해보세요!"
        )
        return

    # 최근 20개만 표시
    display_messages = messages[-20:]

    for msg in display_messages:
        role    = msg.get("role", "user")
        content = msg.get("content", "")
        ts      = msg.get("timestamp", "")

        with st.chat_message(role):
            st.markdown(content)
            if ts:
                st.caption(ts)

    # 히스토리 관리 버튼
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 2, 4])
    with col1:
        if st.button("🗑️ 대화 초기화", key="clear_chat"):
            st.session_state["chat_messages"] = []
            _save_chat_history()
            st.rerun()
    with col2:
        if st.button("📥 대화 내보내기", key="export_chat"):
            _export_chat()


# ─────────────────────────────────────────
# 입력창
# ─────────────────────────────────────────
def _render_input_area(df: pd.DataFrame | None):
    # 빠른 버튼으로 들어온 질문 처리
    pending = st.session_state.pop("pending_question", None)

    user_input = st.chat_input(
        "질문을 입력하세요... (예: 전력팀 지적사항 알려줘)",
        key="chat_input"
    )

    question = pending or user_input
    if not question:
        return

    if df is None:
        st.error("❌ 데이터가 없어 질의응답을 할 수 없습니다.")
        return

    # 사용자 메시지 저장
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.session_state["chat_messages"].append({
        "role":      "user",
        "content":   question,
        "timestamp": ts
    })

    # AI 응답 생성
    with st.spinner("AI가 분석 중입니다..."):
        answer = _generate_answer(question, df)

    # AI 메시지 저장
    st.session_state["chat_messages"].append({
        "role":      "assistant",
        "content":   answer,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })

    # 파일 저장
    _save_chat_history()
    st.rerun()


# ─────────────────────────────────────────
# 대화 이력 정제 헬퍼
# ─────────────────────────────────────────
def _clean_history_content(content: str) -> str:
    """
    이전 답변을 대화 이력으로 재전달하기 전에
    모델이 복사하면 안 되는 장식 요소를 제거합니다.
    - "⚠️ ..." 경고 문구 블록 (--- 이후 전체)
    - "⚖️ **법령/규정 기반 답변**" 헤더
    - 너무 긴 답변은 앞 300자만 (이력은 맥락 파악용이므로 충분)
    """
    # 경고 문구 블록 제거 (--- 구분선 이후)
    if "\n---\n" in content:
        content = content.split("\n---\n")[0]
    # 법령 답변 헤더 제거
    content = content.replace("⚖️ **법령/규정 기반 답변**", "").strip()
    # 길이 제한
    if len(content) > 300:
        content = content[:300] + "..."
    return content


# ─────────────────────────────────────────
# AI 응답 생성 (핵심)
# ─────────────────────────────────────────
def _generate_answer(question: str, df: pd.DataFrame) -> str:
    try:
        # ── 법령DB 상태 먼저 확인 ──
        legal_status = get_legal_store_status()

        # ── 법령 관련 질문 감지 ──
        # 기존 키워드 방식의 한계:
        # "MSDS 갱신주기?" 같은 질문은 법령 키워드가 없어서 건너뜀
        # → 해결: 법령DB 가 있으면 무조건 검색하고,
        #          유사도가 높은 결과가 있을 때만 법령 우선 답변
        legal_keywords = [
            "법령", "법률", "규정", "조항", "제○조", "근거",
            "위반", "가이드", "SOP", "절차서", "지침",
            # ── 추가: 주기/기준 관련 질문 키워드 ──
            "주기", "기간", "기준", "몇 년", "몇년", "얼마나",
            "언제", "몇 회", "몇회", "횟수", "의무", "해야",
            "MSDS", "물질안전보건자료", "화학물질",
            "점검", "교육", "훈련", "갱신", "업데이트",
        ]
        is_legal_query = any(kw in question for kw in legal_keywords)

        # ── 데이터 조회 의도 감지 (2026-07 추가) ──
        # [문제 사례] "전체기록에서 철도종사자안전교육 내역을 뽑아줘"
        #   → "교육" 단어 때문에 법령 질문으로 오분류되어
        #     심사이력 데이터를 전혀 보지 않고 법령PDF만 검색 → 오답
        # [해결] 아래 단어가 있으면 "심사이력 데이터 조회" 의도로 판단하고
        #   법령 전용 답변 경로를 건너뜀 (데이터 경로에서도 법령은
        #   보조 컨텍스트로 함께 검색되므로 정보 손실 없음)
        data_keywords = [
            "내역", "목록", "리스트", "뽑아", "추출", "검색해",
            "건수", "몇 건", "몇건", "기록", "이력", "현황",
            "지적사항", "지적된", "지적받은", "지적은",
            "전체", "모두", "알려줘", "보여줘", "분석해",
        ]
        is_data_query = any(kw in question for kw in data_keywords)

        # ── 법령 우선 검색 (핵심 변경) ──
        # 기존: is_legal_query 일 때만 법령DB 검색
        # 변경: 법령DB 가 있으면 항상 검색하고,
        #        유사도 0.5 이상 결과가 있으면 법령 우선 답변
        #        (키워드 감지 누락으로 인한 오답 방지)
        if legal_status["ready"]:
            from data.legal_store import search_legal
            # top_k=5 로 충분히 검색 (기존 2 → 5 로 증가)
            legal_results = search_legal(question, top_k=5)

            # 유사도 0.45 이상 결과가 있으면 법령 우선 답변
            # ※ 코사인 유사도 기준 (legal_store 가 cosine 으로 재구축된 후 유효)
            #   nomic-embed-text 는 한국어에서 유사 문서도 0.45~0.6 정도로
            #   나오는 경우가 많아 0.5 보다 약간 완화함.
            #   너무 낮추면 무관한 문서가 잡히므로 0.4 미만으로는 내리지 말 것
            high_sim_results = [
                r for r in legal_results
                if r.get("similarity", 0) >= 0.45
            ]

            # 데이터 조회 의도가 있으면 법령 전용 답변으로 빠지지 않음
            # (아래 데이터 경로에서 법령을 보조 컨텍스트로 함께 사용)
            if (high_sim_results or is_legal_query) and not is_data_query:
                with st.spinner("법령/규정 검색 중..."):
                    legal_answer = quick_legal_search(question, top_k=5)

                # 법령DB 에서 찾은 경우 출처 명시
                if high_sim_results:
                    sources = list({
                        r["metadata"].get("file_stem", "")
                        for r in high_sim_results
                        if r.get("metadata", {}).get("file_stem")
                    })
                    source_str = ", ".join(sources)
                    return (
                        f"⚖️ **법령/규정 기반 답변** "
                        f"*(참고문서: {source_str})*\n\n"
                        f"{legal_answer}\n\n"
                        f"---\n"
                        f"📌 위 답변은 등록된 법령/규정 문서에서 검색한 내용입니다."
                    )
                else:
                    return f"⚖️ **법령/규정 기반 답변**\n\n{legal_answer}"

        # ── 법령DB 에서 못 찾은 경우 — 일반 데이터 질의 ──
        context = _build_data_context(question, df)

        # 법령DB 보조 검색 (낮은 유사도라도 힌트로 활용)
        legal_context = ""
        if legal_status["ready"]:
            from data.legal_store import search_legal
            legal_results = search_legal(question, top_k=3)
            if legal_results:
                legal_parts = []
                for r in legal_results:
                    meta = r.get("metadata", {})
                    sim  = r.get("similarity", 0)
                    legal_parts.append(
                        f"- {meta.get('file_stem','')} "
                        f"({meta.get('category_ko','')}, 관련도 {sim:.0%}): "
                        f"{r.get('text','')[:200]}"
                    )
                legal_context = (
                    "\n\n[관련 법령/규정 (참고)]\n"
                    + "\n".join(legal_parts)
                )

        # ── 대화 이력 전달 (반복답변 버그 수정, 2026-07) ──
        # [변경 1] 최근 5턴 → 최근 2턴으로 축소
        #   8b급 소형 모델은 이력이 길수록 새 질문 대신
        #   과거 답변을 복사하는 경향이 강해짐
        # [변경 2] AI 답변에서 경고문(⚠️)·헤더(⚖️)를 제거하고 전달
        #   경고문까지 이력으로 들어가면 모델이 그 문구까지
        #   그대로 복사해서 출력하는 문제가 있었음
        history  = st.session_state.get("chat_messages", [])[:-1][-2:]
        messages = [
            {"role": h["role"], "content": _clean_history_content(h["content"])}
            for h in history
        ]

        system_prompt = f"""당신은 대구도시철도공사(DTRO) 자체종합안전심사 전문 AI 어시스턴트입니다.

[현재 데이터 현황]
{context}{legal_context}

[답변 원칙]
1. 데이터에 근거한 사실만 답변합니다
2. 건수, 비율 등 숫자는 정확하게 제시합니다
3. 한국어로 명확하고 간결하게 답변합니다
4. 표나 목록 형식으로 가독성을 높입니다
5. 법령 근거가 있으면 반드시 인용합니다
6. 법령/규정 자료에 명시된 내용과 AI 일반 지식이 다를 경우
   반드시 법령/규정 자료의 내용을 우선합니다
7. 이전 대화의 답변을 절대 복사하지 않습니다.
   반드시 마지막 질문에 대해서만 새로 답변합니다
8. 질문에 해당하는 데이터가 [현재 데이터 현황]에 없으면
   "해당 데이터를 찾을 수 없습니다"라고만 답변합니다"""

        # ── 경고 문구 추가 ──
        # 법령DB 에서 근거를 찾지 못한 경우
        # 사용자가 AI 자체 지식 기반 답변임을 인지할 수 있도록 표시
        disclaimer = (
            "\n\n---\n"
            "⚠️ *이 답변은 등록된 법령/규정 문서에서 직접 근거를 찾지 못해 "
            "AI 일반 지식을 바탕으로 한 것입니다. "
            "주기, 기준, 의무사항 등 중요한 내용은 반드시 관련 지침서를 직접 확인하세요.*"
        ) if not legal_status["ready"] else (
            "\n\n---\n"
            "⚠️ *법령/규정 문서에서 직접 근거를 찾지 못했습니다. "
            "관련 지침서를 직접 확인하시기 바랍니다.*"
        )

        messages.append({"role": "user", "content": question})

        response = llm_chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *messages
            ],
            options={"temperature": 0.3}
        )
        return response["message"]["content"] + disclaimer

    except Exception as e:
        logger.error(f"AI 응답 오류: {e}")
        return f"❌ 오류: {e}"



# ─────────────────────────────────────────
# 데이터 컨텍스트 구성
# ─────────────────────────────────────────
def _build_data_context(question: str, df: pd.DataFrame) -> str:
    """
    질문에 맞는 데이터를 pandas로 추출하여
    LLM에게 컨텍스트로 제공
    """
    context_parts = []

    # ── 기본 현황
    total = len(df)
    context_parts.append(f"총 지적사항: {total}건")

    if "year" in df.columns:
        years = sorted(df["year"].dropna().unique())
        context_parts.append(f"연도: {', '.join(str(y) for y in years)}")

    # ── AI 분류 현황
    if "ai_part" in df.columns:
        part_counts = df["ai_part"].value_counts()
        part_str = ", ".join(
            f"{p}: {c}건" for p, c in part_counts.items()
        )
        context_parts.append(f"파트별 건수: {part_str}")

    # ── 심사구분
    if "audit_type" in df.columns:
        type_counts = df["audit_type"].value_counts()
        type_str = ", ".join(
            f"{t}: {c}건" for t, c in type_counts.items()
        )
        context_parts.append(f"심사구분: {type_str}")

    # ── 질문 키워드 기반 관련 데이터 추출
    keyword_data = _extract_relevant_data(question, df)
    if keyword_data:
        context_parts.append(keyword_data)

    # ── RAG 유사사례 검색
    try:
        similar = search_similar(question, top_k=3)
        if similar:
            cases = []
            for s in similar:
                meta = s.get("metadata", {})
                cases.append(
                    f"- {meta.get('title', '')} "
                    f"({meta.get('department', '')} / "
                    f"{meta.get('ai_part', '')})"
                )
            context_parts.append(
                "유사 과거 사례:\n" + "\n".join(cases)
            )
    except Exception:
        pass

    return "\n".join(context_parts)


# ─────────────────────────────────────────
# 질문 키워드 기반 데이터 추출
# ─────────────────────────────────────────
# 자유 키워드 추출 시 무시할 조사·일반 단어
_STOPWORDS = {
    "전체", "기록", "기록에서", "내역", "내역을", "목록", "리스트",
    "뽑아줘", "뽑아", "추출", "추출해줘", "알려줘", "보여줘", "검색해줘",
    "대한", "대해", "관련", "관한", "있는", "해당", "모두", "모든",
    "건수", "현황", "분석해줘", "분석", "심사", "지적사항", "지적",
    "무엇", "어떤", "어디", "얼마나",
}


def _search_by_free_keywords(question: str, df: pd.DataFrame) -> str:
    """
    질문 속 자유 키워드로 제목·현황및문제점 컬럼을 직접 검색합니다 (2026-07 추가)

    [문제 배경]
    기존 로직은 부서명/파트명/반복/리스크 같은 정해진 패턴만 인식해서
    "철도종사자안전교육 내역 뽑아줘" 처럼 제목 키워드로 묻는 질문에는
    관련 데이터를 전혀 찾지 못했음

    [동작 방식]
    1. 질문을 공백으로 쪼개고 조사를 제거한 뒤 2글자 이상 단어만 추출
    2. 불용어(뽑아줘, 내역 등 일반 단어) 제외
    3. 각 단어가 제목(title) 또는 현황및문제점(problem)에 포함된 행 검색
    4. 찾은 행의 핵심 정보(제목/부서/년도/심사구분)를 컨텍스트로 반환
    """
    if df is None or df.empty:
        return ""

    # ── 1. 질문에서 후보 키워드 추출 ──
    tokens = []
    for raw in question.replace(",", " ").split():
        # 흔한 조사 제거 (에서/에게/으로/의/을/를/은/는/이/가/도/와/과/에)
        word = raw
        for josa in ("에서", "에게", "으로", "이라", "라고",
                     "의", "을", "를", "은", "는", "이", "가", "도", "와", "과", "에"):
            if word.endswith(josa) and len(word) > len(josa) + 1:
                word = word[: -len(josa)]
                break
        word = word.strip()
        if len(word) >= 2 and word not in _STOPWORDS:
            tokens.append(word)

    if not tokens:
        return ""

    # ── 2. 제목/문제점 컬럼에서 키워드 포함 행 검색 ──
    title_col   = "title"   if "title"   in df.columns else None
    problem_col = "problem" if "problem" in df.columns else None
    if not title_col:
        return ""

    mask = pd.Series(False, index=df.index)
    matched_tokens = []
    for tok in tokens:
        tok_mask = df[title_col].str.contains(tok, na=False, regex=False)
        if problem_col:
            tok_mask |= df[problem_col].str.contains(tok, na=False, regex=False)
        if tok_mask.any():
            mask |= tok_mask
            matched_tokens.append(tok)

    if not mask.any():
        return ""

    hits = df[mask].head(10)  # 프롬프트 길이 보호를 위해 최대 10건

    # ── 3. 컨텍스트 문자열 구성 ──
    lines = [f"키워드({', '.join(matched_tokens)}) 검색 결과 {int(mask.sum())}건:"]
    for _, row in hits.iterrows():
        parts = [f"제목: {row.get(title_col, '')}"]
        if "department" in df.columns and pd.notna(row.get("department")):
            parts.append(f"부서: {row['department']}")
        if "year" in df.columns and pd.notna(row.get("year")):
            parts.append(f"년도: {row['year']}")
        if "audit_type" in df.columns and pd.notna(row.get("audit_type")):
            parts.append(f"구분: {row['audit_type']}")
        if "ai_part" in df.columns and pd.notna(row.get("ai_part")):
            parts.append(f"파트: {row['ai_part']}")
        lines.append("  - " + " / ".join(parts))
        # 문제점 내용도 요약 제공 (있을 때만, 150자 제한)
        if problem_col and pd.notna(row.get(problem_col)) and str(row.get(problem_col)).strip():
            lines.append(f"    문제점: {str(row[problem_col])[:150]}")

    return "\n".join(lines)


def _extract_relevant_data(question: str, df: pd.DataFrame) -> str:
    """질문에서 키워드를 감지하고 관련 데이터를 추출"""
    result_parts = []

    # ── 자유 키워드 제목/내용 검색 (가장 먼저 실행, 2026-07 추가) ──
    free_search = _search_by_free_keywords(question, df)
    if free_search:
        result_parts.append(free_search)

    # 부서명 감지
    if "department" in df.columns:
        departments = df["department"].dropna().unique()
        for dept in departments:
            if dept in question:
                dept_df   = df[df["department"] == dept]
                titles    = dept_df["title"].value_counts().head(5)
                title_str = ", ".join(
                    f"{t}({c}건)" for t, c in titles.items()
                )
                result_parts.append(
                    f"{dept} 지적사항 {len(dept_df)}건: {title_str}"
                )
                break

    # 파트명 감지
    if "ai_part" in df.columns:
        for part in ["안전계획", "안전보건", "재난안전"]:
            if part in question:
                part_df = df[df["ai_part"] == part]
                titles  = part_df["title"].value_counts().head(10)
                t_str   = "\n".join(
                    f"  {i+1}. {t} ({c}건)"
                    for i, (t, c) in enumerate(titles.items())
                )
                result_parts.append(
                    f"{part} 파트 {len(part_df)}건 주요 항목:\n{t_str}"
                )
                break

    # 반복 지적사항 감지
    if any(kw in question for kw in ["반복", "TOP", "상위"]):
        if "title" in df.columns:
            repeat = (
                df["title"].value_counts()
                .head(10)
                .reset_index()
            )
            repeat.columns = ["지적사항", "횟수"]
            r_str = "\n".join(
                f"  {i+1}. {row['지적사항']} ({row['횟수']}회)"
                for i, row in repeat.iterrows()
            )
            result_parts.append(f"반복 지적사항 TOP10:\n{r_str}")

    # 리스크 상 감지
    if any(kw in question for kw in ["리스크 상", "위험", "시정명령"]):
        if "ai_risk" in df.columns:
            high = df[df["ai_risk"] == "상"]
            if not high.empty:
                items = high[["title", "department", "ai_part"]].head(15)
                h_str = "\n".join(
                    f"  - {row['title']} ({row['department']} / {row['ai_part']})"
                    for _, row in items.iterrows()
                )
                result_parts.append(f"리스크 상 {len(high)}건:\n{h_str}")

    # 시정명령 감지
    if "시정명령" in question and "audit_type" in df.columns:
        cmd_df = df[df["audit_type"] == "시정명령"]
        if not cmd_df.empty:
            depts = cmd_df["department"].value_counts().head(10)
            d_str = ", ".join(
                f"{d}({c}건)" for d, c in depts.items()
            )
            result_parts.append(
                f"시정명령 {len(cmd_df)}건, 부서별: {d_str}"
            )

    # 부서별 빈도 TOP 감지
    if any(kw in question for kw in ["부서", "TOP"]):
        if "department" in df.columns:
            top_dept = df["department"].value_counts().head(10)
            d_str = "\n".join(
                f"  {i+1}. {d} ({c}건)"
                for i, (d, c) in enumerate(top_dept.items())
            )
            result_parts.append(f"부서별 지적 TOP10:\n{d_str}")

    # 조치 이행실태 감지 (신규, 2026-07)
    # "조치가 안 된 지적사항은?", "이행률 낮은 부서는?" 같은 질문 처리
    if any(kw in question for kw in ["이행", "조치", "미조치", "완료율", "추진실적", "컨설팅"]):
        try:
            from core.action_analyzer import (
                add_action_status, action_summary,
                action_rate_by_group, consulting_targets,
            )
            df_act = add_action_status(df)
            s = action_summary(df_act)
            result_parts.append(
                f"조치 이행실태: 전체 {s['total']}건 중 "
                f"완료 {s['완료']}건, 형식적완료 {s['형식적']}건, "
                f"진행중 {s['진행중']}건, 미확인 {s['미확인']}건 "
                f"(이행률 {s['이행률']}%)"
            )
            dept_rate = action_rate_by_group(df_act, "department")
            if not dept_rate.empty:
                low5 = dept_rate.head(5)
                r_str = "\n".join(
                    f"  - {row['department']}: 이행률 {row['이행률(%)']}% "
                    f"(지적 {row['지적건수']}건, 완료 {row['완료']}건)"
                    for _, row in low5.iterrows()
                )
                result_parts.append(f"이행률 낮은 부서 TOP5:\n{r_str}")
            targets = consulting_targets(df_act)
            if not targets.empty:
                t_str = ", ".join(
                    f"{row['department']}({row['이행률(%)']}%)"
                    for _, row in targets.iterrows()
                )
                result_parts.append(f"컨설팅 우선 대상 부서(지적 3건↑+이행률 60%↓): {t_str}")
        except Exception:
            pass

    return "\n".join(result_parts)


# ─────────────────────────────────────────
# 대화 내보내기
# ─────────────────────────────────────────
def _export_chat():
    """대화 내역을 텍스트로 내보내기"""
    messages = st.session_state.get("chat_messages", [])
    if not messages:
        st.warning("내보낼 대화 내역이 없습니다.")
        return

    lines = ["DTRO 자체종합안전심사 AI 질의응답 내역\n"]
    lines.append(f"내보내기 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append("=" * 60 + "\n")

    for msg in messages:
        role = "👤 질문" if msg["role"] == "user" else "🤖 답변"
        ts   = msg.get("timestamp", "")
        lines.append(f"\n[{ts}] {role}\n{msg['content']}\n")

    content = "\n".join(lines)
    filename = f"chat_export_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    st.download_button(
        label="⬇️ 텍스트 파일 다운로드",
        data=content.encode("utf-8"),
        file_name=filename,
        mime="text/plain",
        use_container_width=True
    )