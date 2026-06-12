# pages/page_legal.py
# ⚖️ 법령/규정 관리 화면
# PDF 업로드, 벡터DB 구축, 법령 검색

import streamlit as st
from pathlib import Path
from config.settings import LEGAL_DOCS_DIR, LEGAL_CATEGORIES
from data.legal_store import (
    build_legal_store,
    get_legal_store_status,
    get_pdf_file_list,
    search_legal,
)
from core.legal_engine import find_legal_basis, quick_legal_search


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("⚖️ 법령/규정 관리")
    st.markdown("PDF 법령·규정을 등록하고 지적사항 근거를 검색합니다.")
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs([
        "📂 문서 관리",
        "🔍 법령 검색",
        "⚡ 근거 자동 생성",
    ])

    with tab1:
        _render_doc_manager()

    with tab2:
        _render_legal_search()

    with tab3:
        _render_basis_generator()


# ─────────────────────────────────────────
# Tab 1: 문서 관리
# ─────────────────────────────────────────
def _render_doc_manager():
    st.subheader("📂 법령/규정 문서 관리")

    # 현재 법령DB 상태
    status = get_legal_store_status()

    col1, col2, col3 = st.columns(3)
    with col1:
        if status["ready"]:
            st.metric("📚 법령DB 상태", "구축 완료 ✅")
        else:
            st.metric("📚 법령DB 상태", "미구축 ⚠️")
    with col2:
        st.metric("📄 총 파일 수", f"{status['total_files']}개")
    with col3:
        st.metric("🔢 총 청크 수", f"{status['total_chunks']:,}개")

    st.markdown("---")

    # PDF 파일 목록
    st.subheader("📁 등록된 PDF 파일 목록")
    file_list = get_pdf_file_list()

    total_files = 0
    for cat_en, info in file_list.items():
        cat_ko = info["name_ko"]
        files  = info["files"]
        count  = info["count"]
        total_files += count

        with st.expander(
            f"📁 {cat_ko} ({cat_en}) — {count}개 파일",
            expanded=(count > 0)
        ):
            if not files:
                st.info(
                    f"파일이 없습니다.\n"
                    f"경로: data/legal_docs/{cat_en}/"
                )
            else:
                for fname in files:
                    col1, col2 = st.columns([5, 1])
                    col1.write(f"📄 {fname}")
                    if col2.button(
                        "🗑️",
                        key=f"del_{cat_en}_{fname}",
                        help="파일 삭제"
                    ):
                        _delete_pdf(cat_en, fname)

    st.caption(f"총 {total_files}개 파일 등록됨")
    st.markdown("---")

    # PDF 업로드
    st.subheader("📤 PDF 파일 업로드")

    col1, col2 = st.columns([2, 4])
    with col1:
        upload_cat = st.selectbox(
            "분류 선택",
            options=list(LEGAL_CATEGORIES.keys()),
            format_func=lambda x: f"{LEGAL_CATEGORIES[x]} ({x})",
            key="upload_category"
        )
    with col2:
        uploaded = st.file_uploader(
            "PDF 파일 선택",
            type=["pdf"],
            accept_multiple_files=True,
            key="legal_uploader"
        )

    if uploaded:
        if st.button(
            f"💾 {LEGAL_CATEGORIES[upload_cat]}에 저장",
            type="secondary",
            use_container_width=True,
            key="btn_save_pdf"
        ):
            _save_pdfs(uploaded, upload_cat)

    st.markdown("---")

    # 법령DB 구축
    st.subheader("🔧 법령 벡터DB 구축")
    st.caption(
        "등록된 모든 PDF를 읽어 AI가 검색할 수 있도록 벡터화합니다. "
        "파일 추가 후 반드시 재구축하세요."
    )

    est_time = total_files * 30
    st.info(
        f"⏱️ 예상 소요 시간: 약 {est_time//60}분 "
        f"({total_files}개 × 약 30초/파일)"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "🔧 법령DB 구축 시작",
            type="primary",
            use_container_width=True,
            disabled=total_files == 0,
            key="btn_build_legal"
        ):
            _build_legal_db()

    with col2:
        if st.button(
            "🔄 법령DB 재구축",
            use_container_width=True,
            disabled=not status["ready"],
            key="btn_rebuild_legal"
        ):
            _build_legal_db()

    # 파일별 청크 현황
    if status["ready"] and status["files"]:
        st.markdown("---")
        st.subheader("📊 파일별 구축 현황")
        for fname, info in status["files"].items():
            col1, col2, col3 = st.columns([5, 2, 2])
            col1.write(f"📄 {fname}")
            col2.write(info["category"])
            col3.write(f"{info['chunks']}개 청크")


