# pages/page_classify.py
# AI 분류 실행 화면 + 벡터DB 초기화 + 미분류 재분류 기능

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
    st.markdown("llama3.1:8b 모델이 지적사항을 3개 파트로 자동 분류합니다.")
    st.markdown("---")

    # 데이터 로드 확인
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.error("❌ 데이터가 없습니다. [데이터 업로드] 메뉴에서 먼저 업로드하세요.")
        return

    df = pd.read_csv(csv_path, dtype=str)
    rag_status = get_vector_store_status()

    # 현재 상태 KPI
    _render_status(df, rag_status)
    st.markdown("---")

    # Step 1: 벡터DB 관리
    _render_vector_db_section(df, rag_status)
    st.markdown("---")

    # Step 2: AI 분류 실행
    _render_classify_section(df, csv_path, rag_status)
    st.markdown("---")

    # 분류 결과 미리보기
    if "ai_part" in df.columns:
        _render_result_preview(df)
        st.markdown("---")

        # Step 3: 미분류 재분류
        _render_reclassify_section(df, csv_path)


# ─────────────────────────────────────────
# 현재 상태 KPI
# ─────────────────────────────────────────
def _render_status(df: pd.DataFrame, rag_status: dict):
    st.subheader("📌 현재 상태")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("📋 총 지적사항", f"{len(df):,}건")

    with col2:
        if rag_status["ready"]:
            st.metric("🗄️ 벡터DB", f"{rag_status['total']:,}건 ✅")
        else:
            st.metric("🗄️ 벡터DB", "미구축 ⚠️")

    with col3:
        if "ai_part" in df.columns:
            classified = df["ai_part"].notna().sum()
            st.metric("🤖 분류 완료", f"{classified:,}건")
        else:
            st.metric("🤖 분류 완료", "0건")

    with col4:
        if "ai_part" in df.columns and len(df) > 0:
            classified = df["ai_part"].notna().sum()
            pct = classified / len(df) * 100
            st.metric("📊 분류율", f"{pct:.1f}%")
        else:
            st.metric("📊 분류율", "0%")


# ─────────────────────────────────────────
# Step 1: 벡터DB 관리 섹션
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
        if st.button(
            "🔧 벡터DB 구축",
            type="primary" if not rag_status["ready"] else "secondary",
            use_container_width=True,
            disabled=rag_status["ready"],
            key="btn_build"
        ):
            with st.spinner("벡터DB 구축 중... (수 분 소요)"):
                success = initialize_rag(df)
                if success:
                    st.success("✅ 벡터DB 구축 완료!")
                    st.rerun()
                else:
                    st.error("❌ 구축 실패. 로그를 확인하세요.")

    with col2:
        if st.button(
            "🔄 벡터DB 재구축",
            use_container_width=True,
            disabled=not rag_status["ready"],
            key="btn_rebuild"
        ):
            with st.spinner("재구축 중..."):
                success = initialize_rag(df)
                if success:
                    st.success("✅ 재구축 완료!")
                    st.rerun()
                else:
                    st.error("❌ 재구축 실패.")

    with col3:
        if st.button(
            "🗑️ 벡터DB 초기화",
            type="secondary",
            use_container_width=True,
            key="btn_reset"
        ):
            st.session_state["confirm_reset"] = True

    if st.session_state.get("confirm_reset", False):
        _render_reset_confirm()


# ─────────────────────────────────────────
# 벡터DB 초기화 확인
# ─────────────────────────────────────────
def _render_reset_confirm():
    st.warning("⚠️ 정말로 벡터DB를 초기화하시겠습니까? 이 작업은 되돌릴 수 없습니다.")
    col_yes, col_no = st.columns(2)

    with col_yes:
        if st.button(
            "✅ 예, 초기화합니다",
            type="primary",
            use_container_width=True,
            key="btn_confirm_yes"
        ):
            _reset_vector_db()

    with col_no:
        if st.button(
            "❌ 취소",
            use_container_width=True,
            key="btn_confirm_no"
        ):
            st.session_state["confirm_reset"] = False
            st.rerun()


