# pages/page_field.py
# 📱 현장 심사 도우미
# 심사 현장에서 빠르게 활용하는 전용 화면

import json
import logging
from datetime import datetime
from pathlib import Path

import ollama
import pandas as pd
import streamlit as st

from config.settings import (
    OLLAMA_MODEL, PROCESSED_DIR, OUTPUT_DIR
)
from data.vector_store import search_similar
from core.classifier import classify_item

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 현장 기록 저장 경로
# ─────────────────────────────────────────
FIELD_DIR  = OUTPUT_DIR / "field_records"
FIELD_FILE = FIELD_DIR / "field_records.json"


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("📋 현장 심사 도우미")
    st.markdown("심사 현장에서 빠르게 활용하는 전용 도구입니다.")
    st.markdown("---")

    # 데이터 로드
    df = _load_data()

    # 탭 구성
    tab1, tab2, tab3, tab4 = st.tabs([
        "⚡ 즉석 분류",
        "🔍 유사 사례 검색",
        "📋 체크리스트 조회",
        "📝 현장 기록"
    ])

    with tab1:
        _render_instant_classify(df)

    with tab2:
        _render_similar_search(df)

    with tab3:
        _render_checklist(df)

    with tab4:
        _render_field_record(df)


# ─────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────
def _load_data() -> pd.DataFrame | None:
    csv_path = PROCESSED_DIR / "processed_data.csv"
    if not csv_path.exists():
        return None
    return pd.read_csv(csv_path, dtype=str)


# ─────────────────────────────────────────
# Tab 1: 즉석 분류
# ─────────────────────────────────────────
def _render_instant_classify(df: pd.DataFrame | None):
    st.subheader("⚡ 즉석 분류")
    st.caption("현장에서 발견한 지적사항을 즉시 분류합니다.")

    title   = st.text_input(
        "지적사항 제목 입력",
        placeholder="예: TBM 일지 확인사항 누락",
        key="field_title"
    )
    problem = st.text_area(
        "현황 및 문제점 (선택)",
        placeholder="상세 내용을 입력하면 더 정확하게 분류됩니다.",
        height=100,
        key="field_problem"
    )
    audit_type = st.selectbox(
        "심사구분",
        options=["개선권고", "현지시정", "시정명령"],
        key="field_audit_type"
    )

    if st.button(
        "🔍 파트 분류하기",
        type="primary",
        use_container_width=True,
        key="btn_instant_classify"
    ):
        if not title.strip():
            st.warning("제목을 입력해주세요.")
            return

        with st.spinner("AI가 분류 중..."):
            # RAG 유사사례 검색
            query_text    = f"{title} {problem}".strip()
            similar_cases = search_similar(query_text, top_k=3)

            # AI 분류
            result = classify_item(
                title=title,
                problem=problem,
                audit_type=audit_type,
                similar_cases=similar_cases
            )

        # 결과 표시
        part  = result.get("part", "미분류")
        risk  = result.get("risk", "중")
        reason = result.get("reason", "")

        part_icon = {"안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"}.get(part, "❓")
        risk_color = {"상": "🔴", "중": "🟡", "하": "🟢"}.get(risk, "⚪")

        st.success("✅ 분류 완료!")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("분류 파트", f"{part_icon} {part}")
        with col2:
            st.metric("리스크 등급", f"{risk_color} {risk}")

        if reason:
            st.info(f"💡 분류 이유: {reason}")

        # 유사 과거 사례
        if similar_cases:
            st.subheader("📚 유사 과거 사례")
            for i, case in enumerate(similar_cases, 1):
                meta = case.get("metadata", {})
                sim  = case.get("similarity", 0)
                with st.expander(
                    f"{i}. {meta.get('title', '')} "
                    f"(유사도: {sim:.0%})",
                    expanded=(i == 1)
                ):
                    col1, col2, col3 = st.columns(3)
                    col1.write(f"**파트:** {meta.get('ai_part', '')}")
                    col2.write(f"**부서:** {meta.get('department', '')}")
                    col3.write(f"**연도:** {meta.get('year', '')}")
                    st.write(f"**내용:** {case.get('text', '')[:200]}...")

        # 현장 기록에 추가 버튼
        if st.button(
            "📝 현장 기록에 저장",
            key="save_to_record",
            use_container_width=True
        ):
            _save_field_record({
                "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title":      title,
                "problem":    problem,
                "audit_type": audit_type,
                "ai_part":    part,
                "ai_risk":    risk,
                "ai_reason":  reason,
            })
            st.success("✅ 현장 기록에 저장되었습니다!")


