# core/duplicate_detector.py
# 🔎 AI 기반 중복지적 판별
#
# [배경]
# 심사 지적사항은 작성자마다 표현이 달라 단순 문자열 비교로는
# 중복 여부를 판단할 수 없다.
#   예) "기계기구 및 장비 안전관리 미흡"
#       "기계기구 및 장비 안전관리 미흡   - [개선명령]"
#   → 문자열은 다르지만 동일한 지적사항
#
# 반대로 제목이 비슷해도 내용이 전혀 다르면 중복이 아니다.
#   예) "도급사업 안전보건수준평가 미흡" (평가대상명 작성 문제)
#       "도급사업 안전관리 미흡"        (협의체 공문 직인 누락)
#   → 제목은 유사하나 별개의 지적사항
#
# [판별 방식] 2단계
#   1단계 : 임베딩 유사도로 후보 선별 (nomic-embed-text)
#           제목과 현황및문제점을 각각 임베딩하여
#           "둘 다 유사한" 쌍만 중복 후보로 삼는다
#   2단계 : 경계 구간의 쌍만 LLM(llama3.1:8b)이 문맥으로 최종 판정
#
# LLM 전수 비교는 쌍의 수가 O(n²)로 폭증하여 현실적으로 불가능하므로
# 임베딩으로 범위를 좁힌 뒤 LLM을 제한적으로 사용한다.

import hashlib
import json
import logging
import pickle
from pathlib import Path

import pandas as pd

from config.settings import PROCESSED_DIR, OLLAMA_MODEL
from core.embedder import get_embedding
from core.llm_client import llm_chat

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 판정 임계값
# ─────────────────────────────────────────
# 제목·현황 유사도가 모두 HIGH 이상  → 중복 확정 (LLM 미호출)
# 둘 다 LOW 이상이면서 확정 구간 미만 → LLM 판정 대상
# 그 외                              → 비중복
TITLE_HIGH   = 0.88
PROBLEM_HIGH = 0.82
TITLE_LOW    = 0.70
PROBLEM_LOW  = 0.55

MAX_LLM_PAIRS = 120      # LLM 호출 상한 (시간 보호)
CACHE_FILE = PROCESSED_DIR / "embedding_cache.pkl"


# ─────────────────────────────────────────
# 임베딩 캐시
# ─────────────────────────────────────────
def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"임베딩 캐시 로드 실패: {e}")
    return {}