# ─────────────────────────────────────────
# Tab 2: 법령 검색
# ─────────────────────────────────────────
def _render_legal_search():
    st.subheader("🔍 법령/규정 검색")
    st.caption("키워드로 관련 법령/규정 조항을 검색합니다.")

    status = get_legal_store_status()
    if not status["ready"]:
        st.warning("⚠️ 법령DB가 구축되지 않았습니다. [문서 관리] 탭에서 먼저 구축하세요.")
        return

    col1, col2, col3 = st.columns([4, 2, 2])
    with col1:
        query = st.text_input(
            "검색어",
            placeholder="예: TBM 작업전 안전점검, MSDS, 비상대응훈련...",
            key="legal_search_query"
        )
    with col2:
        filter_cat = st.selectbox(
            "분류 필터",
            ["전체"] + list(LEGAL_CATEGORIES.keys()),
            format_func=lambda x: (
                "전체" if x == "전체"
                else f"{LEGAL_CATEGORIES[x]}"
            ),
            key="legal_filter_cat"
        )
    with col3:
        top_k = st.selectbox(
            "결과 수",
            [3, 5, 10],
            key="legal_top_k"
        )

    if st.button(
        "🔍 법령 검색",
        type="primary",
        use_container_width=True,
        key="btn_legal_search"
    ):
        if not query.strip():
            st.warning("검색어를 입력하세요.")
            return

        with st.spinner("법령 검색 중..."):
            results = search_legal(
                query_text=query,
                top_k=top_k,
                filter_category=(
                    filter_cat if filter_cat != "전체" else None
                ),
            )

        if not results:
            st.info("관련 법령/규정을 찾을 수 없습니다.")
            return

        st.success(f"✅ {len(results)}건 검색됨")

        for i, result in enumerate(results, 1):
            meta  = result.get("metadata", {})
            text  = result.get("text", "")
            sim   = result.get("similarity", 0)
            fname = meta.get("file_stem", "")
            cat   = meta.get("category_ko", "")

            with st.expander(
                f"{i}. 📄 {fname} ({cat}) — 관련도 {sim:.0%}",
                expanded=(i == 1)
            ):
                st.write(text)
                st.caption(f"파일: {meta.get('file_name', '')} | "
                           f"청크: {meta.get('chunk_index', '')}"
                           f"/{meta.get('total_chunks', '')}")


# ─────────────────────────────────────────
# Tab 3: 근거 자동 생성
# ─────────────────────────────────────────
def _render_basis_generator():
    st.subheader("⚡ 지적사항 법령 근거 자동 생성")
    st.caption(
        "지적사항을 입력하면 관련 법령/규정을 찾아 "
        "근거 문장을 자동으로 생성합니다."
    )

    status = get_legal_store_status()
    if not status["ready"]:
        st.warning("⚠️ 법령DB가 구축되지 않았습니다.")
        return

    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input(
            "지적사항 제목",
            placeholder="예: TBM 작업전 안전점검회의 시행 미흡",
            key="basis_title"
        )
        audit_type = st.selectbox(
            "심사구분",
            ["개선권고", "현지시정", "시정명령"],
            key="basis_audit"
        )
    with col2:
        problem = st.text_area(
            "현황 및 문제점",
            placeholder="상세 내용 입력 시 더 정확한 근거가 생성됩니다.",
            height=120,
            key="basis_problem"
        )

    if st.button(
        "⚡ 법령 근거 생성",
        type="primary",
        use_container_width=True,
        key="btn_gen_basis"
    ):
        if not title.strip():
            st.warning("지적사항 제목을 입력하세요.")
            return

        with st.spinner("관련 법령을 찾고 근거를 생성 중..."):
            result = find_legal_basis(
                title=title,
                problem=problem,
                audit_type=audit_type,
                top_k=3
            )

        if not result["found"]:
            st.warning("관련 법령/규정을 찾을 수 없습니다.")
            return

        # 생성된 근거 표시
        st.success("✅ 법령 근거 생성 완료!")

        st.subheader("📋 생성된 법령 근거")
        st.info(result["basis"])

        # 참고 출처
        if result["sources"]:
            st.subheader("📚 참고 출처")
            for src in result["sources"]:
                st.write(f"• {src}")

        # 상세 검색 결과
        with st.expander("🔍 관련 법령 원문 보기"):
            for i, r in enumerate(result["results"], 1):
                meta = r.get("metadata", {})
                sim  = r.get("similarity", 0)
                st.markdown(
                    f"**{i}. {meta.get('file_stem','')} "
                    f"({meta.get('category_ko','')}) "
                    f"— 관련도 {sim:.0%}**"
                )
                st.write(r.get("text", "")[:500])
                st.divider()

        # 복사용 텍스트
        st.subheader("📋 복사용 텍스트")
        copy_text = (
            f"【지적사항】{title}\n\n"
            f"【법령 근거】{result['basis']}\n\n"
            f"【참고 문서】{', '.join(result['sources'])}"
        )
        st.code(copy_text, language=None)


# ─────────────────────────────────────────
# 내부 함수
# ─────────────────────────────────────────
def _save_pdfs(uploaded_files, category: str):
    """PDF 파일 저장"""
    save_dir = LEGAL_DOCS_DIR / category
    save_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in uploaded_files:
        save_path = save_dir / f.name
        with open(save_path, "wb") as out:
            out.write(f.getbuffer())
        saved.append(f.name)

    st.success(f"✅ {len(saved)}개 파일 저장 완료!")
    st.caption("저장 후 법령DB를 재구축하세요.")
    st.rerun()


def _delete_pdf(category: str, filename: str):
    """PDF 파일 삭제"""
    file_path = LEGAL_DOCS_DIR / category / filename
    try:
        file_path.unlink()
        st.success(f"✅ {filename} 삭제 완료")
        st.caption("법령DB를 재구축하세요.")
        st.rerun()
    except Exception as e:
        st.error(f"❌ 삭제 실패: {e}")


def _build_legal_db():
    """법령DB 구축 실행"""
    progress_bar = st.progress(0)
    status_text  = st.empty()

    def update(current, total, fname):
        progress_bar.progress(current / total)
        status_text.text(f"처리 중 ({current}/{total}): {fname}")

    with st.spinner("법령 벡터DB 구축 중..."):
        result = build_legal_store(progress_callback=update)

    if result["success"]:
        st.success(
            f"✅ 법령DB 구축 완료! "
            f"{result['files']}개 파일 / "
            f"{result['total_chunks']:,}개 청크"
        )
        if result.get("file_results"):
            for fr in result["file_results"]:
                st.caption(
                    f"  📄 {fr['file']} "
                    f"({fr['cat']}) — {fr['chunks']}청크"
                )
        st.rerun()
    else:
        st.error("❌ 구축 실패. PDF 파일이 있는지 확인하세요.")