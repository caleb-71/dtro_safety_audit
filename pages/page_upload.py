# pages/page_upload.py
# 데이터 업로드 + RAW 파일 관리 화면

import streamlit as st
import pandas as pd
from pathlib import Path
from data.loader import load_single_excel
from data.preprocessor import preprocess, save_processed
from config.settings import RAW_DIR, PROCESSED_DIR


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("📁 데이터 업로드")
    st.markdown("연도별 심사이력 엑셀 파일을 관리합니다.")
    st.markdown("---")

    # 섹션 1: RAW 파일 관리
    _render_raw_file_manager()
    st.markdown("---")

    # 섹션 2: 새 파일 업로드
    _render_file_uploader()
    st.markdown("---")

    # 섹션 3: 현재 데이터 현황
    _render_current_data()


# ─────────────────────────────────────────
# 섹션 1: RAW 파일 관리
# ─────────────────────────────────────────
def _render_raw_file_manager():
    st.subheader("📂 RAW 파일 관리")
    st.caption("data/raw/ 폴더에 저장된 파일 목록입니다.")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(RAW_DIR.glob("*.xlsx"), reverse=True)

    if not raw_files:
        st.info("📭 업로드된 파일이 없습니다. 아래에서 파일을 업로드하세요.")
        return

    # 파일 목록 테이블 헤더
    col_no, col_name, col_size, col_date, col_action = st.columns(
        [0.5, 4, 1.5, 2, 1.5]
    )
    col_no.markdown("**No.**")
    col_name.markdown("**파일명**")
    col_size.markdown("**크기**")
    col_date.markdown("**수정일**")
    col_action.markdown("**관리**")

    st.divider()

    # 파일 목록 출력
    for i, file_path in enumerate(raw_files, 1):
        col_no, col_name, col_size, col_date, col_action = st.columns(
            [0.5, 4, 1.5, 2, 1.5]
        )

        # 파일 크기
        size_kb = file_path.stat().st_size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"

        # 수정일
        import datetime
        mtime    = file_path.stat().st_mtime
        date_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

        col_no.write(f"{i}")
        col_name.write(f"📄 {file_path.name}")
        col_size.write(size_str)
        col_date.write(date_str)

        # 삭제 버튼 (고유 key 필수)
        if col_action.button(
            "🗑️ 삭제",
            key=f"del_{file_path.name}",
            use_container_width=True
        ):
            _delete_raw_file(file_path)

    st.divider()

    # 전체 삭제 버튼
    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button(
            "🗑️ 전체 삭제",
            type="secondary",
            use_container_width=True,
            key="delete_all"
        ):
            _delete_all_raw_files(raw_files)


# ─────────────────────────────────────────
# 섹션 2: 새 파일 업로드
# ─────────────────────────────────────────
def _render_file_uploader():
    st.subheader("📤 새 파일 업로드")
    st.info("💡 파일명에 연도(예: 2025)가 포함되면 자동으로 연도를 인식합니다.")

    uploaded_files = st.file_uploader(
        "엑셀 파일 선택 (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True,
        help="여러 연도 파일을 한번에 업로드 가능합니다",
        key="file_uploader"
    )

    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)}개 파일 선택됨")

        # 중복 파일 경고
        existing = [f.name for f in RAW_DIR.glob("*.xlsx")]
        duplicates = [f.name for f in uploaded_files if f.name in existing]
        if duplicates:
            st.warning(
                f"⚠️ 이미 존재하는 파일: {', '.join(duplicates)}\n"
                f"업로드 시 덮어씁니다."
            )

        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "💾 파일 저장만",
                use_container_width=True,
                key="save_only"
            ):
                _save_files_only(uploaded_files)

        with col2:
            if st.button(
                "🔄 저장 + 즉시 처리",
                type="primary",
                use_container_width=True,
                key="save_and_process"
            ):
                _save_and_process_files(uploaded_files)


# ─────────────────────────────────────────
# 섹션 3: 현재 데이터 현황
# ─────────────────────────────────────────
def _render_current_data():
    st.subheader("📊 현재 데이터 현황")

    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.warning("처리된 데이터가 없습니다. 파일 업로드 후 처리하세요.")

        # 전체 재처리 버튼 (raw 파일은 있지만 processed 없는 경우)
        raw_files = list(RAW_DIR.glob("*.xlsx"))
        if raw_files:
            st.info(f"RAW 파일 {len(raw_files)}개가 있습니다. 전체 재처리를 실행하세요.")
            if st.button(
                "🔄 전체 재처리",
                type="primary",
                use_container_width=True,
                key="reprocess_all"
            ):
                _reprocess_all()
        return

    df = pd.read_csv(csv_path, dtype=str)

    # KPI
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📋 총 건수", f"{len(df):,}건")
    with col2:
        if "year" in df.columns:
            years = sorted(df["year"].dropna().unique())
            year_range = f"{years[0]} ~ {years[-1]}" if len(years) > 1 else years[0]
            st.metric("📅 연도 범위", year_range)
    with col3:
        ai_done = "ai_part" in df.columns and df["ai_part"].notna().sum() > 0
        if ai_done:
            classified = df["ai_part"].notna().sum()
            pct = classified / len(df) * 100
            st.metric("🤖 AI 분류율", f"{pct:.1f}%")
        else:
            st.metric("🤖 AI 분류율", "미실행")

    # 연도별 건수
    if "year" in df.columns:
        year_df = (
            df["year"].value_counts()
            .sort_index()
            .reset_index()
            .rename(columns={"year": "연도", "count": "건수"})
        )
        st.dataframe(year_df, use_container_width=True, hide_index=True)

    st.divider()

    # 전체 재처리 버튼
    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button(
            "🔄 전체 재처리",
            use_container_width=True,
            key="reprocess_bottom"
        ):
            _reprocess_all()