def _save_cache(cache: dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(cache, f)
    except Exception as e:
        logger.warning(f"임베딩 캐시 저장 실패: {e}")


def _key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _embed_all(texts: list[str], cache: dict, progress_cb=None) -> dict:
    """
    텍스트 목록을 임베딩한다. 캐시에 있으면 재사용한다.
    :return: {텍스트: 벡터}
    """
    uniq = sorted({t for t in texts if t and t.strip()})
    todo = [t for t in uniq if _key(t) not in cache]

    for i, t in enumerate(todo):
        vec = get_embedding(t)
        if vec:
            cache[_key(t)] = vec
        if progress_cb and (i + 1) % 5 == 0:
            progress_cb(i + 1, len(todo))

    if progress_cb:
        progress_cb(len(todo), len(todo))

    return {t: cache.get(_key(t), []) for t in uniq}


# ─────────────────────────────────────────
# 코사인 유사도
# ─────────────────────────────────────────
def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ─────────────────────────────────────────
# LLM 최종 판정
# ─────────────────────────────────────────
def _llm_judge(a_title, a_problem, b_title, b_problem) -> tuple[bool, str]:
    """
    두 지적사항이 실질적으로 동일한 사안인지 LLM이 판정한다.
    :return: (중복여부, 사유)
    """
    prompt = f"""당신은 대구교통공사 자체종합안전심사 전문가입니다.
아래 두 지적사항이 '실질적으로 동일한 사안'인지 판정하세요.

[지적사항 A]
제목: {a_title}
현황및문제점: {a_problem}

[지적사항 B]
제목: {b_title}
현황및문제점: {b_problem}

[판정 기준]
1. 제목의 표현이 달라도 지적하는 대상과 문제점이 같으면 '중복'입니다
2. 제목이 비슷해도 지적하는 구체적 내용이 다르면 '별개'입니다
3. 지적 대상 설비·서류·행위가 무엇인지를 기준으로 판단하세요

[응답 형식]
아래 JSON 형식으로만 답변하고 다른 설명은 붙이지 마세요.
{{"판정": "중복" 또는 "별개", "사유": "20자 이내"}}"""

    try:
        res = llm_chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        text = res["message"]["content"].strip()

        # JSON 파싱 (코드펜스 등 제거)
        text = text.replace("```json", "").replace("```", "").strip()
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            data = json.loads(text[s:e + 1])
            verdict = str(data.get("판정", "")).strip()
            reason = str(data.get("사유", "")).strip()
            return (verdict == "중복"), reason

        # JSON 실패 시 문자열 기반 보조 판정
        return ("중복" in text and "별개" not in text), text[:20]

    except Exception as e:
        logger.error(f"LLM 중복판정 오류: {e}")
        return False, "판정 실패"


# ─────────────────────────────────────────
# Union-Find (중복 그룹 형성)
# ─────────────────────────────────────────
class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# ─────────────────────────────────────────
# 메인 — 중복지적 판별
# ─────────────────────────────────────────
def detect_duplicates(
    df: pd.DataFrame,
    scope: str = "dept",
    use_llm: bool = True,
    progress_cb=None,
    log_cb=None,
    title_high: float = TITLE_HIGH,
    problem_high: float = PROBLEM_HIGH,
    title_low: float = TITLE_LOW,
    problem_low: float = PROBLEM_LOW,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    지적사항의 중복 여부를 AI로 판별한다.

    :param df: 대상 데이터 (title, problem, department 컬럼 필요)
    :param scope: "dept" = 같은 부서 안에서만 비교 (중복지적 감점용)
                  "all"  = 전 부서를 통틀어 비교 (전사 공통취약 도출용)
    :param use_llm: 경계 구간을 LLM으로 검증할지 여부
    :param title_high/problem_high: 이 값 이상이면 LLM 없이 중복 확정
    :param title_low/problem_low: 이 값 미만이면 비교 대상에서 제외
    :param progress_cb: 진행률 콜백 (현재, 전체)
    :param log_cb: 로그 메시지 콜백
    :return: (그룹번호가 부여된 df, 그룹 요약 df)
    """
    if df is None or df.empty or "title" not in df.columns:
        return df, pd.DataFrame()

    work = df.reset_index(drop=True).copy()
    work["_title_txt"] = work["title"].fillna("").astype(str).str.strip()
    work["_prob_txt"] = (
        work["problem"].fillna("").astype(str).str.strip()
        if "problem" in work.columns else ""
    )

    def say(msg):
        logger.info(msg)
        if log_cb:
            log_cb(msg)

    # ── 1) 임베딩 ──
    say("임베딩 계산 중...")
    cache = _load_cache()
    texts = work["_title_txt"].tolist() + work["_prob_txt"].tolist()
    vecs = _embed_all(texts, cache, progress_cb)
    _save_cache(cache)

    # ── 2) 비교 대상 쌍 구성 ──
    if scope == "dept" and "department" in work.columns:
        groups = [g.index.tolist() for _, g in work.groupby("department")]
    else:
        groups = [work.index.tolist()]

    uf = _UF(len(work))
    llm_pairs = []
    auto_cnt = 0

    for idx_list in groups:
        for ii in range(len(idx_list)):
            for jj in range(ii + 1, len(idx_list)):
                i, j = idx_list[ii], idx_list[jj]

                st_ = _cosine(vecs.get(work.at[i, "_title_txt"], []),
                              vecs.get(work.at[j, "_title_txt"], []))
                if st_ < title_low:
                    continue

                sp = _cosine(vecs.get(work.at[i, "_prob_txt"], []),
                             vecs.get(work.at[j, "_prob_txt"], []))
                if sp < problem_low:
                    continue

                if st_ >= title_high and sp >= problem_high:
                    uf.union(i, j)          # 확정 중복
                    auto_cnt += 1
                else:
                    llm_pairs.append((i, j, st_, sp))

    say(f"임베딩 판정 완료 — 확정 {auto_cnt}쌍 / LLM 검증 대상 {len(llm_pairs)}쌍")

    # ── 3) 경계 구간 LLM 판정 ──
    judged = []
    if use_llm and llm_pairs:
        # 유사도가 높은 쌍부터 처리 (상한 초과 시 낮은 쌍은 비중복 처리)
        llm_pairs.sort(key=lambda x: -(x[2] + x[3]))
        target = llm_pairs[:MAX_LLM_PAIRS]
        if len(llm_pairs) > MAX_LLM_PAIRS:
            say(f"⚠ LLM 검증 대상이 많아 상위 {MAX_LLM_PAIRS}쌍만 판정합니다")

        for n, (i, j, st_, sp) in enumerate(target, 1):
            ok, reason = _llm_judge(
                work.at[i, "_title_txt"], work.at[i, "_prob_txt"],
                work.at[j, "_title_txt"], work.at[j, "_prob_txt"],
            )
            if ok:
                uf.union(i, j)
            judged.append({
                "A": work.at[i, "_title_txt"], "B": work.at[j, "_title_txt"],
                "제목유사도": round(st_, 3), "현황유사도": round(sp, 3),
                "판정": "중복" if ok else "별개", "사유": reason,
            })
            if progress_cb:
                progress_cb(n, len(target))

        say(f"LLM 판정 완료 — 중복 {sum(1 for x in judged if x['판정']=='중복')}쌍")

    # ── 4) 그룹 번호 부여 ──
    roots = [uf.find(i) for i in range(len(work))]
    sizes = pd.Series(roots).value_counts().to_dict()

    gmap, gid = {}, 0
    for r in roots:
        if sizes[r] >= 2 and r not in gmap:
            gid += 1
            gmap[r] = gid

    work["dup_group"] = [gmap.get(r, 0) for r in roots]
    work["dup_count"] = [sizes[r] if sizes[r] >= 2 else 1 for r in roots]

    # ── 5) 그룹 요약 ──
    rows = []
    for g in range(1, gid + 1):
        sub = work[work["dup_group"] == g]
        rep = sub.iloc[0]
        rows.append({
            "그룹": g,
            "대표 제목": rep["_title_txt"],
            "대표 현황및문제점": rep["_prob_txt"][:120],
            "중복건수": len(sub),
            "부서": " / ".join(sorted(sub["department"].unique()))
                     if "department" in sub.columns else "",
            "연도": " / ".join(
                sorted({str(y) for y in sub["year"].tolist()})
            ) if "year" in sub.columns else "",
        })

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values("중복건수", ascending=False).reset_index(drop=True)

    work = work.drop(columns=["_title_txt", "_prob_txt"])
    work.attrs["llm_judged"] = judged
    return work, summary


# ─────────────────────────────────────────
# 부서별 중복 건수 집계
# ─────────────────────────────────────────
def duplicate_summary_by_dept(df: pd.DataFrame) -> pd.DataFrame:
    """
    detect_duplicates 결과를 부서별로 집계한다.
    채점표의 '중복지적 건수' 입력값으로 사용한다.

    중복 건수 산정 : 그룹의 두 번째 건부터 중복으로 계상
                     (3건 그룹 → 최초 1건 + 중복 2건)
    """
    if df is None or df.empty or "dup_group" not in df.columns:
        return pd.DataFrame()

    rows = []
    for dept, d in df.groupby("department"):
        dup = d[d["dup_group"] > 0]
        n_group = dup["dup_group"].nunique()
        n_dup = len(dup) - n_group if n_group else 0
        rows.append({
            "부서": dept,
            "총지적": len(d),
            "중복그룹수": n_group,
            "중복지적건수": max(n_dup, 0),
            "감점(0.1점/건)": round(max(n_dup, 0) * 0.1, 2),
        })

    out = pd.DataFrame(rows)
    return out.sort_values("중복지적건수", ascending=False).reset_index(drop=True)