# ─────────────────────────────────────────
# Tab 2: 유사 사례 검색
# ─────────────────────────────────────────
def _render_similar_search(df: pd.DataFrame | None):
    st.subheader("🔍 유사 사례 검색")
    st.caption("키워드로 과거 유사 사례를 검색합니다.")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "검색어 입력",
            placeholder="예: MSDS 현행화, 비상대응훈련, TBM...",
            key="field_search_query"
        )
    with col2:
        top_k = st.selectbox("결과 수", [3, 5, 10], key="field_top_k")

    # 필터
    with st.expander("🔧 필터 옵션"):
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_part = st.selectbox(
                "파트",
                ["전체", "안전계획", "안전보건", "재난안전"],
                key="field_filter_part"
            )
        with col2:
            filter_audit = st.selectbox(
                "심사구분",
                ["전체", "개선권고", "현지시정", "시정명령"],
                key="field_filter_audit"
            )
        with col3:
            filter_dept = st.text_input(
                "부서명",
                placeholder="예: 전력팀",
                key="field_filter_dept"
            )

    if st.button(
        "🔍 검색",
        type="primary",
        use_container_width=True,
        key="btn_field_search"
    ):
        if not query.strip():
            st.warning("검색어를 입력해주세요.")
            return

        with st.spinner("검색 중..."):
            results = search_similar(
                query_text=query,
                top_k=top_k,
                filter_part=filter_part if filter_part != "전체" else None,
                filter_dept=filter_dept if filter_dept.strip() else None,
                filter_audit_type=filter_audit if filter_audit != "전체" else None,
            )

        if not results:
            st.info("검색 결과가 없습니다. 키워드를 바꿔보세요.")
            return

        st.success(f"✅ {len(results)}건 검색됨")

        for i, case in enumerate(results, 1):
            meta = case.get("metadata", {})
            sim  = case.get("similarity", 0)
            text = case.get("text", "")

            part_icon = {
                "안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"
            }.get(meta.get("ai_part", ""), "📋")

            with st.expander(
                f"{i}. {part_icon} {meta.get('title', '')} "
                f"— {meta.get('department', '')} "
                f"(유사도 {sim:.0%})",
                expanded=(i <= 3)
            ):
                col1, col2, col3, col4 = st.columns(4)
                col1.write(f"**파트:** {meta.get('ai_part', '-')}")
                col2.write(f"**심사구분:** {meta.get('audit_type', '-')}")
                col3.write(f"**부서:** {meta.get('department', '-')}")
                col4.write(f"**연도:** {meta.get('year', '-')}")
                st.divider()
                st.write(text)


