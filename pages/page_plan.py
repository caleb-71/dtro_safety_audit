# ════════════════════════════════════════════════════════════
# pages/page_plan.py  —  📋 심사계획 수립 (신규, 2026-07)
# ════════════════════════════════════════════════════════════
# [화면 역할]
# 과거 심사이력 데이터를 바탕으로 "올해 자체종합안전심사를
# 어떻게 설계할 것인가"를 지원하는 화면입니다.
#
# 탭 1: 🔥 공통취약 TOP30
#   여러 부서·여러 해에 걸쳐 반복 지적된 항목을 자동 도출
#   → 올해 "전 부서 공통 중점 심사항목" 선정 근거자료
#
# 탭 2: 🏢 부서별 프로파일 카드
#   부서별 과거지적 요약 / 리스크분포 / 반복항목 / 미조치 목록
#   + 해당 부서에 적용되는 심사 점검분야 자동 매핑
#   → 심사반이 부서 방문 전에 보는 "예습 카드"
#
# 탭 3: 🧮 배점 시뮬레이션
#   공사 심사기준 그대로 구현:
#   종합점수 = (안전관리체계 + 안전보건관리 + 해당분야) ÷ 3
#              + 가점 − 감점
#   → 심사 후 부서별 종합점수를 즉석에서 계산·검증
# ════════════════════════════════════════════════════════════

import logging
import pandas as pd
import streamlit as st

from config.settings import PROCESSED_DIR, RISK_LEVELS

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# 배점 기준 상수 (공사 심사기준 그대로 반영)
# ═══════════════════════════════════════════
# ※ 기준이 바뀌면 이 상수만 수정하면 됩니다 (화면 코드는 수정 불필요)

# ── 가점 항목: (항목명, 선택 가능한 점수 목록, 설명) ──
BONUS_ITEMS = [
    ("사고·장애 및 산업재해 예방 우수사례 부서",
     [0.0, 0.1, 0.2, 0.3],
     "심사기간 중 분야별 사례수집, 심사반 검증 후 부여 (상위 3개 부서)"),
    ("안전문화운동 정착 공로 부서",
     [0.0, 0.1, 0.2],
     "안전행사 협조, 운동실행 우수"),
    ("안전보건관리책임자 등 최우수 관리자 소속부서",
     [0.0, 0.2],
     "연간 총 4개 부서 (상·하반기 본사·현업 각 1개)"),
    ("안전파수꾼 활동(내부제안) 우수 포상자 소속부서",
     [0.0, 0.1],
     "포상받은 직원의 소속부서"),
    ("부분(통합)훈련 역량 강화 노력 부서",
     [0.0, 0.2],
     "자체 컨설팅 참여 등"),
    ("안전보건 동영상 콘텐츠 공모전 포상부서",
     [0.0, 0.1, 0.2],
     "최우수 0.2 / 우수·장려 0.1 (2025 한시가점)"),
]

# ── 감점 항목: (항목명, 건당 감점, 설명) ──
PENALTY_ITEMS = [
    ("기관경고",          0.5, "심사대상 기간 중 사고·장애 등 부서 처분"),
    ("주의(개인)",        0.1, "개인 처분"),
    ("경고(개인)",        0.2, "개인 처분"),
    ("견책 이상",         0.3, "개인 처분"),
    ("안전보건 업무수행평가 불합격 판정자", 0.3, "불합격 판정자 소속부서"),
]

# ── 부서명 → 해당분야 점검표 자동 매핑 ──
# 부서명에 키워드가 포함되어 있으면 해당 점검분야를 배정합니다.
# 위에서 아래 순서로 검사하며, 먼저 매칭되는 분야가 적용됩니다.
# 매칭 안 되는 부서(본사 부서 등)는 "공통(안전관리체계+안전보건)" 만 적용
AUDIT_FIELD_MAP = [
    (["관제"],                          "종합관제센터"),
    (["고객센터", "역무"],               "1·2·3고객센터"),
    (["승무"],                          "승무사업소(1·2호선)"),
    (["경전철검수", "경전철차량"],        "경전철차량기지사업소"),
    (["차량기지", "검수", "차량사업"],    "차량기지사업소(월배·안심·문양)"),
    (["경전철기술", "경전철토목", "경전철전기"], "경전철기술사업소"),
    (["시설", "기계", "건축", "토목"],    "시설기계사업소"),
    (["전기", "통신", "전력"],           "전기통신사업소"),
    (["신호", "전자"],                   "신호전자사업소"),
]


