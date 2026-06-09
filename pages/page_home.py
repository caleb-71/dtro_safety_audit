# pages/page_home.py
# 홈 대시보드 - 다년도 데이터 대응 버전

import streamlit as st
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path
from config.settings import PROCESSED_DIR

# ─────────────────────────────────────────
# 색상 / 폰트 설정
# ─────────────────────────────────────────
PART_COLORS = {
    "안전계획": "#2196F3",
    "안전보건": "#4CAF50",
    "재난안전": "#FF9800",
}
RISK_COLORS = {
    "상": "#F44336",
    "중": "#FFC107",
    "하": "#4CAF50",
}

def set_korean_font():
    candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        "C:/Windows/Fonts/batang.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            font = fm.FontProperties(fname=path)
            matplotlib.rc("font", family=font.get_name())
            matplotlib.rcParams["axes.unicode_minus"] = False
            return


def render():
    set_korean_font()

    # ─────────────────────────────────────
    # 헤더
    # ─────────────────────────────────────
    st.title("🚇 DTRO 자체종합안전심사 AI 시스템")
    st.markdown("##### 철도안전관리체계 기반 AI 분석 플랫폼")
    st.markdown("---")

    # ─────────────────────────────────────
    # 데이터 로드
    # ─────────────────────────────────────
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.warning("⚠️ 데이터가 없습니다. [데이터 업로드] 메뉴에서 업로드하세요.")
        _show_guide()
        return

    df = pd.read_csv(csv_path, dtype=str)

    # 연도 정수 변환
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df = df.dropna(subset=["year"])
        df["year"] = df["year"].astype(int)

    # AI 분류 여부
    ai_done = "ai_part" in df.columns and df["ai_part"].notna().sum() > 0

    # ─────────────────────────────────────
    # 연도 선택 필터 (다년도 대비)
    # ─────────────────────────────────────
    if "year" in df.columns:
        years = sorted(df["year"].unique(), reverse=True)
        year_options = ["전체"] + [str(y) for y in years]

        col_filter, _ = st.columns([2, 6])
        with col_filter:
            selected_year = st.selectbox(
                "📅 연도 선택",
                options=year_options,
                index=0
            )

        if selected_year == "전체":
            df_view = df.copy()
            year_label = "전체 연도"
        else:
            df_view = df[df["year"] == int(selected_year)].copy()
            year_label = f"{selected_year}년"
    else:
        df_view = df.copy()
        year_label = "전체"

    st.caption(f"현재 보기: {year_label} | 총 {len(df_view):,}건")
    st.markdown("---")

    # ─────────────────────────────────────
    # KPI 카드
    # ─────────────────────────────────────
    st.subheader("📌 전체 현황")
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("총 지적사항", f"{len(df_view):,}건")

    with col2:
        if "audit_type" in df_view.columns:
            cnt = len(df_view[df_view["audit_type"] == "시정명령"])
            st.metric("🔴 시정명령", f"{cnt}건", delta="최우선 조치", delta_color="inverse")

    with col3:
        if "audit_type" in df_view.columns:
            cnt = len(df_view[df_view["audit_type"] == "개선권고"])
            st.metric("🟡 개선권고", f"{cnt}건")

    with col4:
        if "audit_type" in df_view.columns:
            cnt = len(df_view[df_view["audit_type"] == "현지시정"])
            st.metric("🟢 현지시정", f"{cnt}건")

    with col5:
        if ai_done:
            classified = df_view["ai_part"].notna().sum()
            total = len(df_view)
            pct = classified / total * 100 if total > 0 else 0
            st.metric("🤖 AI 분류율", f"{pct:.1f}%")
        else:
            st.metric("🤖 AI 분류율", "미실행")

    st.markdown("---")

    # ─────────────────────────────────────
    # AI 분류 현황 + 연도별 현황
    # ─────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("🤖 AI 분류 현황")
        if ai_done:
            _render_part_chart(df_view)
        else:
            st.info("AI 분류가 실행되지 않았습니다.")
            st.markdown("👉 **[AI 분류 실행]** 메뉴로 이동하세요")

    with col_right:
        st.subheader("📅 연도별 지적사항 추이")
        if "year" in df.columns:
            _render_yearly_trend(df, ai_done)

    st.markdown("---")

    # ─────────────────────────────────────
    # 파트별 리스크 현황 (AI 분류 완료 시)
    # ─────────────────────────────────────
    if ai_done:
        st.subheader("⚠️ 파트별 리스크 현황")
        _render_risk_summary(df_view)
        st.markdown("---")

    # ─────────────────────────────────────
    # 최근 지적사항 미리보기
    # ─────────────────────────────────────
    st.subheader("📋 최근 지적사항 미리보기")
    _render_preview(df_view, ai_done)