# ─────────────────────────────────────────
# Tab 3: 체크리스트 조회
# ─────────────────────────────────────────
def _render_checklist(df: pd.DataFrame | None):
    st.subheader("📋 파트별 체크리스트")
    st.caption("심사 전 확인할 체크리스트를 조회합니다.")

    selected_part = st.radio(
        "파트 선택",
        ["🚇 안전계획", "🏥 안전보건", "🌪️ 재난안전"],
        horizontal=True,
        key="field_checklist_part"
    )

    # 과거 데이터 기반 상위 지적 항목 추가
    top_items = []
    if df is not None and "ai_part" in df.columns:
        part_name = selected_part.split(" ", 1)[1]
        part_df   = df[df["ai_part"] == part_name]
        if not part_df.empty and "title" in part_df.columns:
            top_items = (
                part_df["title"]
                .value_counts()
                .head(5)
                .index.tolist()
            )

    # 체크리스트 데이터
    checklists = {
        "안전계획": [
            ("A. 사고관리", [
                ("A-1", "철도사고 발생 현황 및 원인분석 적정성", "사고보고서, 원인분석서"),
                ("A-2", "철도준사고 보고 및 재발방지 대책 수립", "준사고 대장"),
                ("A-3", "운행장애 유형별 통계 및 개선 조치", "운행장애 월간보고"),
            ]),
            ("B. 운행안전", [
                ("B-1", "기관사 중점지도관리 대상자 관리", "중점관리대상자 기록부"),
                ("B-2", "지도승무 실시 현황 및 기록 관리", "지도승무 일지"),
                ("B-3", "TBM 작업전 안전점검회의 실시", "TBM 일지"),
            ]),
            ("C. 안전관리", [
                ("C-1", "유지관리 시행계획 수립 및 이행", "시행계획서, 드림스 기록"),
                ("C-2", "업무일지 결재 및 부서장 확인", "업무일지, 결재 이력"),
                ("C-3", "현장조치매뉴얼 최신화 여부", "현장조치매뉴얼"),
            ]),
            ("D. 훈련", [
                ("D-1", "비상대응훈련 계획 및 실시 현황", "훈련계획서, 결과보고서"),
                ("D-2", "훈련 미흡사항 개선 조치 여부", "개선계획서"),
            ]),
        ],
        "안전보건": [
            ("A. 법정교육", [
                ("A-1", "산업안전보건교육 법정시간 이수 여부", "교육실적부, 출석부"),
                ("A-2", "교육 개정사항 반영 여부 (연 1회)", "교육계획서"),
                ("A-3", "신규채용자 교육 이행 여부", "채용일 대비 이수일"),
            ]),
            ("B. 유해물질", [
                ("B-1", "MSDS 목록 최신화 여부 (1년마다)", "MSDS 목록, 갱신일자"),
                ("B-2", "MSDS 게시 및 근로자 접근성", "현장 게시 직접 확인"),
                ("B-3", "유해물질 취급 시 보호구 지급", "보호구 지급대장"),
            ]),
            ("C. 작업환경", [
                ("C-1", "핸드리프트·리프트 정격하중 표기", "현장 직접 확인"),
                ("C-2", "작업환경 측정 실시 여부 (연 2회)", "측정 결과보고서"),
            ]),
            ("D. TBM", [
                ("D-1", "TBM 일지 확인사항 적정성", "TBM 일지 샘플"),
                ("D-2", "TBM 시행 후 수기 작성 여부", "TBM 일지 현장 확인"),
            ]),
        ],
        "재난안전": [
            ("A. 대응계획", [
                ("A-1", "재난유형별 매뉴얼 보유 및 최신화", "재난매뉴얼, 개정이력"),
                ("A-2", "비상연락망 최신화 여부 (반기 1회)", "비상연락망, 갱신일자"),
                ("A-3", "위기대응 절차 부서별 공유 여부", "배포확인서"),
            ]),
            ("B. 훈련", [
                ("B-1", "연간 재난훈련 계획 수립 여부", "훈련계획서"),
                ("B-2", "훈련 실시 및 결과보고서 작성", "결과보고서, 사진"),
                ("B-3", "훈련 미흡사항 개선 조치", "개선계획서"),
            ]),
            ("C. 자연재난", [
                ("C-1", "호우·태풍 대비 시설물 점검", "사전점검 체크리스트"),
                ("C-2", "대설 제설 장비·자재 비축", "비축자재 현황표"),
                ("C-3", "지진 대응 절차 수립 여부", "지진 대응 매뉴얼"),
                ("C-4", "폭염·한파 대응 계획 수립", "계절별 대응계획서"),
            ]),
        ],
    }

    part_name = selected_part.split(" ", 1)[1]
    items     = checklists.get(part_name, [])

    # 체크 상태 초기화
    check_key = f"checks_{part_name}"
    if check_key not in st.session_state:
        st.session_state[check_key] = {}

    checked_count = 0
    total_count   = 0

    for category, sub_items in items:
        st.markdown(f"**{category}**")
        for code, item_name, ref_doc in sub_items:
            total_count += 1
            col1, col2 = st.columns([5, 3])
            with col1:
                # 과거 반복 지적 항목 강조
                is_repeat = any(kw in item_name for kw in top_items)
                label = f"{'🔴 ' if is_repeat else ''}{code}. {item_name}"
                checked = st.checkbox(
                    label,
                    key=f"check_{part_name}_{code}",
                    value=st.session_state[check_key].get(code, False)
                )
                st.session_state[check_key][code] = checked
                if checked:
                    checked_count += 1
            with col2:
                st.caption(f"📄 {ref_doc}")

    # 진행률 표시
    st.markdown("---")
    progress = checked_count / total_count if total_count > 0 else 0
    st.progress(progress)
    st.caption(
        f"점검 완료: {checked_count}/{total_count}개 "
        f"({progress*100:.0f}%)"
    )

    if top_items:
        st.info(
            f"🔴 과거 반복 지적 항목 (주의): "
            + ", ".join(top_items[:3])
        )

    # 체크리스트 초기화 버튼
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "🔄 체크 초기화",
            use_container_width=True,
            key=f"reset_{part_name}"
        ):
            st.session_state[check_key] = {}
            st.rerun()
    with col2:
        if st.button(
            "💾 결과 저장",
            use_container_width=True,
            key=f"save_check_{part_name}"
        ):
            _save_checklist_result(part_name, items, st.session_state[check_key])
            st.success("✅ 체크리스트 결과 저장 완료!")


