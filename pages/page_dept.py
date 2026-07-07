# pages/page_dept.py
# 🏢 부서별 심사 조회
# 부서 선택 → 전체 지적사항 필터링 + 일목요연 표시

import io
import logging
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import PROCESSED_DIR
from data.vector_store import search_similar
from data.legal_store import get_legal_store_status
from core.legal_engine import find_legal_basis
from core.action_analyzer import add_action_status, action_summary

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("🏢 부서별 심사 조회")
    st.markdown("부서를 선택하면 해당 부서의 전체 지적사항을 필터링하여 표시합니다.")
    st.markdown("---")

    # 데이터 로드
    df = _load_data()
    if df is None:
        st.error("❌ 데이터가 없습니다. [데이터 업로드] 메뉴에서 먼저 업로드하세요.")
        return

    # 부서 목록 추출
    departments = _get_departments(df)
    if not departments:
        st.warning("⚠️ 부서 데이터가 없습니다.")
        return

    # ── 필터 영역
    _render_filters(df, departments)


# ─────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────
def _load_data() -> pd.DataFrame | None:
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path, dtype=str)
    # year 숫자 변환
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    # 조치 이행상태 판정 컬럼 추가 (규칙 기반 — 즉시 처리)
    df = add_action_status(df)
    return df


# ─────────────────────────────────────────
# 부서 목록 추출 (지적 건수 많은 순)
# ─────────────────────────────────────────
def _get_departments(df: pd.DataFrame) -> list[str]:
    if "department" not in df.columns:
        return []
    counts = df["department"].value_counts()
    return [
        d for d in counts.index
        if d and d not in ("미기재", "nan", "")
    ]


# ─────────────────────────────────────────
# 필터 영역
# ─────────────────────────────────────────
def _render_filters(df: pd.DataFrame, departments: list[str]):

    # ── 필터 행
    col1, col2, col3, col4, col5 = st.columns([2.5, 1.5, 1.5, 1.5, 1.5])

    with col1:
        selected_dept = st.selectbox(
            "🏢 부서 선택",
            options=departments,
            key="dept_select"
        )
    with col2:
        audit_options = ["전체"] + sorted(
            df["audit_type"].dropna().unique().tolist()
        ) if "audit_type" in df.columns else ["전체"]
        selected_audit = st.selectbox(
            "심사구분",
            options=audit_options,
            key="audit_select"
        )
    with col3:
        part_options = ["전체", "안전계획", "안전보건", "재난안전"]
        selected_part = st.selectbox(
            "파트",
            options=part_options,
            key="part_select"
        )
    with col4:
        year_list = sorted(
            df["year"].dropna().unique().tolist(), reverse=True
        ) if "year" in df.columns else []
        year_options = ["전체"] + [str(int(y)) for y in year_list if y > 0]
        selected_year = st.selectbox(
            "연도",
            options=year_options,
            key="year_select"
        )
    with col5:
        repeat_only = st.selectbox(
            "반복 지적",
            options=["전체", "반복만 보기"],
            key="repeat_select"
        )

    # ── 데이터 필터링
    df_filtered = _filter_data(
        df, selected_dept, selected_audit,
        selected_part, selected_year, repeat_only
    )

    # ── 반복 횟수 컬럼 추가
    df_filtered = _add_repeat_count(df, df_filtered)

    st.markdown("---")

    # ── KPI
    _render_kpi(df_filtered, selected_dept)

    # ── 경고 배너
    _render_warning(df_filtered)

    # ── 메인 테이블
    _render_main_table(df_filtered)

    # ── 하단 액션 버튼
    _render_actions(df_filtered, selected_dept)


# ─────────────────────────────────────────
# 데이터 필터링
# ─────────────────────────────────────────
def _filter_data(
    df: pd.DataFrame,
    dept:   str,
    audit:  str,
    part:   str,
    year:   str,
    repeat: str,
) -> pd.DataFrame:

    result = df[df["department"] == dept].copy()

    if audit != "전체" and "audit_type" in result.columns:
        result = result[result["audit_type"] == audit]

    if part != "전체" and "ai_part" in result.columns:
        result = result[result["ai_part"] == part]

    if year != "전체" and "year" in result.columns:
        result = result[result["year"] == int(year)]

    if repeat == "반복만 보기" and "title" in result.columns:
        title_counts = df[df["department"] == dept]["title"].value_counts()
        repeat_titles = title_counts[title_counts >= 2].index
        result = result[result["title"].isin(repeat_titles)]

    return result.reset_index(drop=True)


