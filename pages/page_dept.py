# pages/page_dept.py
# 🏢 부서별 심사 조회
#
# [반복 지적 판정 기준 — 2가지 방식이 연동됨]
#
#   ① 제목 일치 (기본)
#      제목 문자열을 공백 제거 후 비교. 즉시 계산되나
#      "기계기구 안전관리 미흡" / "기계기구 안전관리 미흡 - [개선명령]" 처럼
#      표현이 다르면 별개로 집계되는 한계가 있음
#
#   ② AI 판정 (🔎 AI 중복지적 분석 탭에서 실행)
#      제목과 현황및문제점을 함께 임베딩하고, 경계 구간은 LLM이 문맥 판정.
#      실행하면 그 결과가 이 화면의 KPI·경고·표 강조·프로파일 카드에
#      자동으로 반영되어 두 기준이 어긋나지 않도록 설계함
#
#   AI 분석을 실행하지 않았거나 분석 범위 밖의 부서는 ①로 자동 대체됨

import io
import logging
from datetime import datetime

import pandas as pd
import streamlit as st

from config.settings import PROCESSED_DIR
from data.vector_store import search_similar
from data.legal_store import get_legal_store_status
from core.legal_engine import find_legal_basis
from core.action_analyzer import add_action_status, action_summary
from core.duplicate_detector import detect_duplicates, duplicate_summary_by_dept

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("🏢 부서별 심사 조회")
    st.markdown("부서를 선택하면 해당 부서의 전체 지적사항을 필터링하여 표시합니다.")
    st.markdown("---")

    df = _load_data()
    if df is None:
        st.error("❌ 데이터가 없습니다. [데이터 업로드] 메뉴에서 먼저 업로드하세요.")
        return

    # AI 중복지적 분석 결과가 있으면 반영 (없으면 제목일치 기준 유지)
    df = _apply_ai_duplicates(df)

    departments = _get_departments(df)
    if not departments:
        st.warning("⚠️ 부서 데이터가 없습니다.")
        return

    # 현재 적용 중인 판정 기준 안내
    _render_basis_banner(df)

    # 전 부서 프로파일 카드 일괄 생성
    _render_profile_export(df, departments)

    st.markdown("---")

    _render_filters(df, departments)


# ─────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────
def _load_data() -> pd.DataFrame | None:
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        return None

    df = pd.read_csv(csv_path, dtype=str)

    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)

    # 행 고유 ID — AI 분석 결과를 원본 행과 매칭하기 위한 키
    # (CSV 읽는 순서가 항상 같으므로 안정적으로 유지됨)
    df = df.reset_index(drop=True)
    df["_row_id"] = df.index

    # 조치 이행상태 판정 컬럼 (규칙 기반)
    df = add_action_status(df)

    # 반복 횟수 컬럼 (제목 일치 기준)
    df = _add_repeat_columns(df)

    return df


# ─────────────────────────────────────────
# 부서 목록 추출 (지적 건수 많은 순)
# ─────────────────────────────────────────
def _get_departments(df: pd.DataFrame) -> list[str]:
    if "department" not in df.columns:
        return []
    counts = df["department"].value_counts()
    return [d for d in counts.index if d and d not in ("미기재", "nan", "")]


# ─────────────────────────────────────────
# 반복 횟수 (제목 일치 기준) — 기본값
# ─────────────────────────────────────────
def _norm_title(t) -> str:
    """제목 정규화 — 띄어쓰기만 다른 동일 지적을 같은 항목으로 묶음"""
    return str(t).replace(" ", "").strip()


def _add_repeat_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    반복 횟수를 두 가지 기준으로 계산한다.

    repeat_dept : 같은 부서에서 동일 제목이 몇 번 나왔는가
                  → 반복 지적 (중복지적 감점 대상)
    repeat_all  : 전 부서를 통틀어 동일 제목이 몇 번 나왔는가
    dept_span   : 그 제목이 몇 개 부서에서 나왔는가
                  → 2개 부서 이상이면 전사 공통취약 항목 후보
    """
    if "title" not in df.columns:
        return df

    df = df.copy()
    df["_key"] = df["title"].apply(_norm_title)

    all_counts = df["_key"].value_counts().to_dict()
    df["repeat_all"] = df["_key"].map(lambda k: all_counts.get(k, 1))

    if "department" in df.columns:
        span = df.groupby("_key")["department"].nunique().to_dict()
        df["dept_span"] = df["_key"].map(lambda k: span.get(k, 1))

        dept_counts = df.groupby(["department", "_key"]).size().to_dict()
        df["repeat_dept"] = df.apply(
            lambda r: dept_counts.get((r["department"], r["_key"]), 1), axis=1
        )
    else:
        df["dept_span"] = 1
        df["repeat_dept"] = df["repeat_all"]

    return df


# ═════════════════════════════════════════════════════════════
# AI 중복지적 결과 반영 (핵심 연동부)
# ═════════════════════════════════════════════════════════════
def _apply_ai_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    🔎 AI 중복지적 분석 결과를 원본 데이터에 병합한다.

    [동작]
      · session_state 에 저장된 {_row_id: 중복건수} 맵을 조회
      · 분석 대상이었던 행은 AI 판정값, 나머지는 제목일치값을 사용
      · 최종 판정 결과를 eff_repeat / eff_span 컬럼에 담아
        KPI · 경고 · 표 강조 · 프로파일 카드가 모두 같은 값을 쓰도록 통일

    [분석 범위에 따른 반영 위치]
      · 부서 내 비교 → eff_repeat (부서내반복)
      · 전사 통합 비교 → eff_span (관련부서수)
    """
    df = df.copy()

    # 기본값 : 제목 일치 기준
    df["eff_repeat"] = df.get("repeat_dept", 1)
    df["eff_span"] = df.get("dept_span", 1)
    df["repeat_basis"] = "제목"
    df["ai_group"] = pd.NA

    if not st.session_state.get("_dup_apply", True):
        return df

    dup_map = st.session_state.get("_dup_map", {})
    grp_map = st.session_state.get("_dup_group_map", {})
    span_map = st.session_state.get("_dup_span_map", {})
    mode = st.session_state.get("_dup_scope_mode", "dept")

    if not dup_map:
        return df

    if "_row_id" not in df.columns:
        return df

    ai_cnt = df["_row_id"].map(dup_map)
    ai_grp = df["_row_id"].map(grp_map)
    covered = ai_cnt.notna()

    df["ai_group"] = ai_grp

    if mode == "dept":
        # 부서 내 비교 → 부서내반복을 AI 판정으로 대체
        df.loc[covered, "eff_repeat"] = ai_cnt[covered].astype(int)
    else:
        # 전사 통합 비교 → 관련부서수를 AI 판정으로 대체
        ai_span = df["_row_id"].map(span_map)
        span_covered = ai_span.notna()
        df.loc[span_covered, "eff_span"] = ai_span[span_covered].astype(int)
        df.loc[covered, "eff_repeat"] = ai_cnt[covered].astype(int)

    df.loc[covered, "repeat_basis"] = "AI"
    return df


