# pages/page_classify.py
# AI 분류 실행 화면
# 개선: Step 4 수동 보정 기능 추가 (오분류 건 직접 수정)

import shutil
import streamlit as st
import pandas as pd
import time
from pathlib import Path
from config.settings import PROCESSED_DIR, VECTOR_DB_DIR
from data.vector_store import get_vector_store_status
from core.rag_engine import initialize_rag, run_full_classification


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("🤖 AI 분류 실행")
    st.markdown("llama3.1:8b + 법령DB 연계로 지적사항을 3개 파트로 자동 분류합니다.")
    st.markdown("---")

    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.error("❌ 데이터가 없습니다. [데이터 업로드] 메뉴에서 먼저 업로드하세요.")
        return

    df         = pd.read_csv(csv_path, dtype=str)
    rag_status = get_vector_store_status()

    _render_status(df, rag_status)
    st.markdown("---")

    _render_vector_db_section(df, rag_status)
    st.markdown("---")

    _render_classify_section(df, csv_path, rag_status)
    st.markdown("---")

    if "ai_part" in df.columns:
        _render_result_preview(df)
        st.markdown("---")
        _render_reclassify_section(df, csv_path)
        st.markdown("---")
        _render_manual_correction(df, csv_path)   # ← 신규: 수동 보정


# ─────────────────────────────────────────
# 현재 상태 KPI
# ─────────────────────────────────────────
def _render_status(df: pd.DataFrame, rag_status: dict):
    st.subheader("📌 현재 상태")

    # 법령DB 상태도 함께 표시
    try:
        from data.legal_store import get_legal_store_status
        legal_status = get_legal_store_status()
        legal_ready  = legal_status.get("ready", False)
        legal_count  = legal_status.get("total_chunks", 0)
    except Exception:
        legal_ready = False
        legal_count = 0

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("📋 총 지적사항", f"{len(df):,}건")
    with col2:
        if rag_status["ready"]:
            st.metric("🗄️ 심사 벡터DB", f"{rag_status['total']:,}건 ✅")
        else:
            st.metric("🗄️ 심사 벡터DB", "미구축 ⚠️")
    with col3:
        if legal_ready:
            st.metric("⚖️ 법령DB", f"{legal_count:,}청크 ✅")
        else:
            st.metric("⚖️ 법령DB", "미구축 ⚠️")
    with col4:
        if "ai_part" in df.columns:
            classified = df["ai_part"].notna().sum()
            st.metric("🤖 분류 완료", f"{classified:,}건")
        else:
            st.metric("🤖 분류 완료", "0건")
    with col5:
        if "ai_part" in df.columns and len(df) > 0:
            pct = df["ai_part"].notna().sum() / len(df) * 100
            st.metric("📊 분류율", f"{pct:.1f}%")
        else:
            st.metric("📊 분류율", "0%")

    # 법령DB 미구축 경고
    if not legal_ready:
        st.warning(
            "⚠️ 법령DB가 구축되지 않았습니다. "
            "[⚖️ 법령/규정 관리] 메뉴에서 먼저 법령DB를 구축하면 "
            "분류 정확도가 크게 향상됩니다."
        )


# ─────────────────────────────────────────
# Step 1: 벡터DB 관리
# ─────────────────────────────────────────
def _render_vector_db_section(df: pd.DataFrame, rag_status: dict):
    st.subheader("Step 1️⃣  RAG 벡터DB 관리")
    st.caption("과거 심사 이력을 AI가 검색할 수 있도록 벡터화합니다.")

    if rag_status["ready"]:
        st.success(f"✅ 벡터DB 준비 완료 — {rag_status['total']:,}건 저장됨")
    else:
        st.warning("⚠️ 벡터DB가 구축되지 않았습니다. 먼저 구축하세요.")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔧 벡터DB 구축",
                     type="primary" if not rag_status["ready"] else "secondary",
                     use_container_width=True,
                     disabled=rag_status["ready"], key="btn_build"):
            with st.spinner("벡터DB 구축 중..."):
                success = initialize_rag(df)
                if success:
                    st.success("✅ 완료!")
                    st.rerun()
                else:
                    st.error("❌ 구축 실패.")

    with col2:
        if st.button("🔄 벡터DB 재구축",
                     use_container_width=True,
                     disabled=not rag_status["ready"], key="btn_rebuild"):
            with st.spinner("재구축 중..."):
                if initialize_rag(df):
                    st.success("✅ 완료!")
                    st.rerun()
                else:
                    st.error("❌ 실패.")

    with col3:
        if st.button("🗑️ 벡터DB 초기화",
                     use_container_width=True, key="btn_reset"):
            st.session_state["confirm_reset"] = True

    if st.session_state.get("confirm_reset", False):
        _render_reset_confirm()


