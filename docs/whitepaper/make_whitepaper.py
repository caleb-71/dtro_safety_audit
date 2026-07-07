# docs/whitepaper/make_whitepaper.py
# 자체종합안전심사 AI 분석 플랫폼 백서(.hwpx) 생성 스크립트
#
# [사용법 — 파이참 터미널]
#   pip install lxml
#   python docs\whitepaper\make_whitepaper.py
#
# [생성물] 같은 폴더의 DTRO_Safety_Audit_백서.hwpx
#
# [원리] HWPX는 ZIP 기반 XML 문서(OWPML)이므로, 본문(section0.xml)을
# 코드로 생성한 뒤 Claude 스킬의 build_hwpx.py로 패키징한다.

import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE         = Path(__file__).resolve().parent
SECTION_PATH = HERE / "section0.xml"
OUTPUT_PATH  = HERE / "DTRO_Safety_Audit_백서.hwpx"

# Claude(Cowork) hwpx 스킬의 빌드 스크립트 경로 — 환경이 바뀌면 이 경로만 수정
BUILD_SCRIPT = Path(
    r"C:\Users\정우연\AppData\Roaming\Claude\local-agent-mode-sessions"
    r"\skills-plugin\f8ab4074-298c-431a-8655-effdf22c6beb"
    r"\6d157a29-1cc1-48d1-99c5-402b4ec07ec4\skills\hwpx\scripts\build_hwpx.py"
)

# ─────────────────────────────────────────
# section0.xml 골격 — 첫 문단(secPr: A4, 여백 등)은 report 템플릿에서 복사
# ─────────────────────────────────────────
XML_HEAD = '''<?xml version='1.0' encoding='UTF-8'?>
<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" xmlns:epub="http://www.idpf.org/2007/ops" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">
  <hp:p id="1000000001" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">
        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>
        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>
        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>
        <hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>
        <hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">
          <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>
        </hp:pagePr>
        <hp:footNotePr>
          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>
          <hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>
          <hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>
          <hp:numbering type="CONTINUOUS" newNum="1"/>
          <hp:placement place="EACH_COLUMN" beneathText="0"/>
        </hp:footNotePr>
        <hp:endNotePr>
          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>
          <hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>
          <hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>
          <hp:numbering type="CONTINUOUS" newNum="1"/>
          <hp:placement place="END_OF_DOCUMENT" beneathText="0"/>
        </hp:endNotePr>
        <hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>
        </hp:pageBorderFill>
        <hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>
        </hp:pageBorderFill>
        <hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>
        </hp:pageBorderFill>
      </hp:secPr>
      <hp:ctrl>
        <hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/>
      </hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="0">
      <hp:t/>
    </hp:run>
  </hp:p>'''

# ─────────────────────────────────────────
# 문단/표 생성 헬퍼 (report 템플릿 스타일 ID 사용)
#   charPr: 7=20pt볼드 8=14pt볼드 9=표헤더볼드 10=볼드밑줄 11=9pt 13=12pt섹션
#   paraPr: 0=본문 20=가운데 21=셀가운데 22=셀양쪽 24=□들여쓰기 25=○들여쓰기
#           26=−들여쓰기 27=섹션헤더(상하단 테두리선)
# ─────────────────────────────────────────
_pid = 1000000100


def nid() -> str:
    global _pid
    _pid += 1
    return str(_pid)


def para(text: str = "", ppr: str = "0", cpr: str = "0",
         page_break: bool = False) -> str:
    pb = "1" if page_break else "0"
    t = f"<hp:t>{escape(text)}</hp:t>" if text else "<hp:t/>"
    return (f'<hp:p id="{nid()}" paraPrIDRef="{ppr}" styleIDRef="0" '
            f'pageBreak="{pb}" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{cpr}">{t}</hp:run></hp:p>')