def _render_basis_banner(df: pd.DataFrame):
    """현재 어떤 판정 기준이 적용 중인지 화면 상단에 표시한다."""
    n_ai = int((df["repeat_basis"] == "AI").sum()) if "repeat_basis" in df.columns else 0

    if n_ai == 0:
        st.info(
            "ℹ️ 현재 반복 지적은 **제목 일치 기준**으로 표시됩니다. "
            "표현이 다른 동일 지적은 별개로 집계될 수 있습니다.  \n"
            "정확한 판정이 필요하면 아래 **🔎 AI 중복지적 분석** 탭에서 분석을 실행하십시오."
        )
        return

    scope = st.session_state.get("_dup_scope", "")
    col1, col2 = st.columns([5, 1])
    with col1:
        st.success(
            f"✅ **AI 중복지적 판정이 적용 중입니다** — {scope} · 대상 {n_ai:,}건  \n"
            f"KPI · 경고 · 지적사항 목록 · 프로파일 카드가 모두 AI 판정 기준으로 표시됩니다."
        )
    with col2:
        st.write("")
        st.checkbox(
            "AI 판정 적용", value=True, key="_dup_apply",
            help="해제하면 제목 일치 기준으로 되돌아갑니다. 두 기준을 비교할 때 사용하십시오.",
        )


# ─────────────────────────────────────────
# 필터 영역
# ─────────────────────────────────────────
def _render_filters(df: pd.DataFrame, departments: list[str]):

    col1, col2, col3, col4, col5 = st.columns([2.5, 1.5, 1.5, 1.5, 1.5])

    with col1:
        selected_dept = st.selectbox(
            "🏢 부서 선택", options=departments, key="dept_select"
        )
    with col2:
        audit_options = ["전체"] + sorted(
            df["audit_type"].dropna().unique().tolist()
        ) if "audit_type" in df.columns else ["전체"]
        selected_audit = st.selectbox("심사구분", options=audit_options, key="audit_select")
    with col3:
        part_options = ["전체", "안전계획", "안전보건", "재난안전"]
        selected_part = st.selectbox("파트", options=part_options, key="part_select")
    with col4:
        year_list = sorted(
            df["year"].dropna().unique().tolist(), reverse=True
        ) if "year" in df.columns else []
        year_options = ["전체"] + [str(int(y)) for y in year_list if y > 0]
        selected_year = st.selectbox("연도", options=year_options, key="year_select")
    with col5:
        repeat_only = st.selectbox(
            "반복 지적",
            options=["전체", "부서내 반복만", "전사 공통만"],
            key="repeat_select",
        )

    df_filtered = _filter_data(
        df, selected_dept, selected_audit, selected_part, selected_year, repeat_only
    )

    st.markdown("---")

    _render_kpi(df_filtered, selected_dept)
    _render_warning(df_filtered)
    _render_main_table(df_filtered)
    # 탭에는 전체 데이터도 함께 전달 (AI 분석은 전체를 대상으로 하므로)
    _render_actions(df_filtered, selected_dept, df)


# ─────────────────────────────────────────
# 데이터 필터링
# ─────────────────────────────────────────
def _filter_data(
    df: pd.DataFrame,
    dept: str, audit: str, part: str, year: str, repeat: str,
) -> pd.DataFrame:

    result = df[df["department"] == dept].copy()

    if audit != "전체" and "audit_type" in result.columns:
        result = result[result["audit_type"] == audit]

    if part != "전체" and "ai_part" in result.columns:
        result = result[result["ai_part"] == part]

    if year != "전체" and "year" in result.columns:
        result = result[result["year"] == int(year)]

    # 반복 필터 — 현재 적용 중인 판정 기준(eff_*)을 사용
    if repeat == "부서내 반복만" and "eff_repeat" in result.columns:
        result = result[result["eff_repeat"] >= 2]
    elif repeat == "전사 공통만" and "eff_span" in result.columns:
        result = result[result["eff_span"] >= 2]

    return result.reset_index(drop=True)


