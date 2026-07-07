# app.py

import streamlit as st

st.set_page_config(
    page_title="DTRO 종합안전심사 AI",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🚇 DTRO")
    st.markdown("### 안전심사 AI 시스템")
    st.markdown("---")

    menu = st.radio(
        "메뉴 선택",
        options=[
            "📊 홈 대시보드",
            "📁 데이터 업로드",
            "🤖 AI 분류 실행",
            "📈 통계 분석",
            "📄 보고서 생성",
            "💬 AI 질의응답",
            "📋 현장 심사 도우미",
            "⚖️ 법령/규정 관리",
            "🏢 부서별 심사 조회",   # ← 신규
        ],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption("Python 3.11.9 | Streamlit")

    # AI 연결 모드 표시 (config/settings.py 의 OLLAMA_MODE 로 전환)
    from config.settings import OLLAMA_MODE, OLLAMA_MODEL, NETWORK_LLM_MODEL, NETWORK_LLM_URL
    if OLLAMA_MODE == "network":
        st.caption(f"AI: {NETWORK_LLM_MODEL} (사내망 서버)")
        st.caption(f"서버: {NETWORK_LLM_URL}")
    else:
        st.caption(f"AI: {OLLAMA_MODEL} (로컬)")

    if st.button("🔌 AI 연결 확인", use_container_width=True):
        from core.llm_client import llm_status
        status = llm_status()
        if status["ok"]:
            st.success(status["detail"])
        else:
            st.error(status["detail"])

# ── 라우팅
if menu == "📊 홈 대시보드":
    from pages.page_home import render
    render()

elif menu == "📁 데이터 업로드":
    from pages.page_upload import render
    render()

elif menu == "🤖 AI 분류 실행":
    from pages.page_classify import render
    render()

elif menu == "📈 통계 분석":
    from pages.page_analysis import render
    render()

elif menu == "📄 보고서 생성":
    from pages.page_report import render
    render()

elif menu == "💬 AI 질의응답":
    from pages.page_chat import render
    render()

elif menu == "📋 현장 심사 도우미":
    from pages.page_field import render
    render()

elif menu == "⚖️ 법령/규정 관리":
    from pages.page_legal import render
    render()

elif menu == "🏢 부서별 심사 조회":   # ← 신규
    from pages.page_dept import render
    render()