def title(text):  return para(text, ppr="20", cpr="7")            # 표지 제목
def center(text): return para(text, ppr="20", cpr="0")            # 가운데 정렬
def sect(text):   return para(text, ppr="27", cpr="13", page_break=True)  # 장 제목
def h2(text):     return para("□ " + text, ppr="24", cpr="10")    # 절 제목
def item(text):   return para("○ " + text, ppr="25", cpr="0")     # 항목
def sub(text):    return para("- " + text, ppr="26", cpr="0")     # 하위 항목
def note(text):   return para(text, ppr="25", cpr="11")           # 9pt 주석
def body(text):   return para(text, ppr="0", cpr="0")             # 일반 본문
def blank():      return para()                                    # 빈 줄
def shot(text):   return para("▶ [스크린샷 삽입: " + text + "]", ppr="25", cpr="10")


def _cell(text, w, h, col, row, bf, ppr, cpr) -> str:
    return (f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" '
            f'borderFillIDRef="{bf}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" '
            f'hasTextRef="0" hasNumRef="0">'
            f'<hp:p paraPrIDRef="{ppr}" styleIDRef="0" pageBreak="0" columnBreak="0" '
            f'merged="0" id="{nid()}">'
            f'<hp:run charPrIDRef="{cpr}"><hp:t>{escape(text)}</hp:t></hp:run></hp:p>'
            f'</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{w}" height="{h}"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
            f'</hp:tc>')


def table(headers: list, rows: list, widths: list, row_h: int = 2600) -> str:
    """표 생성. 열 너비 합은 본문폭 42520 HWPUNIT이어야 한다."""
    assert sum(widths) == 42520, f"열 너비 합이 42520이어야 함: {sum(widths)}"
    n_rows = len(rows) + 1
    trs = ["<hp:tr>" + "".join(
        _cell(str(h), widths[c], row_h, c, 0, "4", "21", "9")
        for c, h in enumerate(headers)) + "</hp:tr>"]
    for r, row in enumerate(rows, 1):
        trs.append("<hp:tr>" + "".join(
            _cell(str(v), widths[c], row_h, c, r, "3", "22", "0")
            for c, v in enumerate(row)) + "</hp:tr>")
    tbl = (f'<hp:tbl id="{nid()}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
           f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" '
           f'repeatHeader="1" rowCnt="{n_rows}" colCnt="{len(headers)}" cellSpacing="0" '
           f'borderFillIDRef="3" noAdjust="0">'
           f'<hp:sz width="42520" widthRelTo="ABSOLUTE" height="{row_h * n_rows}" '
           f'heightRelTo="ABSOLUTE" protect="0"/>'
           f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
           f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" '
           f'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           f'<hp:outMargin left="0" right="0" top="141" bottom="141"/>'
           f'<hp:inMargin left="141" right="141" top="141" bottom="141"/>'
           + "".join(trs) + '</hp:tbl>')
    return (f'<hp:p id="{nid()}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0"><hp:run charPrIDRef="0">{tbl}</hp:run></hp:p>')


# === 본문 내용 (아래에 이어서 정의) ===