# ─────────────────────────────────────────
# 벡터DB 초기화 실행
# ─────────────────────────────────────────
def _reset_vector_db():
    try:
        if VECTOR_DB_DIR.exists():
            shutil.rmtree(VECTOR_DB_DIR)
            VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
        st.session_state["confirm_reset"] = False
        st.success("✅ 벡터DB 초기화 완료!")
        st.caption("벡터DB가 삭제되었습니다. 벡터DB 구축을 다시 실행하세요.")
        st.rerun()
    except Exception as e:
        st.error(f"❌ 초기화 실패: {e}")


# ─────────────────────────────────────────
# Step 2: AI 분류 실행 섹션
# ─────────────────────────────────────────
def _render_classify_section(
    df: pd.DataFrame,
    csv_path: Path,
    rag_status: dict
):
    st.subheader("Step 2️⃣  AI 분류 실행")
    st.caption("llama3.1:8b가 각 지적사항을 안전계획/안전보건/재난안전으로 분류합니다.")

    estimated = len(df) * 15
    minutes   = estimated // 60
    st.info(
        f"⏱️ 예상 소요 시간: 약 {minutes}분 "
        f"({len(df):,}건 × 평균 15초/건)"
    )

    if not rag_status["ready"]:
        st.error("❌ 벡터DB를 먼저 구축하세요. (Step 1)")

    if st.button(
        "🚀 AI 분류 시작",
        type="primary",
        use_container_width=True,
        disabled=not rag_status["ready"],
        key="btn_classify"
    ):
        _run_classification(df, csv_path)


# ─────────────────────────────────────────
# 분류 결과 미리보기
# ─────────────────────────────────────────
def _render_result_preview(df: pd.DataFrame):
    st.subheader("📋 분류 결과 미리보기")

    part_counts = df["ai_part"].value_counts()
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("🚇 안전계획", f"{part_counts.get('안전계획', 0)}건")
    with col2:
        st.metric("🏥 안전보건", f"{part_counts.get('안전보건', 0)}건")
    with col3:
        st.metric("🌪️ 재난안전", f"{part_counts.get('재난안전', 0)}건")
    with col4:
        cnt = part_counts.get("미분류", 0)
        if cnt > 0:
            st.metric("❓ 미분류", f"{cnt}건", delta="재분류 필요", delta_color="inverse")
        else:
            st.metric("✅ 미분류", "0건")

    preview_cols = ["year", "audit_type", "title", "ai_part", "ai_risk", "ai_reason"]
    available   = [c for c in preview_cols if c in df.columns]
    col_labels  = {
        "year": "연도", "audit_type": "심사구분",
        "title": "제목", "ai_part": "AI분류",
        "ai_risk": "리스크", "ai_reason": "분류이유"
    }
    display = df[available].head(20).copy()
    display.columns = [col_labels.get(c, c) for c in available]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────
# Step 3: 미분류 재분류 섹션
# ─────────────────────────────────────────
def _render_reclassify_section(df: pd.DataFrame, csv_path: Path):
    st.subheader("Step 3️⃣  미분류 항목 재분류")

    # 미분류 건 추출
    df_unclassified = df[df["ai_part"] == "미분류"].copy()
    unclassified_cnt = len(df_unclassified)

    # 미분류 없으면 성공 표시 후 종료
    if unclassified_cnt == 0:
        st.success("✅ 미분류 항목이 없습니다! 모든 항목이 분류되었습니다.")
        return

    # 미분류 항목 경고 및 안내
    st.warning(
        f"⚠️ 미분류 항목 {unclassified_cnt}건이 있습니다. "
        f"keywords.py 업데이트 후 재분류를 실행하세요."
    )
    st.caption(
        "💡 config/keywords.py 의 STRONG_INDICATORS에 "
        "관련 키워드를 추가하면 정확도가 높아집니다."
    )

    # 미분류 목록 표시
    show_cols  = ["title", "department", "audit_type", "ai_reason"]
    avail_cols = [c for c in show_cols if c in df_unclassified.columns]
    col_map    = {
        "title":      "제목",
        "department": "담당부서",
        "audit_type": "심사구분",
        "ai_reason":  "분류이유"
    }
    display_df = df_unclassified[avail_cols].copy()
    display_df.columns = [col_map.get(c, c) for c in avail_cols]

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # 예상 소요 시간
    est_sec = unclassified_cnt * 15
    est_min = est_sec // 60
    est_rem = est_sec % 60

    st.info(
        f"⏱️ 예상 소요 시간: 약 {est_min}분 {est_rem}초 "
        f"({unclassified_cnt}건 × 평균 15초/건)"
    )

    if st.button(
        f"🔄 미분류 {unclassified_cnt}건 재분류",
        type="primary",
        use_container_width=True,
        key="btn_reclassify"
    ):
        _run_reclassification(df, df_unclassified, csv_path)


