# 🚇 DTRO 자체종합안전심사 AI 분석 시스템

> 대구도시철도공사(DTRO) 철도안전관리체계 기반  
> AI를 활용한 자체종합안전심사 이력 분석 및 법령 근거 자동 생성 플랫폼

---

## 📌 프로젝트 소개

과거 자체종합안전심사 이력 데이터를 AI가 자동 분류·분석하고,
보유한 법령/규정 PDF를 기반으로 지적사항의 법적 근거를 자동 생성하는 시스템입니다.

- **완전 폐쇄망 운영** — 로컬 AI 모델(llama3.1:8b)만 사용, 외부 인터넷 불필요
- **RAG 아키텍처** — 과거 유사 사례 검색 및 AI 분류
- **법령 RAG** — PDF 법령/규정에서 지적 근거 자동 추출
- **Streamlit** 웹 인터페이스로 누구나 쉽게 사용 가능

---

## 🎯 주요 기능

| 메뉴 | 기능 |
|------|------|
| 📊 홈 대시보드 | 연도별·파트별 현황, KPI, 리스크 요약 |
| 📁 데이터 업로드 | 연도별 엑셀 파일 업로드/삭제/재처리 |
| 🤖 AI 분류 실행 | 지적사항 3개 파트 자동 분류 + 리스크 판정 |
| 📈 통계 분석 | 파트별·연도별 트렌드, 반복 지적 TOP10 |
| 📄 보고서 생성 | 엑셀 + 워드 보고서 자동 생성 |
| 💬 AI 질의응답 | 자연어로 심사 데이터 질의, 대화 히스토리 저장 |
| 📋 현장 심사 도우미 | 즉석 분류, 유사사례 검색, 체크리스트, 현장 기록 |
| ⚖️ 법령/규정 관리 | PDF 등록, 법령DB 구축, 근거 자동 생성 |

---

## 🗂️ 분류 파트

```
안전계획  → 철도사고, 준사고, 운행장애, 운행관리 관련
안전보건  → 산업안전보건법, TBM, MSDS, 근로자 보건 관련
재난안전  → 자연재난(호우/태풍/지진 등), 비상훈련 관련
```

---

## 🏗️ 시스템 아키텍처

```
엑셀 데이터 (연도별 심사이력)          PDF 법령/규정
        ↓                                    ↓
   데이터 전처리                        텍스트 추출·청크 분할
        ↓                                    ↓
nomic-embed-text                    nomic-embed-text
        ↓                                    ↓
  벡터DB: 심사이력                    벡터DB: 법령문서
  (ChromaDB)                          (ChromaDB)
        ↓                                    ↓
  유사사례 검색 (RAG)          +    관련 법령 검색 (RAG)
                    ↓
             llama3.1:8b
                    ↓
     파트 분류 + 리스크 등급 + 법령 근거
```

---

## ⚙️ 설치 방법

### 사전 요구사항