def build_content() -> list:
    P = []

    # ══════════ 표지 ══════════
    for _ in range(6):
        P.append(blank())
    P.append(title("자체종합안전심사 AI 분석 플랫폼"))
    P.append(title("백    서"))
    P.append(blank())
    P.append(center("(DTRO Safety Audit Platform White Paper)"))
    for _ in range(12):
        P.append(blank())
    P.append(center("2026.  7."))
    P.append(blank())
    P.append(center("대구교통공사  [부서명 기재]"))

    # ══════════ Ⅰ. 개발 배경 및 목적 ══════════
    P.append(sect("Ⅰ. 개발 배경 및 목적"))
    P.append(blank())
    P.append(h2("추진 배경"))
    P.append(item("매년 자체종합안전심사에서 다수의 지적사항이 발생하나, 엑셀 수작업 관리로 분류·집계에 과다한 시간 소요"))
    P.append(item("과거 지적사항과의 연계 분석이 어려워 반복 지적과 취약 부서 파악이 담당자 개인의 경험에 의존"))
    P.append(item("추진실적이 \"조치완료\" 한 줄로 기재되는 등 형식적 이행관리 사례가 있어 실질 이행 확인 체계 필요"))
    P.append(item("안전심사 자료는 내부 민감 정보로서 외부 클라우드 AI 서비스 활용이 곤란하여 보안성 확보가 전제조건"))
    P.append(blank())
    P.append(h2("개발 목적"))
    P.append(item("AI 기반 지적사항 자동 분류(안전계획·안전보건·재난안전)로 심사 준비 업무 효율화"))
    P.append(item("축적 데이터 분석으로 반복 지적·고위험 분야를 사전 식별하여 연간 심사계획 수립 지원"))
    P.append(item("조치 이행실태 자동 진단으로 형식적 완료 관행을 개선하고 컨설팅 대상 부서 도출"))
    P.append(item("지적사항별 법령 근거 자동 연계로 심사 결과의 법적 정확성 제고"))
    P.append(item("외부 전송이 전혀 없는 온프레미스(업무용 PC 내) AI 구축으로 보안성 확보"))

    # ══════════ Ⅱ. 주요 기능 ══════════
    P.append(sect("Ⅱ. 주요 기능"))
    P.append(blank())
    P.append(h2("1. 데이터 업로드 및 자동 전처리"))
    P.append(item("연도별 지적사항 엑셀 업로드 시 컬럼 자동 인식, 결측·중복 정비 후 표준 데이터셋 구축"))
    P.append(shot("데이터 업로드 화면"))
    P.append(blank())
    P.append(h2("2. AI 자동 분류"))
    P.append(item("로컬 LLM이 지적사항을 3개 파트(안전계획·안전보건·재난안전)로 자동 분류하고 리스크 등급(상·중·하) 부여"))
    P.append(item("반복 지적 여부를 특정 연도가 아닌 전체 연도 이력 기준으로 자동 산정하여 누락 방지"))
    P.append(shot("AI 분류 실행 화면"))
    P.append(blank())
    P.append(h2("3. 분석 대시보드 (부서별 필터링)"))
    P.append(item("파트별 현황, 연도별 트렌드, 리스크 분석, 반복 지적 TOP, 조치 이행실태의 5개 분석 탭 제공"))
    P.append(item("연도·파트·부서 필터로 원하는 범위만 선택 조회"))
    P.append(item("이행실태 탭: 조치상태 4단계(완료·형식적·진행중·미확인) 판정, 부서별 이행률, 컨설팅 우선 대상 자동 도출"))
    P.append(shot("분석 대시보드 — 파트별 현황 탭"))
    P.append(shot("분석 대시보드 — 조치 이행실태 탭"))
    P.append(blank())
    P.append(h2("4. 부서별 심사 지원"))
    P.append(item("부서 선택 시 핵심 지표(지적건수·시정명령·리스크 상·반복 지적·조치 이행률)와 지적 이력을 한 화면에 제공"))
    P.append(item("지적사항별 관련 법령 근거(철도안전법, 산업안전보건법 등) 자동 연계 및 유사 사례 검색"))
    P.append(shot("부서별 조회 화면"))
    P.append(blank())
    P.append(h2("5. AI Q&A (RAG 기반 검색·질의응답)"))
    P.append(item("지적사항 벡터DB와 법령 데이터를 근거로 자연어 질의에 답변 — 예: \"승강장 관련 반복 지적은?\", \"이행률이 낮은 부서는?\""))
    P.append(item("검색된 실제 데이터를 근거로만 답변을 생성하여 허위 생성(환각) 최소화"))
    P.append(shot("AI 질의응답 화면"))
    P.append(blank())
    P.append(h2("6. 보고서 자동 생성"))
    P.append(item("분류 결과 엑셀과 8장 구성 워드 보고서(개요→분류 요약→파트별→부서별→리스크→이행실태→반복 지적→컨설팅 권고) 자동 생성"))
    P.append(item("각 장에 집계 수치를 근거로 한 AI 해설과 파트별 AI 컨설팅 의견 자동 삽입"))
    P.append(shot("보고서 생성 화면 및 생성된 워드 보고서 표지"))

    # ══════════ Ⅲ. 기술 구현 내용 ══════════
    P.append(sect("Ⅲ. 기술 구현 내용"))
    P.append(blank())
    P.append(h2("시스템 구성"))
    P.append(table(
        ["구성 요소", "적용 기술", "역할"],
        [
            ["사용자 화면", "Streamlit (Python)", "웹 기반 대시보드 UI"],
            ["AI 분류·해설", "Ollama 로컬 LLM", "지적사항 분류, 보고서 해설·컨설팅 의견 생성"],
            ["검색(RAG)", "ChromaDB 벡터DB", "유사 지적사례·법령의 의미 기반 검색"],
            ["데이터 처리", "pandas", "전처리, 통계 집계, 이행률 산출"],
            ["이행 판정", "규칙 기반 엔진", "추진실적의 4단계 조치상태 판정"],
            ["보고서 출력", "python-docx, matplotlib", "워드 보고서·차트 자동 생성"],
        ],
        [8500, 12000, 22020],
    ))
    P.append(blank())
    P.append(h2("핵심 구현 특징"))
    P.append(item("온프레미스 AI: 데이터와 LLM이 모두 업무용 PC 내부에서 동작하며 외부 서버 전송이 전혀 없음"))
    P.append(item("RAG 구조: 답변·해설 생성 시 실제 지적 데이터와 법령 조문을 먼저 검색하여 근거로 제공"))
    P.append(item("환각 억제: 보고서 AI 해설은 집계 수치만 인용하도록 프롬프트를 제한하고 저온도(0.2)로 생성"))
    P.append(item("장애 허용 설계: LLM 미가동 시에도 통계 기반 분석·보고서는 정상 생성"))
    P.append(item("규칙 기반 이행 판정: 판정 기준이 명문화되어 근거 설명이 가능하고 재현성·객관성 확보"))

    # ══════════ Ⅳ. 도입 효과 및 성과 ══════════
    P.append(sect("Ⅳ. 도입 효과 및 성과"))
    P.append(blank())
    P.append(h2("정량 효과"))
    P.append(note("※ [확인 필요] 표시는 실제 측정값으로 교체하십시오."))
    P.append(table(
        ["항목", "도입 전", "도입 후", "비고"],
        [
            ["지적사항 분류·집계", "수작업 약 O일 [확인 필요]", "자동 분류 수 분 내", "전량 AI 분류"],
            ["반복 지적 식별", "담당자 기억 의존", "전체 이력 자동 산정", "누락 방지"],
            ["결과보고서 작성", "약 O일 [확인 필요]", "자동 생성 수 분 내", "8장 구성"],
            ["법령 근거 확인", "건별 수동 검색", "지적사항별 자동 연계", "정확성 제고"],
            ["이행률 관리", "형식적 완료 식별 곤란", "4단계 자동 판정·부서별 이행률", "컨설팅 대상 도출"],
        ],
        [9500, 11000, 12020, 10000],
    ))
    P.append(blank())
    P.append(h2("정성 효과"))
    P.append(item("경험 의존적 심사계획을 데이터 기반으로 전환하여 취약 분야·부서에 심사 역량 집중"))
    P.append(item("형식적 완료 건의 가시화로 실질적 조치 이행 문화 유도"))
    P.append(item("부서별 이행률과 컨설팅 우선 대상의 자동 도출로 지적 감소 컨설팅의 객관적 근거 확보"))
    P.append(item("민감 자료의 외부 유출 위험 없이 사내 AI 활용 기반 마련"))

    # ══════════ Ⅴ. 사용자 피드백 및 개선 이력 ══════════
    P.append(sect("Ⅴ. 사용자 피드백 및 개선 이력"))
    P.append(blank())
    P.append(h2("개선 이력"))
    P.append(table(
        ["시기", "개선 내용"],
        [
            ["2025. O. [확인 필요]", "플랫폼 초기 구축 — 데이터 업로드, AI 분류, 분석 대시보드, 보고서 생성"],
            ["2026. 7.", "반복 지적 산정 로직 개선 — 필터 연도가 아닌 전체 이력 기준 산정으로 정확도 향상"],
            ["2026. 7.", "조치 이행실태 분석 신설 — 4단계 판정, 부서별 이행률, 컨설팅 우선 대상 도출"],
            ["2026. 7.", "보고서 8장 확장 — 부서별·이행실태 장 신설, AI 해설·컨설팅 의견 삽입, 기준연도 자동화"],
        ],
        [9000, 33520],
        row_h=3000,
    ))
    P.append(blank())
    P.append(h2("사용자 피드백"))
    P.append(note("※ 아래는 예시 문구이며 실제 사용자 의견으로 교체하십시오."))
    P.append(item("\"분류 결과 검토 시간이 크게 줄었다.\" — 안전심사 담당자 [확인 필요]"))
    P.append(item("\"부서별 이행률 표가 컨설팅 대상 선정에 유용하다.\" — OO처 [확인 필요]"))
    P.append(item("\"지적사항의 법령 근거를 바로 확인할 수 있어 심사 결과 작성이 빨라졌다.\" [확인 필요]"))

    # ══════════ Ⅵ. 공적 활동 기록 ══════════
    P.append(sect("Ⅵ. 공적 활동 기록"))
    P.append(blank())
    P.append(note("※ 아래는 기재 틀이며 실제 활동 내역으로 교체하십시오."))
    P.append(table(
        ["일자", "구분", "내용"],
        [
            ["[확인 필요]", "사내 발표", "업무개선 사례 발표 — 안전심사 AI 분석 플랫폼 구축"],
            ["[확인 필요]", "제안제도", "업무개선 제안 등록"],
            ["[확인 필요]", "대외 공유", "유관기관(타 도시철도 운영기관 등) 사례 공유"],
            ["[확인 필요]", "지식재산", "프로그램 저작권 등록 등"],
        ],
        [7500, 8000, 27020],
    ))
    P.append(blank())
    P.append(blank())
    P.append(body("본 백서는 자체종합안전심사 AI 분석 플랫폼의 개발 배경과 기능, 성과를 기록한 문서로, "
                  "향후 기능 고도화와 타 업무 분야 확산의 기초 자료로 활용하고자 한다."))
    return P


# ─────────────────────────────────────────
# 실행: section0.xml 생성 → build_hwpx.py로 패키징
# ─────────────────────────────────────────
def main():
    parts = [XML_HEAD]
    parts.extend(build_content())
    parts.append("</hs:sec>")
    SECTION_PATH.write_text("".join(parts), encoding="utf-8")
    print(f"[1/2] section0.xml 생성 완료: {SECTION_PATH}")

    if not BUILD_SCRIPT.is_file():
        sys.exit(f"빌드 스크립트를 찾을 수 없습니다: {BUILD_SCRIPT}\n"
                 f"(Claude 앱의 hwpx 스킬 경로가 바뀌었는지 확인하세요)")

    result = subprocess.run([
        sys.executable, str(BUILD_SCRIPT),
        "--template", "report",
        "--section", str(SECTION_PATH),
        "--title", "자체종합안전심사 AI 분석 플랫폼 백서",
        "--creator", "대구교통공사",
        "--output", str(OUTPUT_PATH),
    ])
    if result.returncode == 0:
        print(f"[2/2] 백서 생성 완료: {OUTPUT_PATH}")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