# ─────────────────────────────────────────
# AI 분류 실행 + 진행률 표시
# ─────────────────────────────────────────
def _run_classification(df: pd.DataFrame, csv_path: Path):
    progress_bar = st.progress(0)
    status_text  = st.empty()
    current_item = st.empty()
    start_time   = time.time()

    def update_progress(current, total, title):
        progress  = current / total
        elapsed   = time.time() - start_time
        remaining = (
            (elapsed / current) * (total - current)
            if current > 0 else 0
        )
        progress_bar.progress(progress)
        status_text.text(
            f"진행: {current}/{total}건 "
            f"({progress*100:.1f}%) | "
            f"남은 시간: 약 {int(remaining//60)}분 {int(remaining%60)}초"
        )
        current_item.caption(f"현재 처리 중: {title}")

    df_result = run_full_classification(df, update_progress)
    df_result.to_csv(csv_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - start_time
    st.success(
        f"🎉 분류 완료! {len(df_result):,}건 처리 "
        f"(소요 시간: {int(elapsed//60)}분 {int(elapsed%60)}초)"
    )
    st.balloons()
    st.rerun()


# ─────────────────────────────────────────
# 미분류 항목만 재분류
# ─────────────────────────────────────────
def _run_reclassification(
    df: pd.DataFrame,
    df_unclassified: pd.DataFrame,
    csv_path: Path
):
    progress_bar = st.progress(0)
    status_text  = st.empty()
    current_item = st.empty()
    start_time   = time.time()
    total        = len(df_unclassified)

    def update_progress(current, total, title):
        progress  = current / total
        elapsed   = time.time() - start_time
        remaining = (
            (elapsed / current) * (total - current)
            if current > 0 else 0
        )
        progress_bar.progress(progress)
        status_text.text(
            f"재분류 진행: {current}/{total}건 "
            f"({progress*100:.1f}%) | "
            f"남은 시간: 약 {int(remaining//60)}분 {int(remaining%60)}초"
        )
        current_item.caption(f"현재 처리 중: {title}")

    # 미분류 건만 재분류
    df_result = run_full_classification(
        df_unclassified.reset_index(drop=True),
        update_progress
    )

    # 원본 df에서 미분류 행 업데이트
    unclassified_indices = list(df_unclassified.index)
    for i, orig_idx in enumerate(unclassified_indices):
        df.loc[orig_idx, "ai_part"]       = df_result.iloc[i]["ai_part"]
        df.loc[orig_idx, "ai_risk"]       = df_result.iloc[i]["ai_risk"]
        df.loc[orig_idx, "ai_reason"]     = df_result.iloc[i]["ai_reason"]
        df.loc[orig_idx, "ai_confidence"] = df_result.iloc[i]["ai_confidence"]
        df.loc[orig_idx, "ai_method"]     = df_result.iloc[i]["ai_method"]

    # 전체 저장
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - start_time
    st.success(
        f"🎉 재분류 완료! {total}건 처리 "
        f"(소요 시간: {int(elapsed//60)}분 {int(elapsed%60)}초)"
    )
    st.balloons()
    st.rerun()