# pages/page_field.py
# 📋 현장 심사 도우미 — 전면 개편
#
# 개선 내용:
# 1. 체크리스트: 과거 253건 데이터 기반 AI 자동 생성 + 세부 항목 대폭 확대
# 2. 미체크 항목 → 지적사항 자동 연결 (현장 기록 Tab 자동 추가)
# 3. JSON 활용: 연도별 비교, 미체크 → 지적사항, 엑셀 개선요구서 자동 생성
# 4. 부서 선택 → 해당 부서 과거 지적 기반 맞춤 체크리스트

import io
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.llm_client import llm_chat
from config.settings import OLLAMA_MODEL, PROCESSED_DIR, OUTPUT_DIR
from data.vector_store import search_similar
from core.classifier import classify_item

logger = logging.getLogger(__name__)

FIELD_DIR  = OUTPUT_DIR / "field_records"
FIELD_FILE = FIELD_DIR / "field_records.json"


# ─────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────
def render():
    st.title("📋 현장 심사 도우미")
    st.markdown("심사 현장에서 빠르게 활용하는 전용 도구입니다.")
    st.markdown("---")

    df = _load_data()

    tab1, tab2, tab3, tab4 = st.tabs([
        "⚡ 즉석 분류",
        "🔍 유사 사례 검색",
        "📋 체크리스트",
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
# Tab 1: 즉석 분류 (기존 유지)
# ─────────────────────────────────────────
def _render_instant_classify(df: pd.DataFrame | None):
    st.subheader("⚡ 즉석 분류")
    st.caption("현장에서 발견한 지적사항을 즉시 분류합니다.")

    title      = st.text_input("지적사항 제목 입력",
                               placeholder="예: TBM 일지 확인사항 누락",
                               key="field_title")
    problem    = st.text_area("현황 및 문제점 (선택)",
                              placeholder="상세 내용을 입력하면 더 정확하게 분류됩니다.",
                              height=100, key="field_problem")
    audit_type = st.selectbox("심사구분",
                              options=["개선권고", "현지시정", "시정명령"],
                              key="field_audit_type")

    if st.button("🔍 파트 분류하기", type="primary",
                 use_container_width=True, key="btn_instant_classify"):
        if not title.strip():
            st.warning("제목을 입력해주세요.")
            return

        with st.spinner("AI가 분류 중..."):
            query_text    = f"{title} {problem}".strip()
            similar_cases = search_similar(query_text, top_k=3)
            result        = classify_item(
                title=title, problem=problem,
                audit_type=audit_type, similar_cases=similar_cases
            )

        part   = result.get("part", "미분류")
        risk   = result.get("risk", "중")
        reason = result.get("reason", "")

        part_icon  = {"안전계획": "🚇", "안전보건": "🏥", "재난안전": "🌪️"}.get(part, "❓")
        risk_icon  = {"상": "🔴", "중": "🟡", "하": "🟢"}.get(risk, "⚪")

        st.success("✅ 분류 완료!")
        col1, col2 = st.columns(2)
        col1.metric("분류 파트",  f"{part_icon} {part}")
        col2.metric("리스크 등급", f"{risk_icon} {risk}")
        if reason:
            st.info(f"💡 분류 이유: {reason}")

        if similar_cases:
            st.subheader("📚 유사 과거 사례")
            for i, case in enumerate(similar_cases, 1):
                meta = case.get("metadata", {})
                sim  = case.get("similarity", 0)
                with st.expander(f"{i}. {meta.get('title','')} (유사도: {sim:.0%})",
                                 expanded=(i == 1)):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**파트:** {meta.get('ai_part','')}")
                    c2.write(f"**부서:** {meta.get('department','')}")
                    c3.write(f"**연도:** {meta.get('year','')}")
                    st.write(f"**내용:** {case.get('text','')[:200]}...")

        if st.button("📝 현장 기록에 저장", key="save_to_record",
                     use_container_width=True):
            _save_field_record({
                "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title":      title, "problem": problem,
                "audit_type": audit_type, "ai_part": part,
                "ai_risk":    risk, "ai_reason": reason,
                "source":     "즉석분류"
            })
            st.success("✅ 현장 기록에 저장되었습니다!")


# ─────────────────────────────────────────
# Tab 2: 유사 사례 검색 (기존 유지)
# ─────────────────────────────────────────
def _render_similar_search(df: pd.DataFrame | None):
    st.subheader("🔍 유사 사례 검색")
    st.caption("키워드로 과거 유사 사례를 검색합니다.")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input("검색어 입력",
                              placeholder="예: MSDS 현행화, 비상대응훈련, TBM...",
                              key="field_search_query")
    with col2:
        top_k = st.selectbox("결과 수", [3, 5, 10], key="field_top_k")

    with st.expander("🔧 필터 옵션"):
        c1, c2, c3 = st.columns(3)
        with c1:
            filter_part  = st.selectbox("파트",
                ["전체","안전계획","안전보건","재난안전"], key="field_filter_part")
        with c2:
            filter_audit = st.selectbox("심사구분",
                ["전체","개선권고","현지시정","시정명령"], key="field_filter_audit")
        with c3:
            filter_dept  = st.text_input("부서명", placeholder="예: 전력팀",
                                         key="field_filter_dept")

    if st.button("🔍 검색", type="primary", use_container_width=True,
                 key="btn_field_search"):
        if not query.strip():
            st.warning("검색어를 입력해주세요.")
            return
        with st.spinner("검색 중..."):
            results = search_similar(
                query_text=query, top_k=top_k,
                filter_part=filter_part  if filter_part  != "전체" else None,
                filter_dept=filter_dept  if filter_dept.strip() else None,
                filter_audit_type=filter_audit if filter_audit != "전체" else None,
            )
        if not results:
            st.info("검색 결과가 없습니다. 키워드를 바꿔보세요.")
            return
        st.success(f"✅ {len(results)}건 검색됨")
        for i, case in enumerate(results, 1):
            meta = case.get("metadata", {})
            sim  = case.get("similarity", 0)
            icon = {"안전계획":"🚇","안전보건":"🏥","재난안전":"🌪️"}.get(
                meta.get("ai_part",""), "📋")
            with st.expander(
                f"{i}. {icon} {meta.get('title','')} — "
                f"{meta.get('department','')} (유사도 {sim:.0%})",
                expanded=(i <= 3)
            ):
                c1,c2,c3,c4 = st.columns(4)
                c1.write(f"**파트:** {meta.get('ai_part','-')}")
                c2.write(f"**심사구분:** {meta.get('audit_type','-')}")
                c3.write(f"**부서:** {meta.get('department','-')}")
                c4.write(f"**연도:** {meta.get('year','-')}")
                st.divider()
                st.write(case.get("text",""))


# ─────────────────────────────────────────
# Tab 3: 체크리스트 — 전면 개편
# ─────────────────────────────────────────
def _render_checklist(df: pd.DataFrame | None):
    st.subheader("📋 체크리스트")

    if df is None:
        st.warning("⚠️ 데이터가 없습니다. [데이터 업로드] 먼저 실행하세요.")
        return

    # ── 부서 + 파트 선택
    col1, col2 = st.columns(2)
    with col1:
        departments = ["전체"] + [
            d for d in df["department"].value_counts().index.tolist()
            if d and d not in ("미기재","nan","")
        ] if "department" in df.columns else ["전체"]
        selected_dept = st.selectbox("🏢 부서 선택", departments,
                                     key="cl_dept")
    with col2:
        selected_part = st.radio("파트 선택",
            ["🚇 안전계획", "🏥 안전보건", "🌪️ 재난안전"],
            horizontal=True, key="cl_part")

    part_name = selected_part.split(" ", 1)[1]

    # ── 체크리스트 생성 (AI + 과거 데이터)
    cl_key = f"checklist_{selected_dept}_{part_name}"
    if cl_key not in st.session_state:
        st.session_state[cl_key] = None

    col_gen, col_load = st.columns(2)
    with col_gen:
        if st.button("🤖 AI 체크리스트 자동 생성",
                     type="primary", use_container_width=True,
                     key="btn_gen_cl"):
            with st.spinner("과거 데이터 분석 + AI 체크리스트 생성 중..."):
                st.session_state[cl_key] = _generate_checklist_ai(
                    df, part_name, selected_dept
                )
            st.success("✅ 체크리스트 생성 완료!")

    with col_load:
        saved = _get_saved_checklists(selected_dept, part_name)
        if saved:
            sel_file = st.selectbox("📂 이전 저장본 불러오기",
                ["선택안함"] + [s["label"] for s in saved],
                key="cl_load_sel")
            if sel_file != "선택안함":
                for s in saved:
                    if s["label"] == sel_file:
                        st.session_state[cl_key] = s["data"]
                        break

    if st.session_state[cl_key] is None:
        # 기본 체크리스트 표시 (고정 항목)
        st.info("💡 [AI 체크리스트 자동 생성] 버튼을 누르면 과거 데이터 기반으로 맞춤 항목이 생성됩니다.")
        st.session_state[cl_key] = _get_default_checklist(part_name)

    checklist = st.session_state[cl_key]
    if not checklist:
        st.warning("체크리스트 항목이 없습니다.")
        return

    # ── 상태 관리
    # 3가지 상태: "이상없음" / "지적사항" / "미확인"
    # session_state[check_state_key][code] = "이상없음" | "지적사항" | "미확인"
    check_state_key = f"checks_{selected_dept}_{part_name}"
    if check_state_key not in st.session_state:
        st.session_state[check_state_key] = {}

    ok_count      = 0   # ✅ 이상없음
    issue_count   = 0   # ❌ 지적사항
    pending_count = 0   # ⬜ 미확인
    total_count   = 0

    issue_items   = []  # 지적사항 → 자동 등록 대상
    pending_items = []  # 미확인 → 심사 계속 필요

    st.markdown("---")

    # ── 범례
    st.caption(
        "✅ 이상없음 = 현장 확인 완료, 문제 없음   "
        "❌ 지적사항 = 문제 발견, 지적 등록 필요   "
        "⬜ 미확인 = 아직 확인 못 함"
    )
    st.markdown("")

    for category in checklist:
        cat_name  = category["category"]
        cat_items = category["items"]

        # 카테고리 헤더
        repeat_cnt = sum(1 for it in cat_items if it.get("repeat_count", 0) >= 2)
        badge = f" 🔴 반복지적 {repeat_cnt}건 포함" if repeat_cnt > 0 else ""
        st.markdown(f"**{cat_name}**{badge}")

        for item in cat_items:
            total_count += 1
            code            = item["code"]
            item_name       = item["item"]
            ref_doc         = item.get("ref_doc", "")
            check_point     = item.get("check_point", "")
            repeat_cnt_item = item.get("repeat_count", 0)
            past_issues     = item.get("past_issues", [])

            # 반복 지적 강조 배지
            if repeat_cnt_item >= 3:
                repeat_badge = " 🔴"
            elif repeat_cnt_item >= 2:
                repeat_badge = " 🟡"
            else:
                repeat_badge = ""

            # 현재 상태값 (기본: 미확인)
            current_state = st.session_state[check_state_key].get(code, "미확인")

            # ── 항목 행 구성
            c1, c2 = st.columns([6, 2])
            with c1:
                st.markdown(
                    f"`{code}` &nbsp; {item_name}{repeat_badge}"
                )
            with c2:
                # 3가지 상태 라디오 (가로 배치)
                new_state = st.radio(
                    label="상태",
                    options=["✅ 이상없음", "❌ 지적사항", "⬜ 미확인"],
                    index={"이상없음": 0, "지적사항": 1, "미확인": 2}.get(
                        current_state, 2
                    ),
                    horizontal=True,
                    key=f"radio_{selected_dept}_{part_name}_{code}",
                    label_visibility="collapsed"
                )

            # 상태 저장 (라벨에서 순수 상태값 추출)
            state_val = new_state.split(" ", 1)[1]  # "✅ 이상없음" → "이상없음"
            st.session_state[check_state_key][code] = state_val

            # 카운트 및 목록 분류
            if state_val == "이상없음":
                ok_count += 1
            elif state_val == "지적사항":
                issue_count += 1
                issue_items.append({
                    "code": code, "item": item_name,
                    "category": cat_name, "ref_doc": ref_doc,
                    "check_point": check_point,
                    "repeat_count": repeat_cnt_item,
                    "past_issues": past_issues,
                })
            else:
                pending_count += 1
                pending_items.append({
                    "code": code, "item": item_name,
                    "category": cat_name, "ref_doc": ref_doc,
                })

            # 참고 정보 (점검 포인트 + 확인 자료)
            info_parts = []
            if check_point:
                info_parts.append(f"🔍 {check_point}")
            if ref_doc:
                info_parts.append(f"📄 {ref_doc}")
            if info_parts:
                st.caption("  " + "   |   ".join(info_parts))

            # 과거 지적 사례 (반복 2회 이상)
            if past_issues and repeat_cnt_item >= 2:
                with st.expander(
                    f"  📌 과거 지적 {repeat_cnt_item}회 내역",
                    expanded=False
                ):
                    for pi in past_issues[:3]:
                        st.caption(
                            f"• {pi.get('year','')}년 "
                            f"{pi.get('audit_type','')} — "
                            f"{pi.get('problem','')[:60]}..."
                        )

            # 지적사항 선택 시 → 문제점 입력창 즉시 표시
            if state_val == "지적사항":
                prob_key = f"prob_{selected_dept}_{part_name}_{code}"
                prob_val = st.text_input(
                    "문제점 상세 입력 (선택)",
                    placeholder=f"예: {item_name} 관련 구체적 문제점 입력...",
                    key=prob_key,
                )
                # issue_items 마지막 항목에 문제점 추가
                if issue_items and issue_items[-1]["code"] == code:
                    issue_items[-1]["problem_detail"] = prob_val

            st.markdown("")

        st.divider()

    # ── 진행 현황 요약
    st.subheader("📊 심사 현황")
    progress_ok = ok_count / total_count if total_count > 0 else 0

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("📋 총 항목",    f"{total_count}개")
    col_b.metric("✅ 이상없음",   f"{ok_count}개")
    col_c.metric("❌ 지적사항",   f"{issue_count}개",
                 delta="지적 등록 필요" if issue_count > 0 else None,
                 delta_color="inverse" if issue_count > 0 else "off")
    col_d.metric("⬜ 미확인",     f"{pending_count}개",
                 delta="계속 심사 필요" if pending_count > 0 else None,
                 delta_color="inverse" if pending_count > 0 else "off")

    st.progress(progress_ok)
    st.caption(
        f"이상없음 비율: {progress_ok*100:.0f}%  |  "
        f"미확인이 있으면 심사를 계속 진행하세요"
    )

    # ── 미확인 항목 안내
    if pending_items:
        st.markdown("---")
        with st.expander(f"⬜ 미확인 {pending_count}개 — 아직 확인이 필요한 항목", expanded=False):
            st.caption("아직 현장 확인을 하지 못한 항목입니다. 심사를 계속 진행하세요.")
            for p in pending_items:
                st.write(f"• `{p['code']}` {p['item']}")
                if p["ref_doc"]:
                    st.caption(f"  확인 자료: {p['ref_doc']}")

    # ── 지적사항 → 자동 등록
    st.markdown("---")
    st.subheader("❌ 지적사항 — 현장 기록 자동 등록")

    if not issue_items:
        st.success("✅ 지적사항이 없습니다!")
    else:
        st.warning(f"⚠️ 지적사항 {len(issue_items)}건이 있습니다.")
        st.caption("아래 항목을 현장 기록에 한 번에 등록하거나 개별 등록하세요.")

        # 전체 일괄 등록 버튼
        if st.button(
            f"📝 지적사항 {len(issue_items)}건 전체 등록",
            type="primary", use_container_width=True,
            key="btn_register_all"
        ):
            dept = selected_dept if selected_dept != "전체" else ""
            for u in issue_items:
                audit_default = "시정명령" if u["repeat_count"] >= 3 else "개선권고"
                risk_default  = "상"       if u["repeat_count"] >= 3 else "중"
                _save_field_record({
                    "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "department":     dept,
                    "title":          u["item"],
                    "audit_type":     audit_default,
                    "ai_part":        part_name,
                    "ai_risk":        risk_default,
                    "problem":        u.get("problem_detail", "") or
                                      f"체크리스트 지적항목: {u['item']}",
                    "improvement":    f"확인 자료 검토 필요: {u['ref_doc']}",
                    "source":         "체크리스트_지적사항",
                    "checklist_code": u["code"],
                    "repeat_count":   u["repeat_count"],
                })
            st.success(f"✅ {len(issue_items)}건 현장 기록에 등록 완료!")
            st.rerun()

        st.markdown("")

        # 개별 항목 표시
        for u in issue_items:
            rep = u["repeat_count"]
            icon = "🔴" if rep >= 3 else "🟡" if rep >= 2 else "❌"
            audit_default = "시정명령" if rep >= 3 else "개선권고"
            risk_default  = "상"       if rep >= 3 else "중"

            with st.expander(
                f"{icon} {u['code']}. {u['item']}"
                f"{'  (반복 '+str(rep)+'회)' if rep >= 2 else ''}",
                expanded=True
            ):
                c_l, c_r = st.columns([3, 1])
                with c_l:
                    st.caption(f"확인 자료: {u['ref_doc']}")
                    st.caption(
                        f"자동 판정 → 심사구분: {audit_default}  |  "
                        f"리스크: {risk_default}"
                    )
                    if u.get("problem_detail"):
                        st.info(f"입력된 문제점: {u['problem_detail']}")
                    if u["past_issues"]:
                        st.caption(
                            "최근 지적: " + " / ".join(
                                f"{pi.get('year','')}년 {pi.get('audit_type','')}"
                                for pi in u["past_issues"][:2]
                            )
                        )
                with c_r:
                    if st.button("📝 개별 등록", key=f"add_issue_{u['code']}",
                                 use_container_width=True):
                        dept = selected_dept if selected_dept != "전체" else ""
                        _save_field_record({
                            "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "department":     dept,
                            "title":          u["item"],
                            "audit_type":     audit_default,
                            "ai_part":        part_name,
                            "ai_risk":        risk_default,
                            "problem":        u.get("problem_detail", "") or
                                              f"체크리스트 지적항목: {u['item']}",
                            "improvement":    f"확인 자료 검토 필요: {u['ref_doc']}",
                            "source":         "체크리스트_지적사항",
                            "checklist_code": u["code"],
                            "repeat_count":   u["repeat_count"],
                        })
                        st.success(f"✅ '{u['item']}' 등록!")
                        st.rerun()

    # ── 하단 버튼
    st.markdown("---")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔄 전체 초기화", use_container_width=True,
                     key=f"reset_cl_{part_name}"):
            st.session_state[check_state_key] = {}
            st.rerun()

    with col2:
        if st.button("💾 체크리스트 저장", use_container_width=True,
                     key=f"save_cl_{part_name}"):
            _save_checklist_result(
                selected_dept, part_name, checklist,
                st.session_state[check_state_key]
            )
            st.success("✅ 저장 완료!")

    with col3:
        if st.button("📥 개선요구서 엑셀 생성", use_container_width=True,
                     key=f"excel_cl_{part_name}"):
            _export_checklist_excel(
                selected_dept, part_name, checklist,
                st.session_state[check_state_key], issue_items
            )


# ─────────────────────────────────────────
# AI 체크리스트 자동 생성 (핵심 신규 기능)
# ─────────────────────────────────────────
def _generate_checklist_ai(
    df: pd.DataFrame,
    part_name: str,
    dept: str = "전체"
) -> list[dict]:
    """
    과거 253건 데이터 분석 → AI가 세부 체크리스트 자동 생성
    부서 선택 시 해당 부서 과거 지적 기반 맞춤 생성
    """
    # ── 1. 과거 데이터 필터링
    df_part = df[df["ai_part"] == part_name].copy() if "ai_part" in df.columns else df.copy()
    if dept != "전체" and "department" in df_part.columns:
        df_dept = df_part[df_part["department"] == dept]
    else:
        df_dept = df_part

    # ── 2. 반복 지적 집계
    title_counts = df_part["title"].value_counts().to_dict() if "title" in df_part.columns else {}

    # ── 3. 주요 지적 항목 추출 (상위 30개)
    top_issues = []
    if "title" in df_part.columns and "problem" in df_part.columns:
        for title, cnt in list(title_counts.items())[:30]:
            rows = df_part[df_part["title"] == title]
            problems = rows["problem"].dropna().tolist()[:3]
            audit_types = rows["audit_type"].dropna().tolist() if "audit_type" in rows else []
            years = rows["year"].dropna().tolist() if "year" in rows else []
            top_issues.append({
                "title":      title,
                "count":      cnt,
                "problems":   problems,
                "audit_types": audit_types,
                "years":      years,
            })

    # ── 4. 부서 특화 지적 추출
    dept_issues = []
    if dept != "전체" and "title" in df_dept.columns:
        dept_title_counts = df_dept["title"].value_counts()
        for title, cnt in dept_title_counts.items():
            rows = df_dept[df_dept["title"] == title]
            dept_issues.append({
                "title": title, "count": cnt,
                "audit_type": rows["audit_type"].iloc[0] if "audit_type" in rows.columns else ""
            })

    # ── 5. AI 프롬프트 구성
    issues_text = "\n".join([
        f"- {it['title']} ({it['count']}회) | "
        f"심사구분: {','.join(set(it['audit_types'][:2]))} | "
        f"예시: {it['problems'][0][:50] if it['problems'] else ''}"
        for it in top_issues[:20]
    ])

    dept_text = ""
    if dept_issues:
        dept_text = f"\n\n[{dept} 특화 지적사항]\n" + "\n".join([
            f"- {it['title']} ({it['count']}회) {it['audit_type']}"
            for it in dept_issues[:10]
        ])

    prompt = f"""당신은 대구도시철도공사 자체종합안전심사 전문가입니다.
아래 과거 지적사항 데이터를 분석하여 [{part_name}] 파트의 현장 심사 체크리스트를 작성하세요.

[과거 주요 지적사항 ({part_name} 파트, {len(df_part)}건)]
{issues_text}{dept_text}

[작성 지침]
1. 대분류 4~6개, 각 대분류당 세부 항목 4~8개 작성
2. 각 항목은 실제 현장에서 확인 가능한 구체적 내용
3. 과거 반복 지적 항목은 반드시 포함
4. 확인 자료(서류명)와 점검 포인트 명시
5. 반드시 아래 JSON 형식으로만 응답 (설명 없이)

[응답 형식 - JSON만 출력]
[
  {{
    "category": "A. 대분류명",
    "items": [
      {{
        "code": "A-1",
        "item": "세부 점검 항목",
        "ref_doc": "확인 자료명",
        "check_point": "구체적 점검 포인트"
      }}
    ]
  }}
]"""

    try:
        response = llm_chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2}
        )
        raw = response["message"]["content"].strip()

        # JSON 파싱
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        checklist_raw = json.loads(raw)

        # ── 6. 과거 지적 정보 매핑 (반복횟수, 과거 사례)
        checklist = _enrich_checklist(checklist_raw, df_part, title_counts)
        return checklist

    except Exception as e:
        logger.error(f"AI 체크리스트 생성 오류: {e}")
        # 폴백: 기본 체크리스트
        return _get_default_checklist(part_name)