def _render_reset_confirm():
    st.warning("⚠️ 정말로 벡터DB를 초기화하시겠습니까?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ 예, 초기화", type="primary",
                     use_container_width=True, key="btn_confirm_yes"):
            _reset_vector_db()  # ← 별도 함수로 분리
    with c2:
        if st.button("❌ 취소", use_container_width=True, key="btn_confirm_no"):
            st.session_state["confirm_reset"] = False
            st.rerun()


def _reset_vector_db():
    """
    벡터DB 초기화
    Windows WinError 32 해결:
    ChromaDB 클라이언트 연결을 먼저 닫은 후 폴더 삭제
    """
    try:
        # ── 1단계: ChromaDB 클라이언트 연결 먼저 해제
        # 연결이 열려있으면 Windows 에서 파일 잠금 발생
        try:
            from data.vector_store import get_chroma_client, COLLECTION_NAME
            client = get_chroma_client()
            # 컬렉션 삭제 (파일 잠금 해제 유도)
            try:
                client.delete_collection(COLLECTION_NAME)
            except Exception:
                pass
            # 클라이언트 객체 명시적 삭제
            del client
        except Exception:
            pass

        # ── 2단계: 잠금 해제 대기 (Windows 파일 시스템 특성)
        import time
        time.sleep(1)

        # ── 3단계: 폴더 삭제 후 재생성
        if VECTOR_DB_DIR.exists():
            # 파일별로 개별 삭제 (폴더 통째로 삭제보다 안전)
            import os
            for root, dirs, files in os.walk(VECTOR_DB_DIR, topdown=False):
                for file in files:
                    try:
                        os.remove(os.path.join(root, file))
                    except Exception as e:
                        # 개별 파일 삭제 실패 시 로그만 남기고 계속
                        import logging
                        logging.getLogger(__name__).warning(f"파일 삭제 실패: {file} — {e}")
                for dir_ in dirs:
                    try:
                        os.rmdir(os.path.join(root, dir_))
                    except Exception:
                        pass
            # 최상위 폴더는 남기고 내용물만 삭제
            # (Streamlit 재실행 후 ChromaDB 가 폴더를 다시 생성)

        VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
        st.session_state["confirm_reset"] = False
        st.success("✅ 벡터DB 초기화 완료! 이제 벡터DB를 새로 구축하세요.")
        st.rerun()

    except Exception as e:
        st.error(f"❌ 초기화 실패: {e}")
        st.caption(
            "💡 해결 방법: Streamlit 을 완전히 종료 후 재시작하고 다시 시도하세요.\n"
            "또는 PyCharm 터미널에서: rmdir /s /q data\\vector_db"
        )


# ─────────────────────────────────────────
# Step 2: AI 분류 실행
# ─────────────────────────────────────────
def _render_classify_section(df, csv_path, rag_status):
    st.subheader("Step 2️⃣  AI 분류 실행")
    st.caption("법령DB → 키워드 → AI 순서로 3단계 분류를 진행합니다.")

    # 분류 방법 설명
    with st.expander("📖 개선된 분류 방법 안내", expanded=False):
        st.markdown("""
        **3단계 분류 프로세스:**

        | 단계 | 방법 | 특징 |
        |---|---|---|
        | 1단계 | **법령DB 검색** | 관련 법령명으로 파트 확정 (가장 정확) |
        | 2단계 | **키워드 매칭** | STRONG_INDICATORS 키워드 빠른 판별 |
        | 3단계 | **AI 분류** | 법령 컨텍스트 포함하여 llama3.1:8b 판단 |

        **예시 (핸드리프트 케이스):**
        - 기존: AI가 "운행장애" 연결 → 안전계획 ❌
        - 개선: 법령DB에서 "산업안전보건기준에 관한 규칙" 검색 → 안전보건 ✅
        """)

    minutes = len(df) * 15 // 60
    st.info(f"⏱️ 예상 소요 시간: 약 {minutes}분 ({len(df):,}건 × 평균 15초/건)")

    if not rag_status["ready"]:
        st.error("❌ 벡터DB를 먼저 구축하세요.")

    if st.button("🚀 AI 분류 시작", type="primary",
                 use_container_width=True,
                 disabled=not rag_status["ready"], key="btn_classify"):
        _run_classification(df, csv_path)