# ═══════════════════════════════════════════
# 메인 렌더
# ═══════════════════════════════════════════
def render():
    st.title("📋 심사계획 수립")
    st.markdown("과거 심사이력 데이터를 바탕으로 **중점 심사항목 도출 → 부서 예습 → 배점 계산**까지 지원합니다.")
    st.markdown("---")

    df = _load_data()
    if df is None or df.empty:
        st.warning("⚠️ 분류된 심사 데이터(processed_data.csv)가 없습니다. 데이터 업로드 → AI 분류를 먼저 실행하세요.")
        return

    # ── 📄 심사계획서(docx) 다운로드 ──
    # 아래 탭들이 화면에 보여주는 집계 결과(TOP30 + 부서 프로파일 +
    # 배점기준)를 그대로 Word 문서로 만들어 내려받는 기능입니다.
    # 결재·보고용 문서가 필요할 때 사용하세요.
    _render_docx_download(df)
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs([
        "🔥 공통취약 TOP30", "🏢 부서별 프로파일 카드", "🧮 배점 시뮬레이션"
    ])

    with tab1:
        _render_top30(df)
    with tab2:
        _render_dept_profile(df)
    with tab3:
        _render_score_simulator(df)


# ─────────────────────────────────────────
# 데이터 로드 (page_dept.py 와 동일한 방식)
# ─────────────────────────────────────────
def _load_data() -> pd.DataFrame | None:
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path, dtype=str)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    # 리스크 가중치 컬럼 부여 (상3/중2/하1, 미분류는 중간값 2)
    if "ai_risk" in df.columns:
        df["risk_w"] = df["ai_risk"].map(RISK_LEVELS).fillna(2).astype(float)
    else:
        df["risk_w"] = 2.0
    return df


def _norm_title(t: str) -> str:
    """
    제목을 그룹핑용 키로 정규화합니다.
    같은 지적인데 띄어쓰기만 다른 경우("MSDS 관리미흡" vs "MSDS 관리 미흡")를
    하나로 묶기 위해 공백을 모두 제거해서 비교합니다.
    """
    return str(t).replace(" ", "").strip()