# ─────────────────────────────────────────
# 반복 횟수 컬럼 추가
# ─────────────────────────────────────────
def _add_repeat_count(
    df_all: pd.DataFrame,
    df_filtered: pd.DataFrame
) -> pd.DataFrame:
    """전체 데이터 기준으로 제목별 반복 횟수 계산"""
    if "title" not in df_all.columns:
        return df_filtered
    title_counts = df_all["title"].value_counts().to_dict()
    df_filtered = df_filtered.copy()
    df_filtered["repeat_count"] = df_filtered["title"].map(
        lambda t: title_counts.get(t, 1)
    )
    return df_filtered


# ─────────────────────────────────────────
# KPI 카드
# ─────────────────────────────────────────
def _render_kpi(df: pd.DataFrame, dept: str):
    st.subheader(f"📌 {dept} 심사 현황")

    total     = len(df)
    cmd_cnt   = len(df[df["audit_type"] == "시정명령"]) if "audit_type" in df.columns else 0
    high_risk = len(df[df["ai_risk"] == "상"]) if "ai_risk" in df.columns else 0
    repeat_cnt = len(df[df["repeat_count"] >= 2]) if "repeat_count" in df.columns else 0
    act = action_summary(df)   # 조치 이행실태 요약 (신규)

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric("📋 총 지적건수", f"{total}건")
    with col2:
        st.metric(
            "🔴 시정명령", f"{cmd_cnt}건",
            delta="즉시 조치" if cmd_cnt > 0 else None,
            delta_color="inverse" if cmd_cnt > 0 else "off"
        )
    with col3:
        st.metric("🟡 개선권고",
            f"{len(df[df['audit_type']=='개선권고'])}건"
            if "audit_type" in df.columns else "0건"
        )
    with col4:
        st.metric(
            "⚠️ 리스크 상", f"{high_risk}건",
            delta="집중 관리" if high_risk > 0 else None,
            delta_color="inverse" if high_risk > 0 else "off"
        )
    with col5:
        st.metric("🔁 반복 지적", f"{repeat_cnt}건")
    with col6:
        # 이행률 (신규) — 완료 ÷ 전체, 형식적 완료는 미포함
        미흡건 = act["형식적"] + act["미확인"]
        st.metric(
            "✅ 조치 이행률", f"{act['이행률']}%",
            delta=f"형식적/미확인 {미흡건}건" if 미흡건 > 0 else None,
            delta_color="inverse" if 미흡건 > 0 else "off"
        )

    # 파트별 분포 (작은 차트 대신 간단한 수평 게이지)
    if "ai_part" in df.columns and total > 0:
        st.markdown("**파트별 분포**")
        for part in ["안전계획", "안전보건", "재난안전"]:
            cnt = len(df[df["ai_part"] == part])
            pct = cnt / total * 100 if total > 0 else 0
            icon = {"안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"}.get(part, "")
            col_a, col_b, col_c = st.columns([2, 6, 1])
            col_a.write(f"{icon} {part}")
            col_b.progress(pct / 100)
            col_c.write(f"{cnt}건")


# ─────────────────────────────────────────
# 경고 배너
# ─────────────────────────────────────────
def _render_warning(df: pd.DataFrame):
    if "repeat_count" not in df.columns:
        return

    high_repeat = df[df["repeat_count"] >= 3]
    if not high_repeat.empty:
        titles = high_repeat["title"].unique()
        st.warning(
            f"⚠️ **반복 3회 이상 지적사항 {len(titles)}건** — "
            f"구조적 문제 가능성. 집중 심사 필요!\n\n"
            + "\n".join(f"• {t}" for t in titles[:5])
        )

    cmd_df = df[df["audit_type"] == "시정명령"] if "audit_type" in df.columns else pd.DataFrame()
    if not cmd_df.empty:
        st.error(
            f"🔴 **시정명령 {len(cmd_df)}건** — 법령 위반 사항. "
            f"심사 전 이행 여부 반드시 확인!"
        )