# ─────────────────────────────────────────
# 파일 처리 함수들
# ─────────────────────────────────────────
def _save_files_only(uploaded_files):
    """파일 저장만 (처리 없이)"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    saved = []

    for uploaded_file in uploaded_files:
        save_path = RAW_DIR / uploaded_file.name
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        saved.append(uploaded_file.name)

    st.success(f"✅ {len(saved)}개 파일 저장 완료!")
    st.caption("벡터DB 재구축은 [AI 분류 실행] 메뉴에서 진행하세요.")
    st.rerun()


def _save_and_process_files(uploaded_files):
    """파일 저장 + 즉시 전처리"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    progress_bar = st.progress(0)
    status       = st.empty()
    all_dfs      = []

    for i, uploaded_file in enumerate(uploaded_files):
        status.text(f"처리 중: {uploaded_file.name}")

        save_path = RAW_DIR / uploaded_file.name
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        df = load_single_excel(save_path)
        if df is not None:
            df_clean = preprocess(df)
            all_dfs.append(df_clean)
            st.success(f"✅ {uploaded_file.name} — {len(df)}건 처리 완료")

        progress_bar.progress((i + 1) / len(uploaded_files))

    if all_dfs:
        # 기존 processed 데이터와 합치기
        combined = _merge_with_existing(all_dfs)
        save_processed(combined)
        st.balloons()
        st.success(f"🎉 전체 {len(combined)}건 처리 완료!")
        st.caption("⚠️ 새 데이터가 추가되었습니다. [AI 분류 실행] 메뉴에서 벡터DB를 재구축하세요.")
        st.rerun()


def _reprocess_all():
    """RAW 폴더 전체 파일 재처리"""
    raw_files = sorted(RAW_DIR.glob("*.xlsx"))

    if not raw_files:
        st.error("RAW 파일이 없습니다.")
        return

    progress_bar = st.progress(0)
    status       = st.empty()
    all_dfs      = []

    for i, file_path in enumerate(raw_files):
        status.text(f"처리 중: {file_path.name}")
        df = load_single_excel(file_path)
        if df is not None:
            df_clean = preprocess(df)
            all_dfs.append(df_clean)
            st.success(f"✅ {file_path.name} — {len(df)}건")
        progress_bar.progress((i + 1) / len(raw_files))

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        save_processed(combined)
        st.balloons()
        st.success(f"🎉 전체 {len(combined)}건 재처리 완료!")
        st.caption("⚠️ [AI 분류 실행] 메뉴에서 벡터DB를 재구축하세요.")
        st.rerun()


def _delete_raw_file(file_path: Path):
    """단일 RAW 파일 삭제"""
    try:
        file_path.unlink()
        st.success(f"✅ {file_path.name} 삭제 완료")
        st.caption("데이터 재처리가 필요할 수 있습니다.")
        st.rerun()
    except Exception as e:
        st.error(f"❌ 삭제 실패: {e}")


def _delete_all_raw_files(raw_files: list):
    """전체 RAW 파일 삭제"""
    deleted = 0
    for file_path in raw_files:
        try:
            file_path.unlink()
            deleted += 1
        except Exception as e:
            st.error(f"❌ {file_path.name} 삭제 실패: {e}")

    if deleted > 0:
        st.success(f"✅ {deleted}개 파일 전체 삭제 완료")
        st.rerun()


def _merge_with_existing(new_dfs: list) -> pd.DataFrame:
    """
    새 데이터를 기존 processed 데이터와 합치기
    같은 파일 소스는 새 데이터로 교체
    """
    csv_path = PROCESSED_DIR / "processed_data.csv"
    new_combined = pd.concat(new_dfs, ignore_index=True)

    if not csv_path.exists():
        return new_combined

    existing = pd.read_csv(csv_path, dtype=str)

    # source_file 기준으로 중복 제거
    if "source_file" in new_combined.columns and \
       "source_file" in existing.columns:
        new_sources = new_combined["source_file"].unique().tolist()
        existing_filtered = existing[
            ~existing["source_file"].isin(new_sources)
        ]
        result = pd.concat(
            [existing_filtered, new_combined],
            ignore_index=True
        )
        return result

    # source_file 없으면 연도 기준
    if "year" in new_combined.columns and "year" in existing.columns:
        new_years = new_combined["year"].dropna().unique().tolist()
        existing_filtered = existing[
            ~existing["year"].isin(new_years)
        ]
        return pd.concat(
            [existing_filtered, new_combined],
            ignore_index=True
        )

    return new_combined