# ─────────────────────────────────────────
# 파트별 분포 차트
# ─────────────────────────────────────────
def _render_part_chart(df: pd.DataFrame):
    # 미분류 제외
    df_clean = df[
        df["ai_part"].notna() &
        (df["ai_part"] != "미분류")
    ]

    if df_clean.empty:
        st.info("분류 데이터가 없습니다.")
        return

    part_counts = df_clean["ai_part"].value_counts()
    total = len(df_clean)

    # 진행률 표시
    classified = len(df_clean)
    all_total  = len(df)
    st.progress(classified / all_total if all_total > 0 else 0)
    st.caption(f"{classified}/{all_total}건 분류 완료")

    # 파트별 색상 막대 차트
    fig, ax = plt.subplots(figsize=(5, 3))
    parts  = list(part_counts.index)
    counts = list(part_counts.values)
    colors = [PART_COLORS.get(p, "#999") for p in parts]

    bars = ax.bar(parts, counts, color=colors, edgecolor="white", linewidth=1.5)

    # 막대 위 숫자 + 퍼센트
    for bar, count in zip(bars, counts):
        pct = count / total * 100
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{count}건\n({pct:.1f}%)",
            ha="center", va="bottom", fontsize=9
        )

    ax.set_title("파트별 분류 현황", fontsize=12)
    ax.set_ylabel("건수")
    ax.set_ylim(0, max(counts) * 1.3)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()


# ─────────────────────────────────────────
# 연도별 트렌드 (다년도 대비)
# ─────────────────────────────────────────
def _render_yearly_trend(df: pd.DataFrame, ai_done: bool):
    if ai_done:
        # 파트별 색상 구분 꺾은선
        df_clean = df[
            df["ai_part"].notna() &
            (df["ai_part"] != "미분류")
        ]
        if df_clean.empty:
            return

        trend = (
            df_clean.groupby(["year", "ai_part"])
            .size()
            .unstack(fill_value=0)
        )

        fig, ax = plt.subplots(figsize=(5, 3))
        for part in trend.columns:
            ax.plot(
                trend.index.astype(str),
                trend[part],
                marker="o",
                linewidth=2,
                label=part,
                color=PART_COLORS.get(part, "#999")
            )

        ax.set_title("연도별 파트별 추이", fontsize=12)
        ax.set_xlabel("연도")
        ax.set_ylabel("건수")
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close()

    else:
        # AI 분류 전: 단순 연도별 막대
        year_counts = df.groupby("year").size().reset_index(name="건수")

        fig, ax = plt.subplots(figsize=(5, 3))
        ax.bar(
            year_counts["year"].astype(str),
            year_counts["건수"],
            color="#2196F3"
        )
        ax.set_title("연도별 지적사항 건수", fontsize=12)
        ax.set_ylabel("건수")
        ax.grid(axis="y", alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close()


# ─────────────────────────────────────────
# 파트별 리스크 요약
# ─────────────────────────────────────────
def _render_risk_summary(df: pd.DataFrame):
    if "ai_risk" not in df.columns:
        return

    df_clean = df[
        df["ai_part"].notna() &
        (df["ai_part"] != "미분류")
    ]

    parts = ["안전계획", "안전보건", "재난안전"]
    cols  = st.columns(3)

    for col, part in zip(cols, parts):
        with col:
            df_part = df_clean[df_clean["ai_part"] == part]
            icon = {"안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"}.get(part)

            st.markdown(f"**{icon} {part}** ({len(df_part)}건)")

            if df_part.empty:
                st.caption("데이터 없음")
                continue

            risk_counts = df_part["ai_risk"].value_counts()

            # 미니 리스크 바
            fig, ax = plt.subplots(figsize=(3, 1.5))
            risks  = [r for r in ["상", "중", "하"] if r in risk_counts.index]
            values = [risk_counts.get(r, 0) for r in risks]
            colors = [RISK_COLORS.get(r, "#999") for r in risks]

            bars = ax.barh(risks, values, color=colors)
            for bar, val in zip(bars, values):
                ax.text(
                    bar.get_width() + 0.1,
                    bar.get_y() + bar.get_height() / 2,
                    str(val),
                    va="center", fontsize=9
                )

            ax.set_xlim(0, max(values) * 1.4 if values else 1)
            ax.grid(axis="x", alpha=0.3)
            plt.tight_layout()
            st.pyplot(fig)
            plt.close()


# ─────────────────────────────────────────
# 최근 지적사항 미리보기
# ─────────────────────────────────────────
def _render_preview(df: pd.DataFrame, ai_done: bool):
    preview_cols = ["year", "audit_type", "title", "department"]
    if ai_done:
        preview_cols += ["ai_part", "ai_risk"]

    available = [c for c in preview_cols if c in df.columns]
    col_labels = {
        "year":       "연도",
        "audit_type": "심사구분",
        "title":      "제목",
        "department": "담당부서",
        "ai_part":    "AI분류",
        "ai_risk":    "리스크",
    }

    # 최신순 정렬
    sort_col = "year" if "year" in df.columns else None
    if sort_col:
        display_df = (
            df[available]
            .sort_values(sort_col, ascending=False)
            .head(10)
            .copy()
        )
    else:
        display_df = df[available].head(10).copy()

    display_df.columns = [col_labels.get(c, c) for c in available]
    st.dataframe(display_df, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────
# 시작 가이드 (데이터 없을 때)
# ─────────────────────────────────────────
def _show_guide():
    st.markdown("---")
    st.subheader("🚀 시작 가이드")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**Step 1** 📁\n\n데이터 업로드\n\n연도별 엑셀 파일을 업로드하세요")
    with col2:
        st.info("**Step 2** 🤖\n\nAI 분류 실행\n\nllama3.1이 3개 파트로 분류합니다")
    with col3:
        st.info("**Step 3** 📄\n\n보고서 생성\n\n분석 결과를 보고서로 출력합니다")