- Python 3.11.9
- [Ollama](https://ollama.com) 설치
- NVIDIA GPU (선택사항, CPU만으로도 동작)

### Ollama 모델 다운로드

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

> ⚠️ Ollama 모델 경로에 한글이 포함되면 오류가 발생합니다.
> 환경변수를 반드시 설정하세요:
> ```
> OLLAMA_MODELS = C:\ollama\models
> ```

### 환경 설정

```bash
# 1. 저장소 클론
git clone https://github.com/아이디/dtro_safety_audit.git
cd dtro_safety_audit

# 2. 가상환경 생성
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. 라이브러리 설치
pip install -r requirements.txt
```

### 로컬 데이터 폴더 생성

GitHub에서 클론 후 아래 폴더를 직접 생성하세요.
(데이터 파일은 보안/용량 이유로 GitHub에 포함되지 않습니다)

```bash
mkdir data\raw
mkdir data\processed
mkdir data\vector_db
mkdir data\legal_docs\guidelines
mkdir data\legal_docs\laws
mkdir data\legal_docs\regulations
mkdir data\legal_docs\sop
mkdir data\legal_db
mkdir output_files
mkdir logs
```

| 폴더 | 내용 |
|------|------|
| `data/raw/` | 연도별 심사이력 엑셀 파일 복사 |
| `data/legal_docs/laws/` | 법률 PDF 복사 (철도안전법 등) |
| `data/legal_docs/regulations/` | 규정 PDF 복사 |
| `data/legal_docs/guidelines/` | 가이드라인 PDF 복사 |
| `data/legal_docs/sop/` | 표준운영절차 PDF 복사 |

---

## 🚀 실행 방법

```bash
python main.py
```

브라우저에서 자동으로 열립니다:
```
http://localhost:8501
```

### 최초 실행 순서

```
1. 📁 데이터 업로드  → 연도별 엑셀 파일 업로드
2. 🤖 AI 분류 실행  → 벡터DB 구축 → AI 분류 시작
3. ⚖️ 법령/규정 관리 → 법령DB 구축
4. 💬 AI 질의응답   → 자유롭게 질의
5. 📄 보고서 생성   → 분석 보고서 다운로드
```

---

## 📁 프로젝트 구조

```
dtro_safety_audit/
│
├── core/                      # AI 핵심 엔진
│   ├── classifier.py          # AI 분류 엔진 (llama3.1:8b)
│   ├── rag_engine.py          # RAG 검색 엔진
│   ├── embedder.py            # 텍스트 임베딩
│   └── legal_engine.py        # 법령 검색 엔진
│
├── data/                      # 데이터 처리
│   ├── loader.py              # 엑셀 로딩
│   ├── preprocessor.py        # 데이터 전처리
│   ├── vector_store.py        # 심사이력 벡터DB
│   ├── legal_store.py         # 법령문서 벡터DB
│   │
│   ├── raw/                   # 엑셀 원본 (git 제외)
│   ├── processed/             # 처리된 CSV (git 제외)
│   ├── vector_db/             # 심사 벡터DB (git 제외)
│   ├── legal_docs/            # PDF 원본 (git 제외)
│   │   ├── laws/
│   │   ├── regulations/
│   │   ├── guidelines/
│   │   └── sop/
│   └── legal_db/              # 법령 벡터DB (git 제외)
│
├── pages/                     # Streamlit 화면
│   ├── page_home.py           # 홈 대시보드
│   ├── page_upload.py         # 데이터 업로드
│   ├── page_classify.py       # AI 분류 실행
│   ├── page_analysis.py       # 통계 분석
│   ├── page_report.py         # 보고서 생성
│   ├── page_chat.py           # AI 질의응답
│   ├── page_field.py          # 현장 심사 도우미
│   └── page_legal.py          # 법령/규정 관리
│
├── output/                    # 결과물 생성
│   ├── excel_writer.py        # 엑셀 저장
│   └── report_builder.py      # 워드 보고서 생성
│
├── config/                    # 설정
│   ├── settings.py            # 전역 설정 (경로, 모델명 등)
│   └── keywords.py            # 분류 키워드 사전
│
├── output_files/              # 생성된 결과물 (git 제외)
│   ├── chat_history/          # AI 대화 히스토리
│   └── field_records/         # 현장 심사 기록
│
├── app.py                     # Streamlit 진입점
├── main.py                    # 실행 파일
├── requirements.txt           # 라이브러리 목록
├── .gitignore                 # git 제외 목록
└── README.md                  # 프로젝트 설명
```

---

## 🛠️ 기술 스택

| 구분 | 기술 | 버전 |
|------|------|------|
| Language | Python | 3.11.9 |
| UI Framework | Streamlit | 1.40+ |
| AI 분류 모델 | llama3.1:8b (Ollama) | 로컬 |
| 임베딩 모델 | nomic-embed-text | 로컬 |
| 벡터DB | ChromaDB | 최신 |
| PDF 파싱 | PyMuPDF (fitz) | 최신 |
| 데이터 처리 | pandas, openpyxl | 최신 |
| 시각화 | matplotlib, seaborn | 최신 |
| 보고서 | python-docx | 최신 |

---

## 📊 엑셀 데이터 형식

입력 엑셀 파일 필수 컬럼:

| 컬럼명 | 영문명 | 설명 |
|--------|--------|------|
| 순번 | seq | 고유 순번 |
| 심사년도 | year | 심사 연도 |
| 관리번호 | mgmt_no | 관리 번호 |
| 세부번호 | detail_no | 세부 번호 |
| 심사구분 | audit_type | 개선권고/현지시정/시정명령 |
| 제목 | title | 지적사항 제목 |
| 현황및문제점 | problem | 상세 내용 |
| 개선방안 | improvement | 개선 방향 |
| 추진실적 | action_result | 조치 결과 |
| 담당부서 | department | 해당 부서명 |

---

## 📂 법령/규정 PDF 분류 기준

| 폴더 | 분류 | 예시 |
|------|------|------|
| `laws/` | 법률 | 철도안전법, 산업안전보건법, 재난안전관리기본법 |
| `regulations/` | 규정 | 시행령, 시행규칙, 사내 규정 |
| `guidelines/` | 가이드라인 | 국토교통부 지침, 안전관리 가이드 |
| `sop/` | 표준운영절차 | 현장 SOP, 비상대응 절차서 |

---

## ⚠️ 주의사항

- 본 시스템은 **완전 로컬(폐쇄망)** 환경에서 동작합니다
- 외부 인터넷 연결 없이 AI 분류 및 법령 검색이 가능합니다
- Ollama 모델 경로는 반드시 **영문 경로**로 설정하세요
- PDF 파일은 **텍스트 추출 가능한 파일**이어야 합니다 (스캔본 불가)
- 법령 PDF 추가 후 반드시 **법령DB 재구축**을 실행하세요

---

## 💻 개발 환경

| 항목 | 내용 |
|------|------|
| OS | Windows 10/11 |
| IDE | PyCharm |
| Python | 3.11.9 |
| Ollama | 0.24.0+ |
| 현재 AI 모델 | llama3.1:8b |
| RTX 4070 이전 시 | qwen2.5:14b 권장 |

---

## 🔄 향후 업그레이드 계획

```
단기:  과거 10년 데이터 추가 → 트렌드 분석 강화
중기:  26년 심사 결과 실시간 입력 기능
장기:  RTX 4070 PC 이전 → qwen2.5:14b 모델 전환
       예측 모델 개발 (취약 부서 사전 예측)
```

---

*본 시스템은 AI 자동 분석 결과를 제공하며,*  
*최종 심사 계획 수립 시 실무자 검토를 반드시 병행하시기 바랍니다.*