# ─────────────────────────────────────────
# KPI 카드
# ─────────────────────────────────────────
def _render_kpi(df: pd.DataFrame, dept: str):
    basis = "AI 판정" if (
        "repeat_basis" in df.columns and (df["repeat_basis"] == "AI").any()
    ) else "제목 일치"

    st.subheader(f"📌 {dept} 심사 현황")

    total = len(df)
    cmd_cnt = len(df[df["audit_type"] == "시정명령"]) if "audit_type" in df.columns else 0
    high_risk = len(df[df["ai_risk"] == "상"]) if "ai_risk" in df.columns else 0
    rep_dept = len(df[df["eff_repeat"] >= 2]) if "eff_repeat" in df.columns else 0
    rep_span = len(df[df["eff_span"] >= 2]) if "eff_span" in df.columns else 0
    act = action_summary(df)

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric("📋 총 지적건수", f"{total}건")
    with col2:
        st.metric(
            "🔴 시정명령", f"{cmd_cnt}건",
            delta="즉시 조치" if cmd_cnt > 0 else None,
            delta_color="inverse" if cmd_cnt > 0 else "off",
        )
    with col3:
        st.metric(
            "🟡 개선권고",
            f"{len(df[df['audit_type']=='개선권고'])}건"
            if "audit_type" in df.columns else "0건",
        )
    with col4:
        st.metric(
            "⚠️ 리스크 상", f"{high_risk}건",
            delta="집중 관리" if high_risk > 0 else None,
            delta_color="inverse" if high_risk > 0 else "off",
        )
    with col5:
        st.metric(
            "🔁 부서내 반복", f"{rep_dept}건",
            delta=f"{basis} 기준",
            delta_color="off",
        )
    with col6:
        미흡건 = act["형식적"] + act["미확인"]
        st.metric(
            "✅ 조치 이행률", f"{act['이행률']}%",
            delta=f"형식적/미확인 {미흡건}건" if 미흡건 > 0 else None,
            delta_color="inverse" if 미흡건 > 0 else "off",
        )

    st.caption(
        f"🔁 부서내 반복 = 같은 부서에서 동일 지적이 재발한 건 (중복지적 감점 대상, **{basis}** 기준)   ·   "
        f"전사 공통 = 2개 부서 이상에서 나타난 지적 {rep_span}건 (공통 중점항목 후보)"
    )

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
    if "eff_repeat" in df.columns:
        high = df[df["eff_repeat"] >= 3]
        if not high.empty:
            basis = "AI 판정" if (df["repeat_basis"] == "AI").any() else "제목 일치"
            titles = high["title"].unique()
            st.warning(
                f"⚠️ **부서내 3회 이상 반복 지적 {len(titles)}건** ({basis} 기준) — "
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

    basis = "AI 판정" if (
        "repeat_basis" in df.columns and (df["repeat_basis"] == "AI").any()
    ) else "제목 일치"

    st.subheader(f"📋 지적사항 목록 ({len(df)}건)")
    st.caption(f"반복 판정 기준 : **{basis}**")

    col_map = {
        "year":          "연도",
        "mgmt_no":       "관리번호",
        "audit_type":    "심사구분",
        "ai_part":       "파트",
        "title":         "지적사항",
        "problem":       "현황및문제점",
        "improvement":   "개선방안",
        "action_result": "추진실적",
        "action_status": "조치상태",
        "ai_risk":       "리스크",
        "eff_repeat":    "부서내반복",
        "eff_span":      "관련부서수",
        "repeat_basis":  "판정기준",
        "ai_group":      "AI그룹",
        "ai_reason":     "분류이유",
    }

    avail_cols = [c for c in col_map.keys() if c in df.columns]
    display_df = df[avail_cols].copy()
    display_df.columns = [col_map[c] for c in avail_cols]

    # AI 분석 전이면 AI 전용 컬럼은 숨김 (표를 단순하게 유지)
    if basis == "제목 일치":
        for c in ["판정기준", "AI그룹"]:
            if c in display_df.columns:
                display_df = display_df.drop(columns=[c])

    # ── 행 강조 ──
    # 배경색만 지정하면 다크 테마에서 흰 글자와 겹쳐 보이지 않으므로
    # 배경색과 글자색을 함께 지정한다.
    RED_BG, RED_TXT = "#7F1D1D", "#FFFFFF"   # 시정명령 · 부서내 3회 이상
    AMB_BG, AMB_TXT = "#7C4A03", "#FFFFFF"   # 부서내 2회 반복
    BLU_BG, BLU_TXT = "#1E3A5F", "#FFFFFF"   # 전사 공통 (2개 부서 이상)

    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def highlight_rows(row):
        bg = txt = None

        # 우선순위 : 전사공통 < 부서내2회 < 부서내3회 = 시정명령
        if "관련부서수" in row.index and _to_int(row["관련부서수"]) >= 2:
            bg, txt = BLU_BG, BLU_TXT

        if "부서내반복" in row.index:
            cnt = _to_int(row["부서내반복"])
            if cnt >= 3:
                bg, txt = RED_BG, RED_TXT
            elif cnt >= 2:
                bg, txt = AMB_BG, AMB_TXT

        if "심사구분" in row.index and row["심사구분"] == "시정명령":
            bg, txt = RED_BG, RED_TXT

        if bg is None:
            return [""] * len(row)
        return [f"background-color: {bg}; color: {txt}"] * len(row)

    st.dataframe(
        display_df.style.apply(highlight_rows, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(520, 45 + len(display_df) * 38),
        column_config={
            "연도":         st.column_config.NumberColumn(width="small"),
            "관리번호":     st.column_config.TextColumn(width="small"),
            "심사구분":     st.column_config.TextColumn(width="small"),
            "파트":         st.column_config.TextColumn(width="small"),
            "지적사항":     st.column_config.TextColumn(width="large"),
            "현황및문제점": st.column_config.TextColumn(width="large"),
            "개선방안":     st.column_config.TextColumn(width="medium"),
            "추진실적":     st.column_config.TextColumn(width="medium"),
            "조치상태":     st.column_config.TextColumn(width="small"),
            "리스크":       st.column_config.TextColumn(width="small"),
            "부서내반복":   st.column_config.NumberColumn(width="small"),
            "관련부서수":   st.column_config.NumberColumn(width="small"),
            "판정기준":     st.column_config.TextColumn(width="small"),
            "AI그룹":       st.column_config.NumberColumn(width="small"),
            "분류이유":     st.column_config.TextColumn(width="medium"),
        },
    )

    st.caption(
        "🟥 진한 빨강 : 시정명령 또는 부서내 3회 이상 반복   ·   "
        "🟧 진한 주황 : 부서내 2회 반복   ·   "
        "🟦 진한 파랑 : 전사 공통(2개 부서 이상)   ·   "
        "기본 : 일반"
    )

    st.markdown("---")
    _render_download(df, display_df)


# ─────────────────────────────────────────
# 엑셀 다운로드 (선택 부서)
# ─────────────────────────────────────────
def _render_download(df_orig: pd.DataFrame, display_df: pd.DataFrame):
    col1, col2 = st.columns([3, 1])

    with col2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            display_df.to_excel(writer, index=False, sheet_name="심사대상목록")
        buffer.seek(0)

        dept = st.session_state.get("dept_select", "부서")
        st.download_button(
            label="📥 엑셀 다운로드",
            data=buffer.read(),
            file_name=f"{dept}_심사대상목록.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ─────────────────────────────────────────
# 하단 액션
# ─────────────────────────────────────────
def _render_actions(df: pd.DataFrame, dept: str, df_all: pd.DataFrame):
    st.markdown("---")
    st.subheader("🔧 추가 기능")

    tab1, tab2, tab3, tab4 = st.tabs([
        "🔍 유사 사례 검색",
        "⚖️ 법령 근거 조회",
        "📝 심사 체크포인트",
        "🔎 AI 중복지적 분석",
    ])

    # ── Tab 1: 유사사례 검색
    with tab1:
        st.caption("선택한 지적사항과 유사한 과거 사례를 검색합니다.")

        if df.empty:
            st.info("지적사항이 없습니다.")
        else:
            titles = df["title"].unique().tolist() if "title" in df.columns else []
            selected_title = st.selectbox(
                "지적사항 선택", options=titles, key="similar_title_select"
            )

            if st.button("🔍 유사 사례 검색", use_container_width=True, key="btn_similar"):
                with st.spinner("유사 사례 검색 중..."):
                    results = search_similar(selected_title, top_k=5)

                if not results:
                    st.info("유사 사례를 찾을 수 없습니다.")
                else:
                    for i, case in enumerate(results, 1):
                        meta = case.get("metadata", {})
                        sim = case.get("similarity", 0)
                        with st.expander(
                            f"{i}. {meta.get('title', '')} "
                            f"({meta.get('department', '')} / {meta.get('ai_part', '')}) "
                            f"— 유사도 {sim:.0%}",
                            expanded=(i == 1),
                        ):
                            c1, c2, c3 = st.columns(3)
                            c1.write(f"**연도:** {meta.get('year', '-')}")
                            c2.write(f"**심사구분:** {meta.get('audit_type', '-')}")
                            c3.write(f"**리스크:** {meta.get('ai_risk', '-')}")
                            st.write(case.get("text", "")[:300])

    # ── Tab 2: 법령 근거
    with tab2:
        legal_status = get_legal_store_status()

        if not legal_status["ready"]:
            st.warning(
                "⚠️ 법령DB가 구축되지 않았습니다. "
                "[⚖️ 법령/규정 관리] 메뉴에서 먼저 구축하세요."
            )
        elif df.empty:
            st.info("지적사항이 없습니다.")
        else:
            titles = df["title"].unique().tolist() if "title" in df.columns else []
            sel_title = st.selectbox(
                "근거 조회할 지적사항", options=titles, key="legal_title_select"
            )

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
                type="primary", use_container_width=True, key="btn_legal_basis",
            ):
                with st.spinner("관련 법령을 검색하고 근거를 생성 중..."):
                    result = find_legal_basis(
                        title=sel_title, problem=problem,
                        audit_type=audit_type, top_k=3,
                    )

                if result["found"]:
                    st.success("✅ 법령 근거 생성 완료!")
                    st.info(result["basis"])

                    if result["sources"]:
                        st.write("**참고 출처:**")
                        for src in result["sources"]:
                            st.write(f"• {src}")

                    with st.expander("📋 복사용 텍스트"):
                        copy_text = (
                            f"【지적사항】{sel_title}\n\n"
                            f"【법령 근거】{result['basis']}\n\n"
                            f"【참고 문서】" + ", ".join(result["sources"])
                        )
                        st.code(copy_text, language=None)
                else:
                    st.warning("관련 법령/규정을 찾을 수 없습니다.")

    # ── Tab 3: 심사 체크포인트
    with tab3:
        st.caption(
            "이 부서의 과거 지적사항을 바탕으로 중점 심사 항목을 자동으로 제시합니다."
        )

        if df.empty:
            st.info("지적사항이 없습니다.")
        else:
            # AI 판정이 적용 중이면 AI 그룹 기준으로, 아니면 제목 기준으로 집계
            use_ai = "ai_group" in df.columns and df["ai_group"].notna().any()
            group_col = "ai_group" if use_ai else "_key"

            if group_col in df.columns:
                sub = df[df[group_col].notna()] if use_ai else df
                repeat_items = (
                    sub.groupby(group_col)
                    .agg(지적사항=("title", "first"), 건수=("title", "size"))
                    .sort_values("건수", ascending=False)
                    .head(10)
                    .reset_index(drop=True)
                )

                st.markdown(
                    f"**🔴 반드시 확인할 항목 (반복 지적 상위 · "
                    f"{'AI 판정' if use_ai else '제목 일치'} 기준)**"
                )
                for i, row in repeat_items.iterrows():
                    cnt = row["건수"]
                    icon = "🔴" if cnt >= 3 else "🟡" if cnt >= 2 else "🟢"
                    st.checkbox(
                        f"{icon} {row['지적사항']} ({cnt}회 지적)",
                        key=f"chk_{dept}_{i}",
                    )

            if "audit_type" in df.columns:
                cmd_items = df[df["audit_type"] == "시정명령"]
                if not cmd_items.empty:
                    st.markdown("**⛔ 시정명령 이행 여부 확인 필수**")
                    for i, row in cmd_items.iterrows():
                        st.checkbox(
                            f"시정명령: {row.get('title', '')} ({row.get('year', '')}년)",
                            key=f"cmd_{dept}_{i}",
                        )

            if st.button("💾 체크 결과 저장", use_container_width=True, key="btn_save_check"):
                st.success(
                    f"✅ {dept} 심사 체크포인트 저장 완료!\n"
                    f"현장 심사 도우미에서도 확인할 수 있습니다."
                )

    # ── Tab 4: AI 중복지적 분석
    with tab4:
        _render_duplicate_tab(df_all, dept)


# ═════════════════════════════════════════════════════════════
# AI 중복지적 분석 (탭 4)
# ═════════════════════════════════════════════════════════════
def _render_duplicate_tab(df_all: pd.DataFrame, dept: str):
    """
    제목과 현황및문제점을 AI가 함께 분석하여 중복지적을 판별한다.
    분석 결과는 session_state 에 저장되며, 화면을 다시 그릴 때
    _apply_ai_duplicates() 가 이를 읽어 KPI·표·프로파일 카드에 반영한다.
    """
    st.caption(
        "제목과 현황및문제점을 **함께** 분석하여 실질적으로 동일한 지적사항을 찾습니다. "
        "분석을 실행하면 이 화면의 KPI · 표 강조 · 프로파일 카드에 결과가 자동 반영됩니다."
    )

    with st.expander("ℹ️ 판별 방식", expanded=False):
        st.markdown("""
**1단계 · 임베딩 유사도** (nomic-embed-text)
- 제목과 현황및문제점을 각각 벡터로 변환해 유사도를 계산합니다
- **둘 다** 유사해야 중복 후보가 됩니다

**2단계 · LLM 문맥 판정** (llama3.1:8b)
- 임베딩만으로 애매한 경계 구간의 쌍만 AI가 최종 판정합니다
- 전수 비교는 쌍의 수가 급증해 현실적으로 불가능하므로 범위를 좁혀 사용합니다

**판정 예시**

| 제목 | 현황및문제점 | 판정 |
|---|---|---|
| 거의 동일 | 유사 | 중복 |
| 유사 | 완전히 다름 | 별개 |
| 유사 | 애매함 | LLM이 판정 |
        """)

    col1, col2, col3 = st.columns([1.4, 1, 1])
    with col1:
        scope_label = st.radio(
            "분석 범위",
            ["선택 부서만", "전 부서 (부서 내 비교)", "전 부서 (전사 통합 비교)"],
            index=1,
            key="dup_scope_radio",
            help="전사 통합 비교는 여러 부서에 걸친 공통취약 항목을 찾을 때 사용합니다.",
        )
    with col2:
        use_llm = st.checkbox(
            "LLM 문맥 판정 사용", value=True, key="dup_use_llm",
            help="해제하면 임베딩 유사도만으로 빠르게 판정합니다.",
        )
    with col3:
        st.write("")
        run = st.button("🔎 중복지적 분석 실행", type="primary",
                        use_container_width=True, key="btn_dup_run")

    with st.expander("⚙️ 판정 임계값 조정", expanded=False):
        st.caption(
            "실제 데이터로 한 번 돌려본 뒤, 중복이 과하게 잡히면 값을 올리고 "
            "놓치는 건이 있으면 값을 내리십시오."
        )
        s1, s2 = st.columns(2)
        with s1:
            st.markdown("**중복 확정 기준** (LLM 없이 바로 중복 처리)")
            st.slider("제목 유사도", 0.50, 0.99, 0.88, 0.01, key="dup_th")
            st.slider("현황 유사도", 0.50, 0.99, 0.82, 0.01, key="dup_ph")
        with s2:
            st.markdown("**비교 하한** (이 미만은 비교하지 않음)")
            st.slider("제목 하한", 0.30, 0.95, 0.70, 0.01, key="dup_tl")
            st.slider("현황 하한", 0.20, 0.95, 0.55, 0.01, key="dup_pl")
        st.caption(
            "하한과 확정 기준 사이 구간이 LLM 판정 대상입니다. "
            "구간이 넓을수록 정확하지만 분석 시간이 길어집니다."
        )

    if run:
        if scope_label == "선택 부서만":
            target = df_all[df_all["department"] == dept]
            scope, mode = "dept", "dept"
        elif scope_label == "전 부서 (부서 내 비교)":
            target = df_all
            scope, mode = "dept", "dept"
        else:
            target = df_all
            scope, mode = "all", "all"

        if target.empty:
            st.info("분석할 데이터가 없습니다.")
            return

        bar = st.progress(0.0)
        status = st.empty()

        def on_progress(cur, total):
            if total:
                bar.progress(min(cur / total, 1.0))

        def on_log(msg):
            status.info(msg)

        with st.spinner("AI가 지적사항을 분석하는 중입니다..."):
            try:
                result, summary = detect_duplicates(
                    target, scope=scope, use_llm=use_llm,
                    progress_cb=on_progress, log_cb=on_log,
                    title_high=st.session_state.get("dup_th", 0.88),
                    problem_high=st.session_state.get("dup_ph", 0.82),
                    title_low=st.session_state.get("dup_tl", 0.70),
                    problem_low=st.session_state.get("dup_pl", 0.55),
                )
            except Exception as e:
                logger.error(f"중복지적 분석 오류: {e}")
                st.error(f"분석 실패: {e}")
                return

        # ── 결과를 화면 전체에 반영하기 위해 매핑 저장 ──
        _store_dup_result(result, summary, scope_label, mode)

        bar.progress(1.0)
        status.success("분석 완료 — 화면 상단의 KPI와 표에 결과가 반영되었습니다.")

    # ── 결과 표시 ──
    if "_dup_result" not in st.session_state:
        return

    result = st.session_state["_dup_result"]
    summary = st.session_state["_dup_summary"]

    st.markdown("---")
    st.markdown(f"**분석 범위 : {st.session_state.get('_dup_scope', '')}**")

    if summary.empty:
        st.success("✅ 중복으로 판정된 지적사항이 없습니다.")
        return

    dup_rows = result[result["dup_group"] > 0]

    c1, c2, c3 = st.columns(3)
    c1.metric("중복 그룹", f"{len(summary)}개")
    c2.metric("관련 지적건수", f"{len(dup_rows)}건")
    c3.metric("중복지적 계상", f"{max(len(dup_rows) - len(summary), 0)}건",
              help="그룹의 두 번째 건부터 중복으로 계상합니다.")

    st.markdown("**🔁 중복지적 그룹**")
    st.dataframe(summary, use_container_width=True, hide_index=True)

    # ── 그룹별 상세 (제목 + 현황및문제점 전문) ──
    st.markdown("---")
    st.markdown("**📄 그룹별 상세 내용**")
    sel = st.selectbox(
        "확인할 그룹",
        options=summary["그룹"].tolist(),
        format_func=lambda g: (
            f"그룹 {g} — {summary[summary['그룹']==g].iloc[0]['대표 제목'][:40]} "
            f"({summary[summary['그룹']==g].iloc[0]['중복건수']}건)"
        ),
        key="dup_group_sel",
    )
    detail = result[result["dup_group"] == sel]
    show_cols = [c for c in
                 ["year", "department", "audit_type", "title", "problem", "improvement"]
                 if c in detail.columns]
    d = detail[show_cols].copy()
    d.columns = [{"year": "연도", "department": "부서", "audit_type": "심사구분",
                  "title": "제목", "problem": "현황및문제점",
                  "improvement": "개선방안"}[c] for c in show_cols]
    st.dataframe(
        d, use_container_width=True, hide_index=True,
        column_config={
            "제목": st.column_config.TextColumn(width="large"),
            "현황및문제점": st.column_config.TextColumn(width="large"),
            "개선방안": st.column_config.TextColumn(width="medium"),
        },
    )

    # ── 부서별 중복 건수 (채점표 입력용) ──
    st.markdown("---")
    st.markdown("**📊 부서별 중복지적 건수 (채점표 입력용)**")
    st.caption("루브릭 채점표의 '중복지적' 열에 입력할 건수입니다. 건당 0.1점이 감점됩니다.")
    dept_sum = duplicate_summary_by_dept(result)
    if not dept_sum.empty:
        st.dataframe(dept_sum, use_container_width=True, hide_index=True)

    # ── LLM 판정 이력 ──
    judged = result.attrs.get("llm_judged", [])
    if judged:
        with st.expander(f"🤖 LLM 판정 이력 ({len(judged)}쌍)"):
            st.dataframe(pd.DataFrame(judged), use_container_width=True, hide_index=True)

    # ── 다운로드 ──
    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="① 중복그룹 요약", index=False)
        if not dept_sum.empty:
            dept_sum.to_excel(writer, sheet_name="② 부서별 중복건수", index=False)
        cols = [c for c in
                ["dup_group", "dup_count", "year", "department", "audit_type",
                 "title", "problem", "improvement", "action_result"]
                if c in result.columns]
        out = result[result["dup_group"] > 0][cols].sort_values("dup_group")
        out.columns = [{"dup_group": "그룹", "dup_count": "중복건수", "year": "연도",
                        "department": "부서", "audit_type": "심사구분",
                        "title": "제목", "problem": "현황및문제점",
                        "improvement": "개선방안",
                        "action_result": "추진실적"}[c] for c in cols]
        out.to_excel(writer, sheet_name="③ 중복지적 상세", index=False)
        if judged:
            pd.DataFrame(judged).to_excel(writer, sheet_name="④ LLM 판정이력", index=False)
    buffer.seek(0)

    st.download_button(
        "📥 중복지적 분석결과 다운로드",
        data=buffer.read(),
        file_name=f"중복지적분석_{datetime.now():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="dl_dup",
    )

    # ── 초기화 ──
    if st.button("♻️ AI 판정 결과 초기화", key="btn_dup_clear"):
        for k in ["_dup_result", "_dup_summary", "_dup_map", "_dup_group_map",
                  "_dup_span_map", "_dup_scope", "_dup_scope_mode"]:
            st.session_state.pop(k, None)
        st.rerun()


def _store_dup_result(result: pd.DataFrame, summary: pd.DataFrame,
                      scope_label: str, mode: str):
    """
    분석 결과를 화면 전체가 참조할 수 있는 형태로 session_state 에 저장한다.
    _row_id 를 키로 삼아 원본 데이터와 안전하게 매칭한다.
    """
    st.session_state["_dup_result"] = result
    st.session_state["_dup_summary"] = summary
    st.session_state["_dup_scope"] = scope_label
    st.session_state["_dup_scope_mode"] = mode

    if "_row_id" not in result.columns:
        logger.warning("_row_id 없음 — 화면 반영 생략")
        return

    # {행ID: 그룹 내 건수} — 중복 아님(0그룹)은 1로 처리
    st.session_state["_dup_map"] = dict(zip(result["_row_id"], result["dup_count"]))
    st.session_state["_dup_group_map"] = dict(zip(result["_row_id"], result["dup_group"]))

    # 전사 통합 비교인 경우, 그룹이 몇 개 부서에 걸쳐 있는지 계산
    span_map = {}
    if mode == "all" and "department" in result.columns:
        g_span = (
            result[result["dup_group"] > 0]
            .groupby("dup_group")["department"].nunique().to_dict()
        )
        for rid, g in zip(result["_row_id"], result["dup_group"]):
            span_map[rid] = g_span.get(g, 1) if g > 0 else 1
    st.session_state["_dup_span_map"] = span_map


# ═════════════════════════════════════════════════════════════
# 전 부서 프로파일 카드 일괄 생성 (엑셀 / Word)
# ═════════════════════════════════════════════════════════════
def _render_profile_export(df: pd.DataFrame, departments: list[str]):
    """
    심사반 사전 배포용 프로파일 카드를 전 부서 한 번에 생성한다.
    AI 중복지적 분석을 실행했으면 그 판정 결과가 반영된다.
    """
    st.subheader("📤 전 부서 프로파일 카드 일괄 생성")
    st.caption(
        "심사반 사전 배포용 자료입니다. 부서별 과거지적 · 반복항목 · "
        "조치 이행률 · 시정명령 이력을 한 번에 정리합니다."
    )

    basis = "AI 판정" if (
        "repeat_basis" in df.columns and (df["repeat_basis"] == "AI").any()
    ) else "제목 일치"

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        years = sorted(
            [int(y) for y in df["year"].dropna().unique() if y > 0], reverse=True
        ) if "year" in df.columns else []
        if years:
            st.caption(
                f"📅 대상 : {min(years)} ~ {max(years)}년 ({len(years)}개년)  ·  "
                f"총 {len(df):,}건  ·  {len(departments)}개 부서  ·  "
                f"반복 판정 기준 **{basis}**"
            )
        else:
            st.caption(
                f"📅 총 {len(df):,}건  ·  {len(departments)}개 부서  ·  "
                f"반복 판정 기준 **{basis}**"
            )

    with col2:
        if st.button("📊 엑셀 생성", type="primary", use_container_width=True,
                     key="btn_profile_xlsx"):
            with st.spinner("부서별 시트를 생성하는 중..."):
                try:
                    st.session_state["_profile_xlsx"] = _build_profile_excel(df, departments)
                except Exception as e:
                    logger.error(f"프로파일 엑셀 생성 오류: {e}")
                    st.error(f"엑셀 생성 실패: {e}")

        if "_profile_xlsx" in st.session_state:
            st.download_button(
                "📥 엑셀 다운로드",
                data=st.session_state["_profile_xlsx"],
                file_name=f"부서별_프로파일카드_{datetime.now():%Y%m%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, key="dl_profile_xlsx",
            )

    with col3:
        if st.button("📄 Word 생성", use_container_width=True, key="btn_profile_docx"):
            with st.spinner("부서별 카드를 생성하는 중..."):
                try:
                    st.session_state["_profile_docx"] = _build_profile_word(df, departments)
                except Exception as e:
                    logger.error(f"프로파일 Word 생성 오류: {e}")
                    st.error(f"Word 생성 실패: {e}")

        if "_profile_docx" in st.session_state:
            st.download_button(
                "📥 Word 다운로드",
                data=st.session_state["_profile_docx"],
                file_name=f"부서별_프로파일카드_{datetime.now():%Y%m%d}.docx",
                mime="application/vnd.openxmlformats-officedocument."
                     "wordprocessingml.document",
                use_container_width=True, key="dl_profile_docx",
            )


def _repeat_groups(d: pd.DataFrame) -> pd.DataFrame:
    """
    부서 내 반복 지적항목을 집계한다.
    AI 판정이 적용 중이면 AI 그룹 기준, 아니면 제목 기준으로 묶는다.
    """
    empty = pd.DataFrame(columns=["지적사항", "현황및문제점", "반복횟수"])
    if d.empty or "title" not in d.columns:
        return empty

    use_ai = "ai_group" in d.columns and d["ai_group"].notna().any()

    if use_ai:
        sub = d[d["ai_group"].notna() & (d["ai_group"] > 0)]
        if sub.empty:
            return empty
        g = (
            sub.groupby("ai_group")
            .agg(
                지적사항=("title", "first"),
                현황및문제점=("problem", "first") if "problem" in sub.columns
                             else ("title", "first"),
                반복횟수=("title", "size"),
            )
            .reset_index(drop=True)
        )
    else:
        g = (
            d.groupby("_key")
            .agg(
                지적사항=("title", "first"),
                현황및문제점=("problem", "first") if "problem" in d.columns
                             else ("title", "first"),
                반복횟수=("title", "size"),
            )
            .reset_index(drop=True)
        )

    g = g[g["반복횟수"] >= 2].sort_values("반복횟수", ascending=False)
    return g if not g.empty else empty


def _dept_profile(df: pd.DataFrame, dept: str) -> dict:
    """부서 1개의 프로파일 지표를 계산한다."""
    d = df[df["department"] == dept]
    act = action_summary(d)
    rep = _repeat_groups(d)

    return {
        "부서": dept,
        "총지적": len(d),
        "시정명령": int((d["audit_type"] == "시정명령").sum())
                     if "audit_type" in d.columns else 0,
        "개선권고": int((d["audit_type"] == "개선권고").sum())
                     if "audit_type" in d.columns else 0,
        "리스크상": int((d["ai_risk"] == "상").sum())
                     if "ai_risk" in d.columns else 0,
        "반복항목수": len(rep),
        "중복지적건수": int(rep["반복횟수"].sum() - len(rep)) if not rep.empty else 0,
        "이행률(%)": act["이행률"],
        "형식적완료": act["형식적"],
        "미확인": act["미확인"],
        "_repeat": rep,
        "_data": d,
    }


def _build_profile_excel(df: pd.DataFrame, departments: list[str]) -> bytes:
    """
    부서별 시트로 구성된 엑셀을 생성한다.
      · 시트 ① : 전 부서 요약
      · 시트 ② : 전사 공통취약 TOP30
      · 시트 ③ : 부서별 반복 지적항목 (제목 + 현황및문제점)
      · 이후   : 부서별 상세 시트
    """
    buffer = io.BytesIO()
    profiles = [_dept_profile(df, d) for d in departments]
    basis = "AI 판정" if (
        "repeat_basis" in df.columns and (df["repeat_basis"] == "AI").any()
    ) else "제목 일치"

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        # ── 시트 ① 전 부서 요약 ──
        summary = pd.DataFrame([
            {k: v for k, v in p.items() if not k.startswith("_")} for p in profiles
        ]).sort_values("총지적", ascending=False)
        summary.insert(0, "순번", range(1, len(summary) + 1))
        summary["반복판정기준"] = basis
        summary.to_excel(writer, sheet_name="① 전부서 요약", index=False)

        # ── 시트 ② 전사 공통취약 TOP30 ──
        if "title" in df.columns and "department" in df.columns:
            group_col = "ai_group" if (
                "ai_group" in df.columns and df["ai_group"].notna().any()
            ) else "_key"
            src = df[df[group_col].notna()] if group_col == "ai_group" else df
            if group_col == "ai_group":
                src = src[src[group_col] > 0]

            if not src.empty:
                common = (
                    src.groupby(group_col)
                    .agg(
                        지적사항=("title", "first"),
                        현황및문제점=("problem", "first") if "problem" in src.columns
                                     else ("title", "first"),
                        총건수=("title", "size"),
                        관련부서수=("department", "nunique"),
                    )
                    .reset_index(drop=True)
                )
                common = common[common["관련부서수"] >= 2]
                common = common.sort_values(
                    ["관련부서수", "총건수"], ascending=False
                ).head(30).reset_index(drop=True)
                if not common.empty:
                    common.insert(0, "순위", range(1, len(common) + 1))
                    common.to_excel(
                        writer, sheet_name="② 전사 공통취약 TOP30", index=False)

        # ── 시트 ③ 부서별 반복 지적항목 ──
        rep_rows = []
        for p in profiles:
            for _, r in p["_repeat"].iterrows():
                rep_rows.append({
                    "부서": p["부서"],
                    "지적사항": r["지적사항"],
                    "현황및문제점": str(r["현황및문제점"])[:200],
                    "반복횟수": r["반복횟수"],
                    "중복계상": r["반복횟수"] - 1,
                    "감점(0.1점/건)": round((r["반복횟수"] - 1) * 0.1, 2),
                })
        if rep_rows:
            pd.DataFrame(rep_rows).to_excel(
                writer, sheet_name="③ 부서별 반복지적", index=False)

        # ── 부서별 상세 시트 ──
        col_map = {
            "year": "연도", "audit_type": "심사구분", "ai_part": "파트",
            "title": "지적사항", "problem": "현황및문제점",
            "improvement": "개선방안", "action_result": "추진실적",
            "action_status": "조치상태", "ai_risk": "리스크",
            "eff_repeat": "부서내반복", "eff_span": "관련부서수",
            "repeat_basis": "판정기준",
        }
        used = set()
        for p in profiles:
            d = p["_data"]
            cols = [c for c in col_map if c in d.columns]
            out = d[cols].copy()
            out.columns = [col_map[c] for c in cols]
            if "연도" in out.columns:
                out = out.sort_values("연도", ascending=False)

            name = str(p["부서"])[:28]
            for ch in "[]:*?/\\":
                name = name.replace(ch, "")
            base, n = name, 1
            while name in used:
                n += 1
                name = f"{base[:26]}_{n}"
            used.add(name)

            out.to_excel(writer, sheet_name=name, index=False)

    buffer.seek(0)
    return buffer.read()


def _build_profile_word(df: pd.DataFrame, departments: list[str]) -> bytes:
    """부서별 페이지로 구성된 Word 프로파일 카드를 생성한다."""
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    basis = "AI 판정" if (
        "repeat_basis" in df.columns and (df["repeat_basis"] == "AI").any()
    ) else "제목 일치"

    doc = Document()
    doc.styles["Normal"].font.name = "맑은 고딕"
    doc.styles["Normal"].font.size = Pt(10)

    def heading(text, size=14, color=(0x1F, 0x38, 0x64)):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(*color)
        return p

    def table(headers, rows):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        for i, h in enumerate(headers):
            c = t.rows[0].cells[i]
            c.text = str(h)
            for para in c.paragraphs:
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for r in para.runs:
                    r.bold = True
                    r.font.size = Pt(9)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = str(v)
                for para in cells[i].paragraphs:
                    for r in para.runs:
                        r.font.size = Pt(9)
        return t

    # ── 표지 ──
    tp = heading("부서별 심사 프로파일 카드", 18)
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sr = sub.add_run("자체종합안전심사 심사반 사전 배포용")
    sr.font.size = Pt(11)
    sr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    years = sorted([int(y) for y in df["year"].dropna().unique() if y > 0]) \
        if "year" in df.columns else []
    info = doc.add_paragraph()
    ir = info.add_run(
        (f"대상 : {min(years)}~{max(years)}년  ·  총 {len(df):,}건  ·  "
         f"{len(departments)}개 부서" if years else
         f"총 {len(df):,}건  ·  {len(departments)}개 부서")
        + f"    |    반복 판정 : {basis}    |    생성일 : {datetime.now():%Y-%m-%d}"
    )
    ir.font.size = Pt(9)
    ir.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # ── 전 부서 요약 ──
    heading("전 부서 요약", 13)
    profiles = sorted(
        [_dept_profile(df, d) for d in departments], key=lambda p: -p["총지적"]
    )
    table(
        ["부서", "총지적", "시정명령", "리스크상", "반복항목", "중복계상", "이행률"],
        [[p["부서"], f"{p['총지적']}건", f"{p['시정명령']}건", f"{p['리스크상']}건",
          f"{p['반복항목수']}개", f"{p['중복지적건수']}건", f"{p['이행률(%)']}%"]
         for p in profiles],
    )
    doc.add_page_break()

    # ── 부서별 카드 ──
    for p in profiles:
        heading(f"■ {p['부서']}", 15)

        table(
            ["총 지적", "시정명령", "개선권고", "리스크 상", "반복 항목", "조치 이행률"],
            [[f"{p['총지적']}건", f"{p['시정명령']}건", f"{p['개선권고']}건",
              f"{p['리스크상']}건", f"{p['반복항목수']}개", f"{p['이행률(%)']}%"]],
        )
        doc.add_paragraph()

        heading(f"반복 지적항목 ({basis} 기준 · 재발 여부 확인 필수)", 11, (0xC0, 0, 0))
        rep = p["_repeat"]
        if not rep.empty:
            table(
                ["지적사항", "현황및문제점", "반복", "중복계상"],
                [[r["지적사항"], str(r["현황및문제점"])[:80],
                  f"{r['반복횟수']}회", f"{r['반복횟수'] - 1}건"]
                 for _, r in rep.head(10).iterrows()],
            )
        else:
            doc.add_paragraph("  반복 지적항목 없음")
        doc.add_paragraph()

        d = p["_data"]
        heading("시정명령 이력 (이행 여부 확인 필수)", 11, (0xC0, 0, 0))
        if "audit_type" in d.columns:
            cmd = d[d["audit_type"] == "시정명령"]
            if not cmd.empty:
                table(["연도", "지적사항", "조치상태"],
                      [[r.get("year", "-"), r.get("title", ""),
                        r.get("action_status", "-")]
                       for _, r in cmd.head(10).iterrows()])
            else:
                doc.add_paragraph("  시정명령 이력 없음")
        doc.add_paragraph()

        heading("심사 시 참고", 11)
        tips = []
        if p["반복항목수"] > 0:
            tips.append(
                f"반복 지적항목 {p['반복항목수']}개 (중복 계상 {p['중복지적건수']}건) — "
                f"재발 여부를 현장에서 확인하고, 재발 시 채점표에 중복지적으로 입력"
            )
        if p["형식적완료"] > 0:
            tips.append(
                f"형식적 완료 {p['형식적완료']}건 — 조치결과가 부실한 건으로 "
                f"실제 이행 여부 확인 필요"
            )
        if p["미확인"] > 0:
            tips.append(f"조치 미확인 {p['미확인']}건 — 이행실태 항목 심사 시 집중 확인")
        if p["시정명령"] > 0:
            tips.append(f"과거 시정명령 {p['시정명령']}건 — 동일 유형 재점검 권장")
        if not tips:
            tips.append("과거 이력상 특이 취약점 없음 — 전사 공통 중점항목 위주로 심사")
        for tip in tips:
            doc.add_paragraph(f"  · {tip}")

        doc.add_page_break()

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()