# ─────────────────────────────────────────
# 분류 결과 미리보기
# ─────────────────────────────────────────
def _render_result_preview(df: pd.DataFrame):
    st.subheader("📋 분류 결과 미리보기")

    part_counts = df["ai_part"].value_counts()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🚇 안전계획", f"{part_counts.get('안전계획', 0)}건")
    col2.metric("🏥 안전보건", f"{part_counts.get('안전보건', 0)}건")
    col3.metric("🌪️ 재난안전", f"{part_counts.get('재난안전', 0)}건")
    cnt = part_counts.get("미분류", 0)
    if cnt > 0:
        col4.metric("❓ 미분류", f"{cnt}건", delta="재분류 필요", delta_color="inverse")
    else:
        col4.metric("✅ 미분류", "0건")

    # 분류 방법별 통계
    if "ai_method" in df.columns:
        method_counts = df["ai_method"].value_counts()
        st.caption(
            "분류 방법: "
            + "  |  ".join(
                f"{m}: {c}건" for m, c in method_counts.items()
            )
        )

    preview_cols  = ["year","audit_type","title","ai_part","ai_risk","ai_reason","ai_method"]
    available     = [c for c in preview_cols if c in df.columns]
    col_labels    = {
        "year":"연도","audit_type":"심사구분","title":"제목",
        "ai_part":"AI분류","ai_risk":"리스크",
        "ai_reason":"분류이유","ai_method":"분류방법"
    }
    display = df[available].head(20).copy()
    display.columns = [col_labels.get(c, c) for c in available]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────
# Step 3: 미분류 재분류
# ─────────────────────────────────────────
def _render_reclassify_section(df: pd.DataFrame, csv_path: Path):
    st.subheader("Step 3️⃣  미분류 항목 재분류")

    df_unc = df[df["ai_part"] == "미분류"].copy()
    if len(df_unc) == 0:
        st.success("✅ 미분류 항목이 없습니다!")
        return

    st.warning(f"⚠️ 미분류 항목 {len(df_unc)}건이 있습니다.")

    show_cols  = ["title", "department", "audit_type", "ai_reason"]
    avail_cols = [c for c in show_cols if c in df_unc.columns]
    col_map    = {"title":"제목","department":"담당부서",
                  "audit_type":"심사구분","ai_reason":"분류이유"}
    disp = df_unc[avail_cols].copy()
    disp.columns = [col_map.get(c, c) for c in avail_cols]
    st.dataframe(disp, use_container_width=True, hide_index=True)

    est = len(df_unc) * 15
    st.info(f"⏱️ 예상: 약 {est//60}분 {est%60}초")

    if st.button(f"🔄 미분류 {len(df_unc)}건 재분류",
                 type="primary", use_container_width=True, key="btn_reclassify"):
        _run_reclassification(df, df_unc, csv_path)