def _enrich_checklist(
    checklist_raw: list,
    df_part: pd.DataFrame,
    title_counts: dict
) -> list:
    """체크리스트 항목에 과거 지적 데이터 매핑"""
    enriched = []
    for cat in checklist_raw:
        new_items = []
        for item in cat.get("items", []):
            item_name = item.get("item", "")
            # 과거 지적 매핑 (유사 제목 찾기)
            repeat_count = 0
            past_issues  = []
            for title, cnt in title_counts.items():
                # 키워드 매칭
                keywords = [w for w in item_name.split() if len(w) >= 2]
                if any(kw in title for kw in keywords):
                    repeat_count = max(repeat_count, cnt)
                    rows = df_part[df_part["title"] == title].head(3)
                    for _, row in rows.iterrows():
                        past_issues.append({
                            "year":       str(row.get("year", "")),
                            "audit_type": str(row.get("audit_type", "")),
                            "problem":    str(row.get("problem", ""))[:80],
                        })

            new_item = dict(item)
            new_item["repeat_count"] = repeat_count
            new_item["past_issues"]  = past_issues[:3]
            new_items.append(new_item)

        enriched.append({
            "category": cat.get("category", ""),
            "items":    new_items
        })
    return enriched


# ─────────────────────────────────────────
# 기본 체크리스트 (AI 생성 전 폴백)
# ─────────────────────────────────────────
def _get_default_checklist(part_name: str) -> list:
    defaults = {
        "안전계획": [
            {"category": "A. 철도사고·준사고 관리", "items": [
                {"code":"A-1","item":"철도사고 발생 현황 및 원인분석 적정성","ref_doc":"사고보고서, 원인분석서","check_point":"원인분석 5WHY 적용 여부","repeat_count":0,"past_issues":[]},
                {"code":"A-2","item":"철도준사고 보고 및 재발방지 대책 수립","ref_doc":"준사고 대장","check_point":"보고 기한(72시간) 준수 여부","repeat_count":0,"past_issues":[]},
                {"code":"A-3","item":"운행장애 유형별 통계 및 개선 조치","ref_doc":"운행장애 월간보고","check_point":"월간 보고서 작성 여부","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "B. 운행안전 관리", "items": [
                {"code":"B-1","item":"기관사 중점지도관리 대상자 관리","ref_doc":"중점관리대상자 기록부","check_point":"선정 기준 및 관리 주기","repeat_count":0,"past_issues":[]},
                {"code":"B-2","item":"지도승무 실시 현황 및 기록 관리","ref_doc":"지도승무 일지","check_point":"월 1회 이상 실시 여부","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "C. 안전관리체계 운영", "items": [
                {"code":"C-1","item":"유지관리 시행계획 수립 및 이행","ref_doc":"시행계획서, 드림스 기록","check_point":"계획 대비 이행률 확인","repeat_count":0,"past_issues":[]},
                {"code":"C-2","item":"업무일지 결재 및 부서장 확인","ref_doc":"업무일지, 결재 이력","check_point":"미결재 건수 확인","repeat_count":0,"past_issues":[]},
                {"code":"C-3","item":"현장조치매뉴얼 최신화 여부","ref_doc":"현장조치매뉴얼, 개정이력","check_point":"최근 1년 내 개정 여부","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "D. 비상대응 훈련", "items": [
                {"code":"D-1","item":"비상대응훈련 연간계획 수립 여부","ref_doc":"훈련계획서","check_point":"훈련 종류 및 횟수 적정성","repeat_count":0,"past_issues":[]},
                {"code":"D-2","item":"훈련 실시 및 결과보고서 작성","ref_doc":"훈련결과보고서, 사진","check_point":"미흡사항 개선 여부","repeat_count":0,"past_issues":[]},
            ]},
        ],
        "안전보건": [
            {"category": "A. 법정 교육", "items": [
                {"code":"A-1","item":"산업안전보건교육 법정시간 이수 여부","ref_doc":"교육실적부, 출석부","check_point":"정기(매분기), 관리감독자(연16시간)","repeat_count":0,"past_issues":[]},
                {"code":"A-2","item":"교육 개정사항 반영 여부 (연 1회)","ref_doc":"교육계획서, 교육자료","check_point":"최신 법령 반영 확인","repeat_count":0,"past_issues":[]},
                {"code":"A-3","item":"신규채용자 교육 이행 여부","ref_doc":"채용일 대비 교육이수일","check_point":"채용 후 1개월 내 이수","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "B. 유해물질 관리", "items": [
                {"code":"B-1","item":"MSDS 목록 최신화 여부 (1년마다)","ref_doc":"MSDS 목록, 갱신일자","check_point":"갱신일이 1년 이내인지 확인","repeat_count":0,"past_issues":[]},
                {"code":"B-2","item":"MSDS 게시 및 근로자 접근성","ref_doc":"현장 게시 직접 확인","check_point":"취급 장소 부근 게시 여부","repeat_count":0,"past_issues":[]},
                {"code":"B-3","item":"유해물질 취급 시 보호구 지급","ref_doc":"보호구 지급대장","check_point":"종류별 적정 보호구 지급","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "C. 작업환경 관리", "items": [
                {"code":"C-1","item":"핸드리프트·리프트 정격하중 표기","ref_doc":"현장 직접 확인","check_point":"스티커 부착 및 수량 확인","repeat_count":0,"past_issues":[]},
                {"code":"C-2","item":"작업환경 측정 실시 여부 (연 2회)","ref_doc":"작업환경측정 결과보고서","check_point":"측정 주기 및 결과 적정성","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "D. TBM 관리", "items": [
                {"code":"D-1","item":"TBM 일지 확인사항 적정성","ref_doc":"TBM 일지 샘플 5개 이상","check_point":"형식적 기재 여부 확인","repeat_count":0,"past_issues":[]},
                {"code":"D-2","item":"TBM 시행 후 수기 서명 여부","ref_doc":"TBM 일지 현장 확인","check_point":"서명 누락 건 수 확인","repeat_count":0,"past_issues":[]},
            ]},
        ],
        "재난안전": [
            {"category": "A. 재난대응 계획", "items": [
                {"code":"A-1","item":"재난유형별 매뉴얼 보유 및 최신화","ref_doc":"재난매뉴얼, 개정이력","check_point":"최근 1년 내 개정 여부","repeat_count":0,"past_issues":[]},
                {"code":"A-2","item":"비상연락망 최신화 여부 (반기 1회)","ref_doc":"비상연락망, 갱신일자","check_point":"6개월 이내 갱신 여부","repeat_count":0,"past_issues":[]},
                {"code":"A-3","item":"위기대응 절차 부서별 공유 여부","ref_doc":"배포확인서, 교육실적","check_point":"전 직원 숙지 여부 확인","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "B. 재난 훈련", "items": [
                {"code":"B-1","item":"연간 재난훈련 계획 수립 여부","ref_doc":"훈련계획서","check_point":"유형별 훈련 횟수 적정성","repeat_count":0,"past_issues":[]},
                {"code":"B-2","item":"훈련 실시 및 결과보고서 작성","ref_doc":"훈련결과보고서, 사진","check_point":"미흡사항 개선 조치 여부","repeat_count":0,"past_issues":[]},
            ]},
            {"category": "C. 자연재난 대비", "items": [
                {"code":"C-1","item":"호우·태풍 대비 시설물 사전 점검","ref_doc":"사전점검 체크리스트","check_point":"우수로, 배수구 점검 여부","repeat_count":0,"past_issues":[]},
                {"code":"C-2","item":"대설 제설 장비·자재 비축 현황","ref_doc":"비축자재 현황표","check_point":"수량 적정성 및 관리상태","repeat_count":0,"past_issues":[]},
                {"code":"C-3","item":"지진 대응 절차 수립 여부","ref_doc":"지진 대응 매뉴얼","check_point":"직원 숙지 여부","repeat_count":0,"past_issues":[]},
                {"code":"C-4","item":"폭염·한파 대응 계획 수립","ref_doc":"계절별 대응계획서","check_point":"온열질환 예방 지침 여부","repeat_count":0,"past_issues":[]},
            ]},
        ],
    }
    return defaults.get(part_name, [])


# ─────────────────────────────────────────
# 저장된 체크리스트 목록 조회
# ─────────────────────────────────────────
def _get_saved_checklists(dept: str, part_name: str) -> list:
    if not FIELD_DIR.exists():
        return []
    pattern = f"checklist_{dept}_{part_name}_*.json"
    files   = sorted(FIELD_DIR.glob(pattern), reverse=True)
    result  = []
    for f in files[:5]:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            ts = data.get("timestamp", f.stem)
            unchecked = sum(
                1 for item in data.get("items", [])
                if not item.get("checked", True)
            )
            result.append({
                "label": f"{ts} (미체크 {unchecked}건)",
                "data":  data.get("checklist_data", []),
            })
        except Exception:
            pass
    return result


# ─────────────────────────────────────────
# 체크리스트 결과 저장 (개선)
# ─────────────────────────────────────────
def _save_checklist_result(
    dept: str,
    part_name: str,
    checklist: list,
    checks: dict
):
    """체크리스트 결과 저장 — 3가지 상태(이상없음/지적사항/미확인) 반영"""
    FIELD_DIR.mkdir(parents=True, exist_ok=True)
    items_flat = []
    for cat in checklist:
        for item in cat.get("items", []):
            code  = item["code"]
            state = checks.get(code, "미확인")  # 3가지 상태값
            items_flat.append({
                "code":         code,
                "category":     cat["category"],
                "item":         item["item"],
                "state":        state,
                "is_ok":        state == "이상없음",
                "is_issue":     state == "지적사항",
                "is_pending":   state == "미확인",
                "ref_doc":      item.get("ref_doc", ""),
                "check_point":  item.get("check_point", ""),
                "repeat_count": item.get("repeat_count", 0),
            })

    result = {
        "type":           "checklist",
        "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "department":     dept,
        "part":           part_name,
        "total":          len(items_flat),
        "ok_count":       sum(1 for it in items_flat if it["is_ok"]),
        "issue_count":    sum(1 for it in items_flat if it["is_issue"]),
        "pending_count":  sum(1 for it in items_flat if it["is_pending"]),
        "items":          items_flat,
        "checklist_data": checklist,
    }
    ts_str    = datetime.now().strftime("%Y%m%d_%H%M")
    save_path = FIELD_DIR / f"checklist_{dept}_{part_name}_{ts_str}.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────
# 개선요구서 엑셀 생성 (신규)
# ─────────────────────────────────────────
def _export_checklist_excel(
    dept: str,
    part_name: str,
    checklist: list,
    checks: dict,
    unchecked_items: list
):
    """미체크 항목 → 개선요구서 엑셀 자동 생성"""
    rows = []
    no   = 1
    for u in unchecked_items:
        audit_type = "시정명령" if u["repeat_count"] >= 3 else "개선권고"
        risk       = "상" if u["repeat_count"] >= 3 else "중" if u["repeat_count"] >= 2 else "중"
        rows.append({
            "No":       no,
            "부서":     dept if dept != "전체" else "",
            "파트":     part_name,
            "심사구분": audit_type,
            "리스크":   risk,
            "지적사항": u["item"],
            "분류":     u["category"],
            "확인자료": u["ref_doc"],
            "반복횟수": u["repeat_count"],
            "개선방향": "",   # 심사자가 직접 입력
            "이행기한": "",   # 심사자가 직접 입력
            "비고":     f"반복 {u['repeat_count']}회" if u["repeat_count"] >= 2 else "",
        })
        no += 1

    if not rows:
        st.info("미체크 항목이 없어 개선요구서를 생성할 수 없습니다.")
        return

    export_df = pd.DataFrame(rows)
    buffer    = io.BytesIO()
    export_df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    ts = datetime.now().strftime("%Y%m%d")
    st.download_button(
        label=f"⬇️ 개선요구서 엑셀 다운로드 ({len(rows)}건)",
        data=buffer.read(),
        file_name=f"{dept}_{part_name}_개선요구서_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )


# ─────────────────────────────────────────
# Tab 4: 현장 기록 (기존 유지 + 체크리스트 연동 표시)
# ─────────────────────────────────────────
def _render_field_record(df: pd.DataFrame | None):
    st.subheader("📝 현장 기록")
    st.caption("심사 중 발견한 지적사항을 기록합니다. 체크리스트 미체크 항목도 여기 표시됩니다.")

    with st.expander("➕ 새 지적사항 직접 입력", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            rec_dept  = st.text_input("담당 부서", key="rec_dept")
            rec_title = st.text_input("지적사항 제목", key="rec_title")
            rec_part  = st.selectbox("파트",
                ["안전계획","안전보건","재난안전"], key="rec_part")
        with c2:
            rec_audit = st.selectbox("심사구분",
                ["개선권고","현지시정","시정명령"], key="rec_audit")
            rec_risk  = st.selectbox("리스크 등급",
                ["상","중","하"], key="rec_risk")
        rec_content = st.text_area("현황 및 문제점", height=80, key="rec_content")
        rec_improve = st.text_area("개선 방향",      height=80, key="rec_improve")

        if st.button("💾 기록 저장", type="primary",
                     use_container_width=True, key="btn_save_record"):
            if not rec_title.strip():
                st.warning("제목을 입력해주세요.")
            else:
                _save_field_record({
                    "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "department":  rec_dept,  "title":   rec_title,
                    "audit_type":  rec_audit, "ai_part": rec_part,
                    "ai_risk":     rec_risk,  "problem": rec_content,
                    "improvement": rec_improve, "source": "현장직접입력"
                })
                st.success("✅ 저장 완료!")
                st.rerun()

    st.divider()

    records = _load_field_records()
    if not records:
        st.info("📭 현장 기록이 없습니다.")
        return

    # 출처별 분류 표시
    checklist_records = [r for r in records if r.get("source") == "체크리스트_미체크"]
    manual_records    = [r for r in records if r.get("source") != "체크리스트_미체크"]

    st.caption(
        f"총 {len(records)}건  |  "
        f"직접입력/즉석분류 {len(manual_records)}건  |  "
        f"체크리스트 미체크 {len(checklist_records)}건"
    )

    # 엑셀 내보내기
    if st.button("📥 전체 기록 엑셀 내보내기",
                 use_container_width=True, key="export_records"):
        _export_records_excel(records)

    # 통계 요약
    if records:
        risk_counts = {}
        for r in records:
            risk = r.get("ai_risk", "미정")
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
        c1, c2, c3 = st.columns(3)
        c1.metric("🔴 리스크 상", f"{risk_counts.get('상', 0)}건")
        c2.metric("🟡 리스크 중", f"{risk_counts.get('중', 0)}건")
        c3.metric("🟢 리스크 하", f"{risk_counts.get('하', 0)}건")

    st.markdown("---")

    # 체크리스트 미체크 항목 먼저 표시
    if checklist_records:
        st.markdown("**📋 체크리스트 미체크 항목 (자동 등록)**")
        for i, rec in enumerate(reversed(checklist_records)):
            risk_icon = {"상":"🔴","중":"🟡","하":"🟢"}.get(rec.get("ai_risk",""),"⚪")
            part_icon = {"안전계획":"🚇","안전보건":"🏥","재난안전":"🌪️"}.get(
                rec.get("ai_part",""),"📋")
            with st.expander(
                f"{part_icon} {risk_icon} [{rec.get('timestamp','')}] "
                f"{rec.get('title','')} — {rec.get('department','')}",
                expanded=False
            ):
                c1,c2,c3 = st.columns(3)
                c1.write(f"**파트:** {rec.get('ai_part','-')}")
                c2.write(f"**심사구분:** {rec.get('audit_type','-')}")
                c3.write(f"**리스크:** {rec.get('ai_risk','-')}")
                if rec.get("problem"):
                    st.write(f"**문제점:** {rec['problem']}")
                if rec.get("improvement"):
                    st.write(f"**개선방향:** {rec['improvement']}")
                repeat = rec.get("repeat_count", 0)
                if repeat >= 2:
                    st.caption(f"🔁 반복 지적 {repeat}회")

        st.markdown("---")

    # 직접 입력 기록
    if manual_records:
        st.markdown("**📝 직접 입력 / 즉석 분류 기록**")
        for i, rec in enumerate(reversed(manual_records)):
            part_icon = {"안전계획":"🚇","안전보건":"🏥","재난안전":"🌪️"}.get(
                rec.get("ai_part",""),"📋")
            risk_icon = {"상":"🔴","중":"🟡","하":"🟢"}.get(rec.get("ai_risk",""),"⚪")
            with st.expander(
                f"{part_icon} {risk_icon} [{rec.get('timestamp','')}] "
                f"{rec.get('title','')} — {rec.get('department','')}",
                expanded=False
            ):
                c1,c2,c3 = st.columns(3)
                c1.write(f"**파트:** {rec.get('ai_part','-')}")
                c2.write(f"**심사구분:** {rec.get('audit_type','-')}")
                c3.write(f"**리스크:** {rec.get('ai_risk','-')}")
                if rec.get("problem"):
                    st.write(f"**문제점:** {rec['problem']}")
                if rec.get("improvement"):
                    st.write(f"**개선방향:** {rec['improvement']}")
                if st.button("🗑️ 삭제", key=f"del_rec_{i}",
                             use_container_width=True):
                    idx = records.index(rec)
                    _delete_field_record(idx)
                    st.rerun()


# ─────────────────────────────────────────
# 현장 기록 저장/로드/삭제
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


def _export_records_excel(records: list):
    df = pd.DataFrame(records)
    col_map = {
        "timestamp":"기록일시","department":"담당부서","title":"지적사항",
        "audit_type":"심사구분","ai_part":"파트","ai_risk":"리스크",
        "problem":"현황및문제점","improvement":"개선방향",
        "ai_reason":"분류이유","source":"입력방법",
        "repeat_count":"반복횟수","checklist_code":"체크리스트코드"
    }
    df     = df.rename(columns=col_map)
    avail  = [v for v in col_map.values() if v in df.columns]
    df     = df[avail]
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