# pages/page_analysis.py
# 통계 분석 화면

import streamlit as st
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path
from config.settings import PROCESSED_DIR
from core.action_analyzer import (
    add_action_status,
    action_summary,
    action_rate_by_group,
    consulting_targets,
)

# ─────────────────────────────────────────
# 한글 폰트 설정
# ─────────────────────────────────────────
def set_korean_font():
    font_candidates = [
        "C:/Windows/Fonts/malgun.ttf",    # 맑은 고딕
        "C:/Windows/Fonts/gulim.ttc",     # 굴림
        "C:/Windows/Fonts/batang.ttc",    # 바탕
    ]
    for font_path in font_candidates:
        if Path(font_path).exists():
            font = fm.FontProperties(fname=font_path)
            matplotlib.rc("font", family=font.get_name())
            matplotlib.rcParams["axes.unicode_minus"] = False
            return
    matplotlib.rcParams["axes.unicode_minus"] = False


def render():
    set_korean_font()

    st.title("📈 통계 분석")
    st.markdown("AI 분류 결과를 기반으로 파트별·연도별 트렌드를 분석합니다.")
    st.markdown("---")

    # ─────────────────────────────────────
    # 데이터 로드
    # ─────────────────────────────────────
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.error("❌ 데이터가 없습니다.")
        return

    df = pd.read_csv(csv_path, dtype=str)

    if "ai_part" not in df.columns:
        st.warning("⚠️ AI 분류가 완료되지 않았습니다. [AI 분류 실행] 메뉴를 먼저 실행하세요.")
        return

    # 미분류 제외
    df = df[df["ai_part"].notna()]
    df = df[df["ai_part"] != "미분류"]

    # 조치 이행상태 판정 컬럼 추가 (규칙 기반 — 즉시 처리)
    df = add_action_status(df)

    # ─────────────────────────────────────
    # 필터 옵션
    # ─────────────────────────────────────
    with st.expander("🔍 필터 옵션", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            years = sorted(df["year"].dropna().unique().tolist())
            selected_years = st.multiselect(
                "연도 선택",
                options=years,
                default=years
            )
        with col2:
            parts = sorted(df["ai_part"].unique().tolist())
            selected_parts = st.multiselect(
                "파트 선택",
                options=parts,
                default=parts
            )

    # 필터 적용
    df_filtered = df[
        df["year"].isin(selected_years) &
        df["ai_part"].isin(selected_parts)
    ]

    if df_filtered.empty:
        st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
        return

    st.caption(f"분석 대상: {len(df_filtered):,}건")
    st.markdown("---")

    # ─────────────────────────────────────
    # 탭 구성
    # ─────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 파트별 현황",
        "📅 연도별 트렌드",
        "⚠️ 리스크 분석",
        "🔁 반복 지적 TOP",
        "✅ 조치 이행실태"
    ])

    # ─────────────────────────────────
    with tab1:
        _render_part_analysis(df_filtered)

    with tab2:
        _render_trend_analysis(df_filtered)

    with tab3:
        _render_risk_analysis(df_filtered)

    with tab4:
        _render_repeat_analysis(df_filtered)

    with tab5:
        _render_action_analysis(df_filtered)


# ─────────────────────────────────────────
# Tab 1: 파트별 현황
# ─────────────────────────────────────────
def _render_part_analysis(df: pd.DataFrame):
    st.subheader("📊 파트별 지적사항 현황")

    col1, col2 = st.columns(2)

    with col1:
        # KPI 카드
        part_counts = df["ai_part"].value_counts()
        total = len(df)

        for part, count in part_counts.items():
            pct = count / total * 100
            icon = {"안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"}.get(part, "📋")
            st.metric(
                label=f"{icon} {part}",
                value=f"{count}건",
                delta=f"전체의 {pct:.1f}%"
            )

    with col2:
        # 파이차트
        fig, ax = plt.subplots(figsize=(5, 5))
        colors = ["#2196F3", "#4CAF50", "#FF9800"]
        wedges, texts, autotexts = ax.pie(
            part_counts.values,
            labels=part_counts.index,
            autopct="%1.1f%%",
            colors=colors[:len(part_counts)],
            startangle=90
        )
        for text in texts + autotexts:
            text.set_fontsize(11)
        ax.set_title("파트별 분포", fontsize=14, pad=15)
        st.pyplot(fig)
        plt.close()

    st.markdown("---")

    # 심사구분 × 파트 크로스탭
    st.subheader("심사구분 × 파트 분포")
    if "audit_type" in df.columns:
        cross = pd.crosstab(df["audit_type"], df["ai_part"])
        st.dataframe(cross, use_container_width=True)

        fig2, ax2 = plt.subplots(figsize=(8, 4))
        cross.plot(kind="bar", ax=ax2, color=colors[:3])
        ax2.set_title("심사구분별 파트 분포", fontsize=13)
        ax2.set_xlabel("심사구분")
        ax2.set_ylabel("건수")
        ax2.legend(title="파트")
        plt.xticks(rotation=0)
        plt.tight_layout()
        st.pyplot(fig2)
        plt.close()