# ─────────────────────────────────────────
# Step 4: 수동 보정 (신규)
# ─────────────────────────────────────────
def _render_manual_correction(df: pd.DataFrame, csv_path: Path):
    st.subheader("Step 4️⃣  수동 보정")
    st.caption(
        "AI 분류 결과가 잘못된 건을 직접 수정합니다. "
        "법령DB 분류 결과가 틀린 경우에도 여기서 보정합니다."
    )

    if "ai_part" not in df.columns:
        st.info("AI 분류를 먼저 실행하세요.")
        return

    # ── 필터: 의심 건 우선 표시
    with st.expander("🔧 필터 옵션", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_method = st.selectbox(
                "분류 방법",
                ["전체", "ai", "keyword", "legal", "fallback"],
                help="fallback/ai 는 오분류 가능성이 높습니다",
                key="mc_method"
            )
        with col2:
            filter_part = st.selectbox(
                "현재 파트",
                ["전체", "안전계획", "안전보건", "재난안전", "미분류"],
                key="mc_part"
            )
        with col3:
            search_kw = st.text_input(
                "제목 검색",
                placeholder="예: 핸드리프트, MSDS...",
                key="mc_search"
            )

    # 필터 적용
    df_view = df.copy()
    if filter_method != "전체" and "ai_method" in df_view.columns:
        df_view = df_view[df_view["ai_method"] == filter_method]
    if filter_part != "전체":
        df_view = df_view[df_view["ai_part"] == filter_part]
    if search_kw.strip() and "title" in df_view.columns:
        df_view = df_view[df_view["title"].str.contains(search_kw.strip(), na=False)]

    st.caption(f"필터 결과: {len(df_view)}건")

    if df_view.empty:
        st.info("해당 조건의 건이 없습니다.")
        return

    # ── 수정 대상 선택
    col_a, col_b = st.columns([3, 1])
    with col_a:
        # 제목 + 현재 파트로 선택지 구성
        options = [
            f"[{row.get('ai_part','?')}] {row.get('title','')[:40]} "
            f"({row.get('department','')})"
            for _, row in df_view.head(50).iterrows()
        ]
        selected_option = st.selectbox(
            "수정할 지적사항 선택",
            options=options,
            key="mc_select"
        )

    selected_idx = df_view.head(50).index[options.index(selected_option)]
    selected_row = df.loc[selected_idx]

    # ── 선택된 건 상세 표시
    with st.container():
        st.markdown("**선택된 지적사항 상세:**")
        col1, col2, col3 = st.columns(3)
        col1.write(f"**부서:** {selected_row.get('department', '-')}")
        col2.write(f"**심사구분:** {selected_row.get('audit_type', '-')}")
        col3.write(f"**분류방법:** {selected_row.get('ai_method', '-')}")

        st.write(f"**제목:** {selected_row.get('title', '')}")

        problem = selected_row.get('problem', '')
        if problem and problem != "내용 없음":
            st.write(f"**문제점:** {problem[:200]}")

        # 현재 분류 결과
        current_part = selected_row.get("ai_part", "미분류")
        current_risk = selected_row.get("ai_risk", "중")
        current_reason = selected_row.get("ai_reason", "")

        col_p, col_r = st.columns(2)
        col_p.info(f"현재 파트: **{current_part}**")
        col_r.info(f"현재 리스크: **{current_risk}**")
        if current_reason:
            st.caption(f"분류이유: {current_reason}")

    st.markdown("")

    # ── 법령DB 조회 버튼
    if st.button("⚖️ 법령DB 조회 (참고용)",
                 use_container_width=True, key="mc_legal_check"):
        try:
            from data.legal_store import search_legal
            query   = f"{selected_row.get('title','')} {selected_row.get('problem','')}"
            results = search_legal(query, top_k=3)
            if results:
                st.markdown("**관련 법령 검색 결과:**")
                for i, r in enumerate(results, 1):
                    meta = r.get("metadata", {})
                    sim  = r.get("similarity", 0)
                    st.write(
                        f"{i}. **{meta.get('file_stem','')}** "
                        f"({meta.get('category_ko','')}) — 유사도 {sim:.0%}"
                    )
                    st.caption(r.get("text", "")[:150] + "...")
            else:
                st.info("관련 법령을 찾을 수 없습니다.")
        except Exception as e:
            st.error(f"법령 검색 오류: {e}")

    st.markdown("")

    # ── 수정 입력
    st.markdown("**✏️ 파트 및 리스크 수정:**")
    col1, col2 = st.columns(2)
    with col1:
        new_part = st.selectbox(
            "수정할 파트",
            ["안전계획", "안전보건", "재난안전"],
            index=["안전계획","안전보건","재난안전"].index(current_part)
                  if current_part in ["안전계획","안전보건","재난안전"] else 0,
            key="mc_new_part"
        )
    with col2:
        new_risk = st.selectbox(
            "수정할 리스크",
            ["상", "중", "하"],
            index=["상","중","하"].index(current_risk)
                  if current_risk in ["상","중","하"] else 1,
            key="mc_new_risk"
        )

    new_reason = st.text_input(
        "수정 이유 (선택)",
        placeholder="예: 산업안전보건기준에 관한 규칙 제133조 — 수동 보정",
        key="mc_reason"
    )

    # ── 저장 버튼
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 수정 저장", type="primary",
                     use_container_width=True, key="mc_save"):
            # 변경사항 없으면 알림
            if new_part == current_part and new_risk == current_risk:
                st.warning("변경된 내용이 없습니다.")
            else:
                reason_text = (
                    new_reason if new_reason.strip()
                    else f"수동 보정: {current_part} → {new_part}"
                )
                df.loc[selected_idx, "ai_part"]       = new_part
                df.loc[selected_idx, "ai_risk"]       = new_risk
                df.loc[selected_idx, "ai_reason"]     = reason_text
                df.loc[selected_idx, "ai_method"]     = "manual"
                df.loc[selected_idx, "ai_confidence"] = "manual"
                df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                st.success(
                    f"✅ 수정 완료!\n"
                    f"{current_part} → **{new_part}**  |  "
                    f"리스크: {current_risk} → **{new_risk}**"
                )
                st.rerun()

    with col_cancel:
        if st.button("↩️ 취소", use_container_width=True, key="mc_cancel"):
            st.rerun()

    # ── 수동 보정 이력
    st.markdown("---")
    if "ai_method" in df.columns:
        manual_df = df[df["ai_method"] == "manual"]
        if not manual_df.empty:
            with st.expander(f"📋 수동 보정 이력 ({len(manual_df)}건)", expanded=False):
                disp_cols = ["title","department","ai_part","ai_risk","ai_reason"]
                avail     = [c for c in disp_cols if c in manual_df.columns]
                col_map   = {
                    "title":"제목","department":"부서",
                    "ai_part":"파트","ai_risk":"리스크","ai_reason":"보정이유"
                }
                d = manual_df[avail].copy()
                d.columns = [col_map.get(c,c) for c in avail]
                st.dataframe(d, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────
# AI 분류 실행
# ─────────────────────────────────────────
def _run_classification(df: pd.DataFrame, csv_path: Path):
    progress_bar = st.progress(0)
    status_text  = st.empty()
    current_item = st.empty()
    start_time   = time.time()

    def update_progress(current, total, title):
        progress  = current / total
        elapsed   = time.time() - start_time
        remaining = (elapsed / current) * (total - current) if current > 0 else 0
        progress_bar.progress(progress)
        status_text.text(
            f"진행: {current}/{total}건 ({progress*100:.1f}%) | "
            f"남은 시간: 약 {int(remaining//60)}분 {int(remaining%60)}초"
        )
        current_item.caption(f"현재 처리 중: {title}")

    df_result = run_full_classification(df, update_progress)
    df_result.to_csv(csv_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - start_time

    # 분류 방법별 통계 출력
    if "ai_method" in df_result.columns:
        method_counts = df_result["ai_method"].value_counts()
        st.info(
            "분류 방법별 결과: "
            + "  |  ".join(f"{m}: {c}건" for m, c in method_counts.items())
        )

    st.success(
        f"🎉 분류 완료! {len(df_result):,}건 처리 "
        f"(소요 시간: {int(elapsed//60)}분 {int(elapsed%60)}초)"
    )
    st.balloons()
    st.rerun()


# ─────────────────────────────────────────
# 미분류만 재분류
# ─────────────────────────────────────────
def _run_reclassification(df, df_unc, csv_path):
    progress_bar = st.progress(0)
    status_text  = st.empty()
    current_item = st.empty()
    start_time   = time.time()

    def update_progress(current, total, title):
        progress  = current / total
        elapsed   = time.time() - start_time
        remaining = (elapsed / current) * (total - current) if current > 0 else 0
        progress_bar.progress(progress)
        status_text.text(
            f"재분류 진행: {current}/{total}건 ({progress*100:.1f}%) | "
            f"남은 시간: 약 {int(remaining//60)}분 {int(remaining%60)}초"
        )
        current_item.caption(f"현재 처리 중: {title}")

    df_result = run_full_classification(
        df_unc.reset_index(drop=True), update_progress
    )

    for i, orig_idx in enumerate(df_unc.index):
        df.loc[orig_idx, "ai_part"]       = df_result.iloc[i]["ai_part"]
        df.loc[orig_idx, "ai_risk"]       = df_result.iloc[i]["ai_risk"]
        df.loc[orig_idx, "ai_reason"]     = df_result.iloc[i]["ai_reason"]
        df.loc[orig_idx, "ai_confidence"] = df_result.iloc[i]["ai_confidence"]
        df.loc[orig_idx, "ai_method"]     = df_result.iloc[i]["ai_method"]

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    elapsed = time.time() - start_time
    st.success(
        f"🎉 재분류 완료! {len(df_unc)}건 처리 "
        f"(소요 시간: {int(elapsed//60)}분 {int(elapsed%60)}초)"
    )
    st.balloons()
    st.rerun()