# ─────────────────────────────────────────
# 메인 테이블
# ─────────────────────────────────────────
def _render_main_table(df: pd.DataFrame):

    if df.empty:
        st.info("📭 해당 조건의 지적사항이 없습니다.")
        return

    st.subheader(f"📋 지적사항 목록 ({len(df)}건)")

    # 표시 컬럼 선택
    col_map = {
        "year":         "연도",
        "mgmt_no":      "관리번호",
        "audit_type":   "심사구분",
        "ai_part":      "파트",
        "title":        "지적사항",
        "problem":      "현황및문제점",
        "improvement":  "개선방안",
        "action_result":"추진실적",
        "ai_risk":      "리스크",
        "repeat_count": "반복횟수",
        "ai_reason":    "분류이유",
    }

    avail_cols = [c for c in col_map.keys() if c in df.columns]
    display_df = df[avail_cols].copy()
    display_df.columns = [col_map[c] for c in avail_cols]

    # 반복횟수 강조 표시
    def highlight_rows(row):
        styles = [""] * len(row)
        if "반복횟수" in row.index:
            cnt = row["반복횟수"]
            if isinstance(cnt, (int, float)):
                if cnt >= 3:
                    styles = ["background-color: #FFCDD2"] * len(row)
                elif cnt >= 2:
                    styles = ["background-color: #FFF9C4"] * len(row)
        if "심사구분" in row.index and row["심사구분"] == "시정명령":
            styles = ["background-color: #FFCDD2; font-weight: bold"] * len(row)
        return styles

    st.dataframe(
        display_df.style.apply(highlight_rows, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(400, 45 + len(display_df) * 38),
        column_config={
            "연도":       st.column_config.NumberColumn(width="small"),
            "관리번호":   st.column_config.TextColumn(width="small"),
            "심사구분":   st.column_config.TextColumn(width="small"),
            "파트":       st.column_config.TextColumn(width="small"),
            "지적사항":   st.column_config.TextColumn(width="large"),
            "현황및문제점": st.column_config.TextColumn(width="large"),
            "개선방안":   st.column_config.TextColumn(width="medium"),
            "추진실적":   st.column_config.TextColumn(width="medium"),
            "리스크":     st.column_config.TextColumn(width="small"),
            "반복횟수":   st.column_config.NumberColumn(width="small"),
            "분류이유":   st.column_config.TextColumn(width="medium"),
        }
    )

    # 범례
    st.caption(
        "🔴 빨간색: 시정명령 또는 3회 이상 반복   "
        "🟡 노란색: 2회 반복   "
        "⬜ 흰색: 일반"
    )

    # 엑셀 다운로드
    st.markdown("---")
    _render_download(df, display_df)


# ─────────────────────────────────────────
# 엑셀 다운로드
# ─────────────────────────────────────────
def _render_download(df_orig: pd.DataFrame, display_df: pd.DataFrame):
    col1, col2 = st.columns([3, 1])

    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            display_df.to_excel(
                writer,
                index=False,
                sheet_name="심사대상목록"
            )
        buffer.seek(0)

        dept = st.session_state.get("dept_select", "부서")
        st.download_button(
            label="📥 엑셀 다운로드",
            data=buffer.read(),
            file_name=f"{dept}_심사대상목록.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )


# ─────────────────────────────────────────
# 하단 액션 버튼
# ─────────────────────────────────────────
def _render_actions(df: pd.DataFrame, dept: str):
    st.markdown("---")
    st.subheader("🔧 추가 기능")

    tab1, tab2, tab3 = st.tabs([
        "🔍 유사 사례 검색",
        "⚖️ 법령 근거 조회",
        "📝 심사 체크포인트"
    ])

    # ── Tab 1: 유사사례 검색
    with tab1:
        st.caption("선택한 지적사항과 유사한 과거 사례를 검색합니다.")

        if df.empty:
            st.info("지적사항이 없습니다.")
        else:
            titles = df["title"].unique().tolist() if "title" in df.columns else []
            selected_title = st.selectbox(
                "지적사항 선택",
                options=titles,
                key="similar_title_select"
            )

            if st.button(
                "🔍 유사 사례 검색",
                use_container_width=True,
                key="btn_similar"
            ):
                with st.spinner("유사 사례 검색 중..."):
                    results = search_similar(selected_title, top_k=5)

                if not results:
                    st.info("유사 사례를 찾을 수 없습니다.")
                else:
                    for i, case in enumerate(results, 1):
                        meta = case.get("metadata", {})
                        sim  = case.get("similarity", 0)
                        with st.expander(
                            f"{i}. {meta.get('title', '')} "
                            f"({meta.get('department', '')} / "
                            f"{meta.get('ai_part', '')}) "
                            f"— 유사도 {sim:.0%}",
                            expanded=(i == 1)
                        ):
                            col1, col2, col3 = st.columns(3)
                            col1.write(f"**연도:** {meta.get('year', '-')}")
                            col2.write(f"**심사구분:** {meta.get('audit_type', '-')}")
                            col3.write(f"**리스크:** {meta.get('ai_risk', '-')}")
                            st.write(case.get("text", "")[:300])

    # ── Tab 2: 법령 근거
    with tab2:
        legal_status = get_legal_store_status()

        if not legal_status["ready"]:
            st.warning(
                "⚠️ 법령DB가 구축되지 않았습니다. "
                "[⚖️ 법령/규정 관리] 메뉴에서 먼저 구축하세요."
            )
        else:
            if df.empty:
                st.info("지적사항이 없습니다.")
            else:
                titles = df["title"].unique().tolist() if "title" in df.columns else []
                sel_title = st.selectbox(
                    "근거 조회할 지적사항",
                    options=titles,
                    key="legal_title_select"
                )

                # 선택한 지적사항의 문제점 자동 로드
                sel_row = df[df["title"] == sel_title]
                problem = ""
                if not sel_row.empty and "problem" in sel_row.columns:
                    problem = str(sel_row.iloc[0]["problem"])
                    if problem in ("nan", "내용 없음"):
                        problem = ""

                audit_type = ""
                if not sel_row.empty and "audit_type" in sel_row.columns:
                    audit_type = str(sel_row.iloc[0]["audit_type"])

                if st.button(
                    "⚖️ 법령 근거 자동 생성",
                    type="primary",
                    use_container_width=True,
                    key="btn_legal_basis"
                ):
                    with st.spinner("관련 법령을 검색하고 근거를 생성 중..."):
                        result = find_legal_basis(
                            title=sel_title,
                            problem=problem,
                            audit_type=audit_type,
                            top_k=3
                        )

                    if result["found"]:
                        st.success("✅ 법령 근거 생성 완료!")
                        st.info(result["basis"])

                        if result["sources"]:
                            st.write("**참고 출처:**")
                            for src in result["sources"]:
                                st.write(f"• {src}")

                        # 복사용 텍스트
                        with st.expander("📋 복사용 텍스트"):
                            copy_text = (
                                f"【지적사항】{sel_title}\n\n"
                                f"【법령 근거】{result['basis']}\n\n"
                                f"【참고 문서】"
                                + ", ".join(result["sources"])
                            )
                            st.code(copy_text, language=None)
                    else:
                        st.warning("관련 법령/규정을 찾을 수 없습니다.")

    # ── Tab 3: 심사 체크포인트
    with tab3:
        st.caption(
            "이 부서의 과거 지적사항을 바탕으로 "
            "중점 심사 항목을 자동으로 제시합니다."
        )

        if df.empty:
            st.info("지적사항이 없습니다.")
            return

        # 반복 지적 상위 항목
        if "title" in df.columns:
            repeat_items = (
                df.groupby("title")
                .size()
                .sort_values(ascending=False)
                .head(10)
                .reset_index()
            )
            repeat_items.columns = ["지적사항", "건수"]

            st.markdown("**🔴 반드시 확인할 항목 (반복 지적 상위)**")
            for i, row in repeat_items.iterrows():
                cnt = row["건수"]
                icon = "🔴" if cnt >= 3 else "🟡" if cnt >= 2 else "🟢"
                checked = st.checkbox(
                    f"{icon} {row['지적사항']} ({cnt}회 지적)",
                    key=f"chk_{dept}_{i}"
                )

        # 시정명령 항목
        if "audit_type" in df.columns:
            cmd_items = df[df["audit_type"] == "시정명령"]
            if not cmd_items.empty:
                st.markdown("**⛔ 시정명령 이행 여부 확인 필수**")
                for i, row in cmd_items.iterrows():
                    st.checkbox(
                        f"시정명령: {row.get('title', '')} "
                        f"({row.get('year', '')}년)",
                        key=f"cmd_{dept}_{i}"
                    )

        # 결과 저장 버튼
        if st.button(
            "💾 체크 결과 저장",
            use_container_width=True,
            key="btn_save_check"
        ):
            st.success(
                f"✅ {dept} 심사 체크포인트 저장 완료!\n"
                f"현장 심사 도우미에서도 확인할 수 있습니다."
            )