# ─────────────────────────────────────────
# Tab 2: 연도별 트렌드
# ─────────────────────────────────────────
def _render_trend_analysis(df: pd.DataFrame):
    st.subheader("📅 연도별 트렌드")

    if "year" not in df.columns:
        st.info("연도 데이터가 없습니다.")
        return

    # 연도별 × 파트별 건수
    trend = df.groupby(["year", "ai_part"]).size().unstack(fill_value=0)

    st.dataframe(trend, use_container_width=True)

    # 꺾은선 차트
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = {"안전계획": "#2196F3", "안전보건": "#4CAF50", "재난안전": "#FF9800"}

    for part in trend.columns:
        ax.plot(
            trend.index,
            trend[part],
            marker="o",
            linewidth=2,
            label=part,
            color=colors.get(part, "#999")
        )
        # 값 표시
        for x, y in zip(trend.index, trend[part]):
            ax.annotate(
                str(y),
                (x, y),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=9
            )

    ax.set_title("연도별 파트별 지적사항 추이", fontsize=14)
    ax.set_xlabel("연도")
    ax.set_ylabel("건수")
    ax.legend(title="파트")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()

    # 연도별 총계
    st.markdown("#### 연도별 총 지적사항")
    year_total = df.groupby("year").size().reset_index(name="총건수")
    st.bar_chart(year_total.set_index("year"))


# ─────────────────────────────────────────
# Tab 3: 리스크 분석
# ─────────────────────────────────────────
def _render_risk_analysis(df: pd.DataFrame):
    st.subheader("⚠️ 리스크 등급 분석")

    if "ai_risk" not in df.columns:
        st.info("리스크 데이터가 없습니다.")
        return

    col1, col2 = st.columns(2)

    with col1:
        risk_counts = df["ai_risk"].value_counts()
        for risk, count in risk_counts.items():
            color = {"상": "🔴", "중": "🟡", "하": "🟢"}.get(risk, "⚪")
            st.metric(f"{color} 리스크 {risk}", f"{count}건")

    with col2:
        fig, ax = plt.subplots(figsize=(5, 5))
        risk_colors = {"상": "#F44336", "중": "#FFC107", "하": "#4CAF50"}
        colors = [risk_colors.get(r, "#999") for r in risk_counts.index]
        ax.pie(
            risk_counts.values,
            labels=risk_counts.index,
            autopct="%1.1f%%",
            colors=colors,
            startangle=90
        )
        ax.set_title("리스크 등급 분포", fontsize=14)
        st.pyplot(fig)
        plt.close()

    st.markdown("---")

    # 파트별 리스크 분포
    st.subheader("파트별 리스크 분포")
    if "ai_part" in df.columns:
        risk_cross = pd.crosstab(df["ai_part"], df["ai_risk"])
        # 상/중/하 순서 정렬
        order = [c for c in ["상", "중", "하"] if c in risk_cross.columns]
        risk_cross = risk_cross[order]
        st.dataframe(risk_cross, use_container_width=True)

        fig2, ax2 = plt.subplots(figsize=(8, 4))
        risk_cross.plot(
            kind="bar",
            ax=ax2,
            color=[risk_colors.get(c, "#999") for c in order]
        )
        ax2.set_title("파트별 리스크 등급 분포", fontsize=13)
        ax2.set_xlabel("파트")
        ax2.set_ylabel("건수")
        ax2.legend(title="리스크")
        plt.xticks(rotation=0)
        plt.tight_layout()
        st.pyplot(fig2)
        plt.close()


# ─────────────────────────────────────────
# Tab 4: 반복 지적 TOP
# ─────────────────────────────────────────
def _render_repeat_analysis(df: pd.DataFrame):
    st.subheader("🔁 반복 지적사항 TOP 10")
    st.caption("제목이 유사한 지적사항이 반복되는 항목을 분석합니다.")

    if "title" not in df.columns:
        st.info("제목 데이터가 없습니다.")
        return

    # 제목 빈도 분석
    title_counts = (
        df.groupby(["title", "ai_part"])
        .size()
        .reset_index(name="반복횟수")
        .sort_values("반복횟수", ascending=False)
        .head(10)
    )

    if title_counts.empty:
        st.info("반복 지적사항이 없습니다.")
        return

    # 색상 강조
    def highlight_repeat(val):
        if isinstance(val, int):
            if val >= 3:
                return "background-color: #FFCDD2"
            elif val >= 2:
                return "background-color: #FFF9C4"
        return ""

    st.dataframe(
        title_counts.style.map(
            highlight_repeat,
            subset=["반복횟수"]
        ),
        use_container_width=True,
        hide_index=True
    )

    # 막대 차트
    fig, ax = plt.subplots(figsize=(10, 5))
    colors_bar = [
        "#F44336" if c >= 3 else "#FFC107" if c >= 2 else "#4CAF50"
        for c in title_counts["반복횟수"]
    ]
    bars = ax.barh(
        title_counts["title"].str[:20],
        title_counts["반복횟수"],
        color=colors_bar
    )
    ax.set_title("반복 지적사항 TOP 10", fontsize=13)
    ax.set_xlabel("반복 횟수")

    # 값 표시
    for bar, val in zip(bars, title_counts["반복횟수"]):
        ax.text(
            bar.get_width() + 0.05,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            fontsize=10
        )

    plt.tight_layout()
    st.pyplot(fig)
    plt.close()

    st.markdown("---")

    # 부서별 지적 빈도
    st.subheader("🏢 부서별 지적사항 빈도 TOP 10")
    _render_dept_freq(df)