# ─────────────────────────────────────────
# Tab 4: 현장 기록
# ─────────────────────────────────────────
def _render_field_record(df: pd.DataFrame | None):
    st.subheader("📝 현장 기록")
    st.caption("심사 중 발견한 지적사항을 기록합니다.")

    # 새 기록 입력
    with st.expander("➕ 새 지적사항 기록", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            rec_dept = st.text_input("담당 부서", key="rec_dept")
            rec_title = st.text_input("지적사항 제목", key="rec_title")
            rec_part = st.selectbox(
                "파트",
                ["안전계획", "안전보건", "재난안전"],
                key="rec_part"
            )
        with col2:
            rec_audit = st.selectbox(
                "심사구분",
                ["개선권고", "현지시정", "시정명령"],
                key="rec_audit"
            )
            rec_risk = st.selectbox(
                "리스크 등급",
                ["상", "중", "하"],
                key="rec_risk"
            )

        rec_content = st.text_area(
            "현황 및 문제점",
            height=80,
            key="rec_content"
        )
        rec_improve = st.text_area(
            "개선 방향",
            height=80,
            key="rec_improve"
        )

        if st.button(
            "💾 기록 저장",
            type="primary",
            use_container_width=True,
            key="btn_save_record"
        ):
            if not rec_title.strip():
                st.warning("제목을 입력해주세요.")
            else:
                _save_field_record({
                    "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "department":  rec_dept,
                    "title":       rec_title,
                    "audit_type":  rec_audit,
                    "ai_part":     rec_part,
                    "ai_risk":     rec_risk,
                    "problem":     rec_content,
                    "improvement": rec_improve,
                    "source":      "현장직접입력"
                })
                st.success("✅ 저장 완료!")
                st.rerun()

    st.divider()

    # 기록 목록 표시
    records = _load_field_records()

    if not records:
        st.info("📭 현장 기록이 없습니다.")
        return

    st.caption(f"총 {len(records)}건 기록됨")

    # 엑셀 내보내기
    if st.button(
        "📥 전체 기록 엑셀 내보내기",
        use_container_width=True,
        key="export_records"
    ):
        _export_records_excel(records)

    # 기록 목록
    for i, rec in enumerate(reversed(records)):
        part_icon = {
            "안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"
        }.get(rec.get("ai_part", ""), "📋")
        risk_icon = {
            "상": "🔴", "중": "🟡", "하": "🟢"
        }.get(rec.get("ai_risk", ""), "⚪")

        with st.expander(
            f"{part_icon} {risk_icon} [{rec.get('timestamp', '')}] "
            f"{rec.get('title', '')} — {rec.get('department', '')}",
            expanded=False
        ):
            col1, col2, col3 = st.columns(3)
            col1.write(f"**파트:** {rec.get('ai_part', '-')}")
            col2.write(f"**심사구분:** {rec.get('audit_type', '-')}")
            col3.write(f"**리스크:** {rec.get('ai_risk', '-')}")

            if rec.get("problem"):
                st.write(f"**문제점:** {rec['problem']}")
            if rec.get("improvement"):
                st.write(f"**개선방향:** {rec['improvement']}")

            # 삭제 버튼
            if st.button(
                "🗑️ 삭제",
                key=f"del_rec_{i}",
                use_container_width=True
            ):
                _delete_field_record(len(records) - 1 - i)
                st.rerun()


# ─────────────────────────────────────────
# 현장 기록 저장/로드
# ─────────────────────────────────────────
def _save_field_record(record: dict):
    FIELD_DIR.mkdir(parents=True, exist_ok=True)
    records = _load_field_records()
    records.append(record)
    with open(FIELD_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _load_field_records() -> list:
    if not FIELD_FILE.exists():
        return []
    try:
        with open(FIELD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _delete_field_record(index: int):
    records = _load_field_records()
    if 0 <= index < len(records):
        records.pop(index)
        with open(FIELD_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


def _save_checklist_result(
    part_name: str,
    items: list,
    checks: dict
):
    FIELD_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "type":      "checklist",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "part":      part_name,
        "items":     []
    }
    for category, sub_items in items:
        for code, item_name, ref_doc in sub_items:
            result["items"].append({
                "code":     code,
                "category": category,
                "item":     item_name,
                "checked":  checks.get(code, False),
                "ref_doc":  ref_doc
            })

    save_path = FIELD_DIR / f"checklist_{part_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def _export_records_excel(records: list):
    import io
    import pandas as pd

    df = pd.DataFrame(records)
    col_map = {
        "timestamp":   "기록일시",
        "department":  "담당부서",
        "title":       "지적사항",
        "audit_type":  "심사구분",
        "ai_part":     "파트",
        "ai_risk":     "리스크",
        "problem":     "현황및문제점",
        "improvement": "개선방향",
        "ai_reason":   "분류이유",
        "source":      "입력방법"
    }
    df = df.rename(columns=col_map)
    avail = [v for v in col_map.values() if v in df.columns]
    df    = df[avail]

    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    st.download_button(
        label="⬇️ 엑셀 다운로드",
        data=buffer.read(),
        file_name=f"현장기록_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )