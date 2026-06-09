# pages/page_report.py
# 보고서 생성 화면

import streamlit as st
import pandas as pd
from pathlib import Path
from config.settings import PROCESSED_DIR, OUTPUT_DIR
from output.excel_writer import save_classified_excel
from output.report_builder import build_report


def render():
    st.title("📄 보고서 생성")
    st.markdown("AI 분석 결과를 엑셀 및 워드 보고서로 출력합니다.")
    st.markdown("---")

    # 데이터 로드
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        st.error("❌ 데이터가 없습니다. [데이터 업로드] 메뉴에서 먼저 업로드하세요.")
        return

    df = pd.read_csv(csv_path, dtype=str)

    if "ai_part" not in df.columns:
        st.warning("⚠️ AI 분류가 완료되지 않았습니다. [AI 분류 실행] 메뉴를 먼저 실행하세요.")
        return

    # 현황 요약
    total      = len(df)
    classified = df["ai_part"].notna().sum()
    st.success(f"✅ {classified:,}건 AI 분류 완료 — 보고서 생성 준비됨")

    col1, col2, col3 = st.columns(3)
    part_counts = df["ai_part"].value_counts()
    with col1:
        st.metric("🚇 안전계획", f"{part_counts.get('안전계획', 0)}건")
    with col2:
        st.metric("🏥 안전보건", f"{part_counts.get('안전보건', 0)}건")
    with col3:
        st.metric("🌪️ 재난안전", f"{part_counts.get('재난안전', 0)}건")

    st.markdown("---")

    # 보고서 1: 엑셀
    st.subheader("📊 보고서 1 — 분류 결과 엑셀")
    st.caption("AI 분류 결과 전체를 엑셀 파일로 저장합니다.")

    if st.button(
        "📥 엑셀 파일 생성",
        type="secondary",
        use_container_width=True
    ):
        with st.spinner("엑셀 생성 중..."):
            excel_path = save_classified_excel(df)
            st.success(f"✅ 엑셀 저장 완료!")
            st.code(str(excel_path))

            # 다운로드 버튼
            with open(excel_path, "rb") as f:
                st.download_button(
                    label="⬇️ 엑셀 다운로드",
                    data=f.read(),
                    file_name=excel_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

    st.markdown("---")

    # 보고서 2: 워드
    st.subheader("📝 보고서 2 — AI 분석 결과 보고서 (워드)")
    st.caption("2025년 자체종합안전심사 AI 분석 결과 보고서를 워드 파일로 생성합니다.")

    st.info("""
    📋 보고서 구성
    - 제1장: 분석 개요
    - 제2장: AI 분류 결과 요약 (차트 포함)
    - 제3장: 파트별 세부 분석
    - 제4장: 리스크 등급 분석
    - 제5장: 반복 지적사항 분석
    - 제6장: 올해 집중 점검 권고사항
    """)

    if st.button(
        "📝 워드 보고서 생성",
        type="primary",
        use_container_width=True
    ):
        with st.spinner("보고서 생성 중... (약 30초 소요)"):
            try:
                report_path = build_report(df)
                st.success("✅ 보고서 생성 완료!")
                st.code(str(report_path))

                # 다운로드 버튼
                with open(report_path, "rb") as f:
                    st.download_button(
                        label="⬇️ 워드 보고서 다운로드",
                        data=f.read(),
                        file_name=report_path.name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"❌ 보고서 생성 오류: {e}")
                st.exception(e)