def _render_dept_freq(df: pd.DataFrame):
    if "department" in df.columns:
        dept_counts = (
            df["department"]
            .value_counts()
            .head(10)
            .reset_index()
        )
        dept_counts.columns = ["부서명", "건수"]
        st.dataframe(dept_counts, use_container_width=True, hide_index=True)

        fig3, ax3 = plt.subplots(figsize=(10, 5))
        ax3.barh(
            dept_counts["부서명"],
            dept_counts["건수"],
            color="#2196F3"
        )
        ax3.set_title("부서별 지적사항 TOP 10", fontsize=13)
        ax3.set_xlabel("건수")
        plt.tight_layout()
        st.pyplot(fig3)
        plt.close()


# ─────────────────────────────────────────
# Tab 5: 조치 이행실태 (신규, 2026-07)
# ─────────────────────────────────────────
def _render_action_analysis(df: pd.DataFrame):
    """
    추진실적 텍스트를 판정한 조치상태(완료/형식적/진행중/미확인)를 기반으로
    전체 이행률, 부서별·파트별·연도별 이행률, 컨설팅 우선 대상을 표시합니다.
    """
    st.subheader("✅ 조치 이행실태 분석")
    st.caption(
        "추진실적 기록을 자동 판정한 결과입니다. "
        "'형식적'은 \"조치완료\" 한 줄 등 내용 없는 완료 처리로, 실질 이행 확인이 필요합니다."
    )

    if "action_status" not in df.columns:
        st.info("추진실적 데이터가 없습니다.")
        return

    # ── 전체 요약 KPI
    summary = action_summary(df)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("📋 전체", f"{summary['total']}건")
    col2.metric("✅ 완료", f"{summary['완료']}건")
    col3.metric("📝 형식적 완료", f"{summary['형식적']}건",
                delta="실질 확인 필요" if summary['형식적'] > 0 else None,
                delta_color="inverse" if summary['형식적'] > 0 else "off")
    col4.metric("🔄 진행중", f"{summary['진행중']}건")
    col5.metric("❓ 미확인", f"{summary['미확인']}건")

    st.metric("🎯 이행률 (완료 ÷ 전체)", f"{summary['이행률']}%")
    st.markdown("---")

    # ── 부서별 이행률 (이행률 낮은 순 — 컨설팅 우선 대상이 위)
    st.markdown("#### 🏢 부서별 이행률 (낮은 순)")
    dept_rate = action_rate_by_group(df, "department")
    if not dept_rate.empty:
        dept_rate_display = dept_rate.rename(columns={"department": "부서"})
        st.dataframe(dept_rate_display, use_container_width=True, hide_index=True)
    else:
        st.info("부서 데이터가 없습니다.")

    # ── 파트별 / 연도별 이행률
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 파트별 이행률")
        part_rate = action_rate_by_group(df, "ai_part")
        if not part_rate.empty:
            st.dataframe(
                part_rate.rename(columns={"ai_part": "파트"}),
                use_container_width=True, hide_index=True
            )
    with col_b:
        st.markdown("#### 연도별 이행률")
        year_rate = action_rate_by_group(df, "year")
        if not year_rate.empty:
            st.dataframe(
                year_rate.rename(columns={"year": "연도"}).sort_values("연도"),
                use_container_width=True, hide_index=True
            )

    st.markdown("---")

    # ── 컨설팅 우선 대상 부서
    st.markdown("#### 🎯 컨설팅 우선 대상 부서")
    st.caption("지적 3건 이상 + 이행률 60% 이하 부서 — 지적 감소 컨설팅이 가장 시급한 곳입니다.")
    targets = consulting_targets(df)
    if not targets.empty:
        st.dataframe(
            targets.rename(columns={"department": "부서"}),
            use_container_width=True, hide_index=True
        )
    else:
        st.success("✅ 컨설팅 우선 대상 기준에 해당하는 부서가 없습니다.")

    # ── 미확인/형식적 상세 목록
    with st.expander("📝 형식적 완료 / 미확인 건 상세 보기"):
        problem_df = df[df["action_status"].isin(["형식적", "미확인"])]
        if problem_df.empty:
            st.info("해당 건이 없습니다.")
        else:
            cols = [c for c in ["year", "department", "title", "action_result", "action_status"]
                    if c in problem_df.columns]
            show = problem_df[cols].rename(columns={
                "year": "연도", "department": "부서", "title": "지적사항",
                "action_result": "추진실적", "action_status": "조치상태",
            })
            st.dataframe(show, use_container_width=True, hide_index=True)