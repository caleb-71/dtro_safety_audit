# core/action_analyzer.py
# 조치 이행실태 분석 엔진 (신규, 2026-07)
#
# [역할]
# 추진실적(action_result) 텍스트를 분석해서 각 지적사항의
# 조치상태를 4단계로 판정하고, 부서별·파트별·연도별 이행률을 집계합니다.
#
# [조치상태 4단계]
#   완료    : 구체적 조치 내용이 기술된 완료 건
#   형식적  : "조치완료" 한 줄 등 내용 없는 완료 처리 (실질 이행 확인 필요)
#   진행중  : 추진 중, 예정, 검토 중인 건
#   미확인  : 추진실적이 비어 있거나 판단 불가 (미조치 가능성)
#
# [설계 원칙]
# 대량 데이터를 매번 LLM으로 판정하면 느리므로 규칙(키워드) 기반으로
# 판정합니다. 규칙 기반은 재현 가능하고 판정 근거를 설명할 수 있어
# 심사 업무 특성에 맞습니다.

import logging
import pandas as pd

logger = logging.getLogger(__name__)

# 진행중 신호를 완료 신호보다 먼저 검사 ("설치 완료 예정" → 진행중)
IN_PROGRESS_PATTERNS = [
    "추진중", "추진 중", "진행중", "진행 중", "예정",
    "검토중", "검토 중", "계획중", "계획 중", "협의중", "협의 중",
    "발주", "설계중", "설계 중", "공사중", "공사 중", "준비중", "준비 중",
]
COMPLETE_PATTERNS = [
    "완료", "조치함", "시행함", "개선함", "정비함", "교체함",
    "설치함", "보완함", "실시함", "제정", "개정", "수립",
]
# 형식적 완료 문구 (preprocessor.TRIVIAL_RESULT_PATTERNS 와 동일 기준)
TRIVIAL_PATTERNS = [
    "조치완료", "조치 완료", "이행완료", "이행 완료",
    "시행완료", "시행 완료", "완료", "처리완료",
    "해당없음", "해당 없음", "없음",
]

STATUS_ORDER = ["완료", "형식적", "진행중", "미확인"]


def judge_action_status(action_result: str) -> str:
    """
    추진실적 텍스트 하나를 4단계 조치상태로 판정합니다.
    1. 비어있음/무의미      → 미확인
    2. 20자 이하 형식 문구  → 형식적
    3. 진행/예정 신호 포함  → 진행중
    4. 완료 신호 포함       → 완료
    5. 그 외                → 진행중 (보수적 판정)
    """
    text = str(action_result).strip()

    if not text or text in ("nan", "None", "내용 없음", "-"):
        return "미확인"

    if len(text) <= 20:
        for pattern in TRIVIAL_PATTERNS:
            if pattern in text:
                return "형식적"

    for pattern in IN_PROGRESS_PATTERNS:
        if pattern in text:
            return "진행중"

    for pattern in COMPLETE_PATTERNS:
        if pattern in text:
            return "완료"

    return "진행중"


def add_action_status(df: pd.DataFrame) -> pd.DataFrame:
    """action_result 를 판정해 action_status 컬럼을 추가합니다. (LLM 호출 없음 — 즉시 처리)"""
    if df is None or df.empty:
        return df

    df = df.copy()
    if "action_result" in df.columns:
        df["action_status"] = df["action_result"].apply(judge_action_status)
    else:
        df["action_status"] = "미확인"
    return df


def action_summary(df: pd.DataFrame) -> dict:
    """전체 이행실태 요약. 이행률 = 완료 ÷ 전체 (형식적 완료는 제외)"""
    if df is None or df.empty or "action_status" not in df.columns:
        return {"total": 0, "완료": 0, "형식적": 0, "진행중": 0, "미확인": 0, "이행률": 0.0}

    counts = df["action_status"].value_counts().to_dict()
    total  = len(df)
    done   = counts.get("완료", 0)

    return {
        "total":   total,
        "완료":    done,
        "형식적":  counts.get("형식적", 0),
        "진행중":  counts.get("진행중", 0),
        "미확인":  counts.get("미확인", 0),
        "이행률":  round(done / total * 100, 1) if total > 0 else 0.0,
    }


def action_rate_by_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    그룹(department/ai_part/year)별 이행률 표.
    이행률 낮은 순 정렬 — 컨설팅 우선 대상이 위로 오도록.
    """
    if (df is None or df.empty
            or group_col not in df.columns
            or "action_status" not in df.columns):
        return pd.DataFrame()

    rows = []
    for group, gdf in df.groupby(group_col):
        if not str(group).strip() or str(group) in ("nan", "미기재"):
            continue
        counts = gdf["action_status"].value_counts().to_dict()
        total  = len(gdf)
        done   = counts.get("완료", 0)
        rows.append({
            group_col:  group,
            "지적건수": total,
            "완료":     done,
            "형식적":   counts.get("형식적", 0),
            "진행중":   counts.get("진행중", 0),
            "미확인":   counts.get("미확인", 0),
            "이행률(%)": round(done / total * 100, 1) if total > 0 else 0.0,
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("이행률(%)").reset_index(drop=True)


def consulting_targets(
    df: pd.DataFrame,
    min_issues: int = 3,
    max_rate: float = 60.0,
    top_n: int = 5,
) -> pd.DataFrame:
    """
    "지적은 많은데 이행률이 낮은" 부서 = 컨설팅 최우선 대상 자동 도출.
    :param min_issues: 최소 지적 건수 (건수가 적으면 이행률이 왜곡되므로)
    :param max_rate: 이행률 상한
    """
    dept_rate = action_rate_by_group(df, "department")
    if dept_rate.empty:
        return dept_rate

    targets = dept_rate[
        (dept_rate["지적건수"] >= min_issues)
        & (dept_rate["이행률(%)"] <= max_rate)
    ]
    return targets.head(top_n).reset_index(drop=True)