# ═══════════════════════════════════════════
# 탭 1: 공통취약 TOP30
# ═══════════════════════════════════════════
def _render_top30(df: pd.DataFrame):
    st.subheader("🔥 공통취약 항목 TOP30")
    st.caption(
        "우선순위점수 = 반복건수 × 평균 리스크가중(상3/중2/하1). "
        "여러 부서에서 반복된 항목일수록 구조적 문제 가능성이 높아 "
        "올해 **전 부서 공통 중점 심사항목** 후보입니다."
    )

    if "title" not in df.columns:
        st.info("제목 컬럼이 없습니다.")
        return

    # ── 옵션: 최근 N년만 볼지 선택 ──
    # 너무 오래된 지적은 이미 개선됐을 수 있으므로 기간 선택 제공
    years = sorted(df["year"].dropna().unique().tolist(), reverse=True) if "year" in df.columns else []
    col_a, col_b = st.columns([1, 1])
    with col_a:
        year_range = st.selectbox(
            "분석 대상 기간",
            ["전체 기간", "최근 2개년", "최근 3개년"],
            key="plan_year_range"
        )
    with col_b:
        min_count = st.number_input("최소 반복 건수", 2, 10, 2, key="plan_min_count")

    target = df.copy()
    if year_range != "전체 기간" and years:
        n = 2 if "2개년" in year_range else 3
        target = target[target["year"].isin(years[:n])]

    # ── 제목 정규화 후 그룹 집계 ──
    target["_key"] = target["title"].apply(_norm_title)

    grouped = target.groupby("_key").agg(
        건수=("title", "size"),
        대표제목=("title", "first"),
        평균가중=("risk_w", "mean"),
        부서수=("department", "nunique") if "department" in target.columns else ("title", "size"),
    ).reset_index(drop=True)

    grouped = grouped[grouped["건수"] >= min_count]
    if grouped.empty:
        st.success(f"✅ {min_count}건 이상 반복된 항목이 없습니다.")
        return

    # 우선순위점수 = 건수 × 평균 리스크가중 (소수1자리)
    grouped["우선순위점수"] = (grouped["건수"] * grouped["평균가중"]).round(1)
    grouped["평균가중"] = grouped["평균가중"].round(2)
    grouped = grouped.sort_values(
        ["우선순위점수", "부서수"], ascending=False
    ).head(30).reset_index(drop=True)
    grouped.index = grouped.index + 1   # 순위 1부터 표시

    # 전사 공통(2개 부서 이상) 표시 컬럼
    grouped["범위"] = grouped["부서수"].apply(
        lambda n: "🌐 전사공통" if n >= 2 else "단일부서"
    )

    show = grouped[["대표제목", "건수", "부서수", "범위", "평균가중", "우선순위점수"]]
    show.columns = ["지적 항목", "반복건수", "관련부서수", "범위", "평균리스크", "우선순위점수"]
    st.dataframe(show, use_container_width=True)

    # ── 요약 지표 ──
    col1, col2, col3 = st.columns(3)
    col1.metric("TOP30 항목 총 지적건수", f"{int(grouped['건수'].sum()):,}건")
    col2.metric("전사공통 항목", f"{int((grouped['부서수'] >= 2).sum())}개")
    col3.metric("최다 반복 항목", f"{int(grouped['건수'].max())}건")

    # ── 상위 항목 상세: 어느 부서에서 언제 지적됐는지 ──
    st.markdown("---")
    st.markdown("**🔍 항목별 상세 (어느 부서에서 반복됐는지)**")
    sel = st.selectbox(
        "상세 확인할 항목 선택",
        grouped["대표제목"].tolist(),
        key="plan_top30_detail"
    )
    detail = target[target["_key"] == _norm_title(sel)]
    cols = [c for c in ["year", "department", "audit_type", "ai_risk", "progress_type"] if c in detail.columns]
    d = detail[cols].copy()
    d.columns = [{"year": "년도", "department": "부서", "audit_type": "심사구분",
                  "ai_risk": "리스크", "progress_type": "추진구분"}[c] for c in cols]
    st.dataframe(d.sort_values("년도", ascending=False), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════
# 탭 2: 부서별 프로파일 카드
# ═══════════════════════════════════════════
def _render_dept_profile(df: pd.DataFrame):
    st.subheader("🏢 부서별 프로파일 카드")
    st.caption("심사반이 부서 방문 전에 확인하는 예습 자료입니다. 리스크 가중점수가 높은 부서부터 정렬됩니다.")

    if "department" not in df.columns:
        st.info("담당부서 컬럼이 없습니다.")
        return

    # ── 부서별 요약 집계 ──
    dept_summary = _build_dept_summary(df)

    # 상단: 우선 점검 순위 (가중점수 기준)
    st.markdown("**📊 부서별 심사 우선순위 (리스크 가중점수 기준)**")
    top_show = dept_summary[["부서", "총지적", "시정명령", "반복항목수", "미완료", "가중점수"]].head(15)
    st.dataframe(top_show, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── 개별 부서 프로파일 카드 ──
    sel_dept = st.selectbox(
        "프로파일 카드를 볼 부서 선택",
        dept_summary["부서"].tolist(),
        key="plan_dept_select"
    )
    _render_single_profile(df, sel_dept, dept_summary)


def _build_dept_summary(df: pd.DataFrame) -> pd.DataFrame:
    """부서별 핵심 지표를 한 번에 집계합니다."""
    rows = []
    for dept, g in df.groupby("department"):
        # 반복항목: 같은 제목이 2회 이상 지적된 항목 수
        title_counts = g["title"].apply(_norm_title).value_counts() if "title" in g.columns else pd.Series()
        repeat_cnt = int((title_counts >= 2).sum())
        # 미완료: 추진구분이 "완료" 가 아닌 건
        if "progress_type" in g.columns:
            incomplete = int((g["progress_type"].fillna("") != "완료").sum())
        else:
            incomplete = 0
        rows.append({
            "부서": dept,
            "총지적": len(g),
            "시정명령": int((g["audit_type"] == "시정명령").sum()) if "audit_type" in g.columns else 0,
            "반복항목수": repeat_cnt,
            "미완료": incomplete,
            # 가중점수 = Σ리스크가중 + 반복항목×2 (반복은 2배 페널티 사상 반영)
            "가중점수": round(float(g["risk_w"].sum()) + repeat_cnt * 2, 1),
        })
    return pd.DataFrame(rows).sort_values("가중점수", ascending=False).reset_index(drop=True)


def _match_audit_field(dept: str) -> str:
    """부서명 키워드로 해당분야 점검표를 자동 배정합니다."""
    for keywords, field in AUDIT_FIELD_MAP:
        if any(kw in str(dept) for kw in keywords):
            return field
    return "공통 점검표만 적용 (안전관리체계 + 안전보건체계)"


def _render_single_profile(df: pd.DataFrame, dept: str, summary: pd.DataFrame):
    """선택된 부서 1개의 상세 프로파일 카드를 그립니다."""
    g = df[df["department"] == dept]
    row = summary[summary["부서"] == dept].iloc[0]

    st.markdown(f"### 📇 {dept}")

    # ── 적용 점검분야 안내 ──
    field = _match_audit_field(dept)
    st.info(
        f"**적용 심사표**: 안전관리체계(공통 100점) + 안전보건체계(공통 100점) + "
        f"해당분야 **[{field}]** (100점) → 3분야 평균이 점검표 득점"
    )

    # ── 핵심 지표 카드 ──
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 지적", f"{row['총지적']}건")
    c2.metric("시정명령", f"{row['시정명령']}건")
    c3.metric("반복항목", f"{row['반복항목수']}개")
    c4.metric("미완료", f"{row['미완료']}건")
    c5.metric("가중점수", f"{row['가중점수']}")

    # ── 리스크 분포 ──
    if "ai_risk" in g.columns:
        risk_dist = g["ai_risk"].value_counts()
        st.caption(
            "리스크 분포: " + " / ".join(
                f"{lv} {int(risk_dist.get(lv, 0))}건" for lv in ["상", "중", "하"]
            )
        )

    col_l, col_r = st.columns(2)

    # ── 좌: 반복 지적항목 (올해 재확인 필수) ──
    with col_l:
        st.markdown("**🔁 반복 지적항목 (올해 재확인 필수)**")
        tc = g.groupby(g["title"].apply(_norm_title)).agg(
            제목=("title", "first"), 건수=("title", "size")
        )
        rep = tc[tc["건수"] >= 2].sort_values("건수", ascending=False).head(8)
        if not rep.empty:
            st.dataframe(rep.reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.success("반복 지적항목 없음")

    # ── 우: 미완료 지적 (이행 확인 대상) ──
    with col_r:
        st.markdown("**⏳ 조치 미완료 지적 (이행 확인 대상)**")
        if "progress_type" in g.columns:
            inc = g[g["progress_type"].fillna("") != "완료"]
            cols = [c for c in ["year", "title", "audit_type", "progress_type"] if c in inc.columns]
            if not inc.empty:
                d = inc[cols].copy().sort_values("year", ascending=False).head(8)
                d.columns = [{"year": "년도", "title": "제목",
                              "audit_type": "구분", "progress_type": "추진"}[c] for c in cols]
                st.dataframe(d, use_container_width=True, hide_index=True)
            else:
                st.success("미완료 지적 없음")
        else:
            st.caption("추진구분 데이터 없음")

    # ── 심사 시 참고 코멘트 (룰 기반 자동 생성 — LLM 미사용으로 즉시 표시) ──
    tips = []
    if row["반복항목수"] > 0:
        tips.append(f"반복항목 {row['반복항목수']}개 → 재발 여부 현장 확인 필수 (감점·시정명령 검토 대상)")
    if row["미완료"] > 0:
        tips.append(f"미완료 {row['미완료']}건 → '전년도 지적사항 이행실태' 항목(가중치 6.0) 심사 시 집중 확인")
    if row["시정명령"] > 0:
        tips.append(f"과거 시정명령 {row['시정명령']}건 → 동일 유형 재점검 권장")
    if not tips:
        tips.append("과거 이력상 특이 취약점 없음 — 공통 중점항목 위주 심사")
    st.markdown("**💡 심사 시 참고**")
    for t in tips:
        st.markdown(f"- {t}")


# ═══════════════════════════════════════════
# 탭 3: 배점 시뮬레이션
# ═══════════════════════════════════════════
def _render_score_simulator(df: pd.DataFrame):
    st.subheader("🧮 종합점수 배점 시뮬레이션")
    st.caption(
        "공사 심사기준 그대로: **종합점수 = (안전관리체계 + 안전보건관리 + 해당분야) ÷ 3 + 가점 − 감점**  "
        "· 안전보건관리 배점 강화(15%→33%) 취지에 따라 3분야 동일가중 평균 방식"
    )

    # ── 대상 부서 선택 (데이터 연동 참고지표 표시용) ──
    dept_list = sorted(df["department"].dropna().unique().tolist()) if "department" in df.columns else []
    sel_dept = st.selectbox("시뮬레이션 대상 부서", ["(부서 미지정)"] + dept_list, key="sim_dept")

    if sel_dept != "(부서 미지정)":
        g = df[df["department"] == sel_dept]
        rep = int((g["title"].apply(_norm_title).value_counts() >= 2).sum())
        inc = int((g["progress_type"].fillna("") != "완료").sum()) if "progress_type" in g.columns else 0
        st.caption(
            f"📌 {sel_dept} 과거이력 참고: 총지적 {len(g)}건 · 반복항목 {rep}개 · 미완료 {inc}건 "
            f"→ '지적사항 이행실태(가중치 6.0)' 등 관련 항목 채점 시 참고"
        )

    st.markdown("---")

    # ── ① 심사점검표 득점 ──
    st.markdown("**① 심사점검표 득점 (3개 분야 각 100점 만점)**")
    c1, c2, c3 = st.columns(3)
    s1 = c1.number_input("안전관리체계", 0.0, 100.0, 85.0, 0.5, key="sim_s1")
    s2 = c2.number_input("안전보건관리", 0.0, 100.0, 85.0, 0.5, key="sim_s2")
    s3 = c3.number_input("해당분야",     0.0, 100.0, 85.0, 0.5, key="sim_s3")
    base = round((s1 + s2 + s3) / 3, 3)
    st.caption(f"점검표 득점 = ({s1} + {s2} + {s3}) ÷ 3 = **{base}점**")

    st.markdown("---")

    # ── ② 가점 ──
    st.markdown("**② 가점**")
    bonus_total = 0.0
    for i, (name, options, desc) in enumerate(BONUS_ITEMS):
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.markdown(f"- {name}")
            st.caption(f"  {desc}")
        with col_b:
            v = st.selectbox(
                "점수", options,
                key=f"sim_bonus_{i}",
                label_visibility="collapsed",
                format_func=lambda x: f"+{x}" if x > 0 else "해당없음",
            )
            bonus_total += v
    st.caption(f"가점 합계: **+{round(bonus_total, 2)}점**")

    st.markdown("---")

    # ── ③ 감점 ──
    st.markdown("**③ 감점** (심사대상 기간 중 처분 건수 입력)")
    penalty_total = 0.0
    p_cols = st.columns(len(PENALTY_ITEMS))
    for i, (name, per, desc) in enumerate(PENALTY_ITEMS):
        with p_cols[i]:
            cnt = st.number_input(
                f"{name}\n(건당 -{per})",
                0, 20, 0, key=f"sim_pen_{i}",
                help=desc
            )
            penalty_total += cnt * per
    st.caption(f"감점 합계: **−{round(penalty_total, 2)}점**")

    st.markdown("---")

    # ── 최종 결과 ──
    final = round(base + bonus_total - penalty_total, 3)
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("점검표 득점", f"{base}")
    r2.metric("가점", f"+{round(bonus_total, 2)}")
    r3.metric("감점", f"−{round(penalty_total, 2)}")
    r4.metric("🏆 종합점수", f"{final}")

    # 계산 근거를 표로도 남김 (보고서 첨부용 스크린샷 고려)
    with st.expander("📄 계산 내역 상세"):
        st.markdown(f"""
| 구분 | 내용 | 점수 |
|------|------|------|
| 점검표 득점 | ({s1} + {s2} + {s3}) ÷ 3 | {base} |
| 가점 | 선택 항목 합계 | +{round(bonus_total, 2)} |
| 감점 | 처분 건수 × 건당 감점 | −{round(penalty_total, 2)} |
| **종합점수** | | **{final}** |
""")


# ═══════════════════════════════════════════
# 📄 심사계획서 docx 다운로드 (신규, 2026-07)
# ═══════════════════════════════════════════
# python-docx 라이브러리가 필요합니다:
#   pip install python-docx
# 화면의 집계 결과를 그대로 공기업 보고서 양식의
# Word 문서로 변환해서 다운로드 버튼을 제공합니다.

def _render_docx_download(df: pd.DataFrame):
    """화면 상단에 심사계획서 다운로드 버튼을 표시합니다."""
    try:
        docx_bytes = _build_plan_docx(df)
    except ImportError:
        st.warning(
            "📄 문서 다운로드 기능을 쓰려면 python-docx 설치가 필요합니다: "
            "`pip install python-docx` 실행 후 재시작하세요."
        )
        return
    except Exception as e:
        logger.error(f"계획서 생성 오류: {e}")
        st.error(f"계획서 생성 중 오류: {e}")
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(
            "현재 데이터 기준으로 공통취약 TOP30 + 부서별 요약 + 배점기준이 "
            "포함된 심사계획서 초안을 Word 파일로 내려받습니다."
        )
    with col2:
        st.download_button(
            label="📄 심사계획서(docx) 다운로드",
            data=docx_bytes,
            file_name="자체종합안전심사_계획서_초안.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )


def _build_plan_docx(df: pd.DataFrame) -> bytes:
    """
    심사계획서 Word 문서를 생성해서 바이트로 반환합니다.

    문서 구성 (공기업 보고서 양식):
      제목 / □ 추진배경 / □ 공통취약 TOP30 표
      / □ 부서별 심사 우선순위 표 / □ 배점 기준(가점·감점 표)
    """
    import io
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    # ── 집계 (화면 탭과 동일한 로직: 전체기간, 최소 2건, TOP30) ──
    work = df.copy()
    work["_key"] = work["title"].apply(_norm_title)
    grouped = work.groupby("_key").agg(
        건수=("title", "size"),
        대표제목=("title", "first"),
        평균가중=("risk_w", "mean"),
        부서수=("department", "nunique") if "department" in work.columns else ("title", "size"),
    ).reset_index(drop=True)
    grouped = grouped[grouped["건수"] >= 2]
    grouped["우선순위점수"] = (grouped["건수"] * grouped["평균가중"]).round(1)
    grouped = grouped.sort_values(
        ["우선순위점수", "부서수"], ascending=False
    ).head(30).reset_index(drop=True)

    dept_summary = _build_dept_summary(df).head(15)

    # ── 문서 생성 ──
    doc = Document()

    # 기본 폰트를 맑은 고딕으로 (한글 문서 표준)
    style = doc.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.font.size = Pt(10)

    def heading(text, size=16, color=(0x1F, 0x38, 0x64)):
        """굵은 파란색 제목 단락을 추가하는 내부 도우미"""
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor(*color)
        return p

    def section(text):
        """□ 로 시작하는 소제목"""
        p = doc.add_paragraph()
        run = p.add_run(f"□ {text}")
        run.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x2E, 0x75, 0xB6)
        return p

    def bullet(text):
        p = doc.add_paragraph()
        run = p.add_run(f" ❍ {text}")
        run.font.size = Pt(10)
        return p

    def add_table(headers, rows):
        """머리행이 굵게 표시된 표를 추가하는 내부 도우미"""
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        for i, h in enumerate(headers):
            cell = table.rows[0].cells[i]
            cell.text = h
            for p in cell.paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(9)
        for row in rows:
            cells = table.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = str(v)
                for p in cells[i].paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(9)
        return table

    # ── 표지·제목 ──
    title = heading("자체종합안전심사 계획(안) — 중점 심사항목", 18)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub_run = sub.add_run("AX 안전관리 플랫폼(Safety-Audit) 데이터 분석 기반")
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # ── 추진배경 ──
    section("추진 배경")
    bullet(f"과거 심사이력 {len(df):,}건의 AI 분류·분석 결과를 바탕으로 금년도 중점 심사항목 도출")
    bullet("반복 지적 항목과 조치 미완료 건을 중심으로 형평성 있는 심사계획 수립")
    doc.add_paragraph()

    # ── 공통취약 TOP30 ──
    section("공통취약 항목 TOP30 (전 부서 공통 중점 심사항목 후보)")
    bullet("우선순위점수 = 반복건수 × 평균 리스크가중(상3/중2/하1)")
    rows = [
        [i + 1, r["대표제목"], f"{int(r['건수'])}건", f"{int(r['부서수'])}개",
         "전사공통" if r["부서수"] >= 2 else "단일부서", r["우선순위점수"]]
        for i, r in grouped.iterrows()
    ]
    add_table(["순위", "지적 항목", "반복건수", "관련부서", "범위", "우선순위점수"], rows)
    doc.add_paragraph()

    # ── 부서별 심사 우선순위 ──
    section("부서별 심사 우선순위 (리스크 가중점수 기준 상위 15개)")
    bullet("가중점수 = Σ리스크가중 + 반복항목수 × 2  (반복 지적은 2배 반영)")
    rows = [
        [i + 1, r["부서"], f"{r['총지적']}건", f"{r['시정명령']}건",
         f"{r['반복항목수']}개", f"{r['미완료']}건", r["가중점수"]]
        for i, r in dept_summary.iterrows()
    ]
    add_table(["순위", "부서", "총지적", "시정명령", "반복항목", "미완료", "가중점수"], rows)
    doc.add_paragraph()

    # ── 배점 기준 ──
    section("종합점수 배점 기준")
    bullet("종합점수 = [안전관리체계(100) + 안전보건관리(100) + 해당분야(100)] ÷ 3 + 가점 − 감점")
    bullet("안전보건관리 심사배점 강화(15%→33%)로 재해예방 중요성 향상 유도")
    doc.add_paragraph()

    p = doc.add_paragraph(); p.add_run("〈 가점 항목 〉").bold = True
    add_table(
        ["항목", "배점", "비고"],
        [[name, f"+{'/'.join(str(v) for v in opts if v > 0)}", desc]
         for name, opts, desc in BONUS_ITEMS]
    )
    doc.add_paragraph()

    p = doc.add_paragraph(); p.add_run("〈 감점 항목 〉").bold = True
    add_table(
        ["항목", "건당 감점", "비고"],
        [[name, f"−{per}", desc] for name, per, desc in PENALTY_ITEMS]
    )
    doc.add_paragraph()

    footer = doc.add_paragraph()
    f_run = footer.add_run("※ 본 문서는 Safety-Audit 플랫폼이 심사이력 데이터를 자동 집계하여 생성한 초안이며, 심사위원회 검토 후 확정합니다.")
    f_run.font.size = Pt(8)
    f_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    # ── 바이트로 변환해서 반환 ──
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()