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
# AI 응답 생성 (핵심)
# ─────────────────────────────────────────
def _generate_answer(question: str, df: pd.DataFrame) -> str:
    try:
        # 법령 관련 질문 감지
        legal_keywords = [
            "법령", "법률", "규정", "조항", "제○조", "근거",
            "위반", "가이드", "SOP", "절차서", "지침"
        ]
        is_legal_query = any(kw in question for kw in legal_keywords)

        # 법령DB 상태 확인
        legal_status = get_legal_store_status()

        # 법령 관련 질문이고 DB가 구축된 경우
        if is_legal_query and legal_status["ready"]:
            with st.spinner("법령 검색 중..."):
                legal_answer = quick_legal_search(question)
            return f"⚖️ **법령/규정 기반 답변**\n\n{legal_answer}"

        # 일반 데이터 질의
        context = _build_data_context(question, df)

        # 법령DB가 있으면 추가 검색
        legal_context = ""
        if legal_status["ready"]:
            from data.legal_store import search_legal
            legal_results = search_legal(question, top_k=2)
            if legal_results:
                legal_parts = []
                for r in legal_results:
                    meta = r.get("metadata", {})
                    legal_parts.append(
                        f"- {meta.get('file_stem','')} "
                        f"({meta.get('category_ko','')}): "
                        f"{r.get('text','')[:200]}"
                    )
                legal_context = (
                    "\n\n[관련 법령/규정]\n"
                    + "\n".join(legal_parts)
                )

        # 직전 대화 이력 (마지막 항목은 방금 저장된 '현재 질문'이므로 제외 —
        # 아래에서 question 을 다시 붙이기 때문에 포함하면 중복 전달됨)
        history  = st.session_state.get("chat_messages", [])[:-1][-5:]
        messages = [
            {"role": h["role"], "content": h["content"]}
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
5. 법령 근거가 있으면 반드시 인용합니다"""

        messages.append({"role": "user", "content": question})

        response = llm_chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *messages
            ],
            options={"temperature": 0.3}
        )
        return response["message"]["content"]

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
def _extract_relevant_data(question: str, df: pd.DataFrame) -> str:
    """질문에서 키워드를 감지하고 관련 데이터를 추출"""
    result_parts = []

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