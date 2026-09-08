"""
engine.py — 학생 프로필 × 대학 데이터 → 전형별 평가 결과.

학생 프로필(student.json) 구조:
{
  "name": "홍길동",
  "gyeyeol": "자연",              # 인문 | 자연 (지원 계열)
  "naesin": {"국어":2.3,"영어":1.8,"수학":2.0,"사회":2.4,"과학":2.2,"한국사":3.0},
  "suneung": {"국어":3,"수학":2,"영어":2,"탐구1":3,"탐구2":4,"한국사":4,
              "수학선택":"미적분","탐구과목":["생명과학","지구과학"]},
  "categories": ["교과","종합"]    # 관심 전형유형(비우면 전체)
}
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model, suneung, gyogwa, assemble, features
from math import exp as _exp, sqrt as _sqrt

_SQRT2 = _sqrt(2.0)


def _erf(x):
    """Abramowitz–Stegun 7.1.26 오차함수 근사 (|오차| < 1.5e-7).

    math.erf 가 있는데 왜 이걸 쓰나 — Dart 쪽(engine.dart)에는 erf 가
    없다. 두 엔진이 **같은 수를 내야** 대조 시험이 성립하므로 같은 식을
    쓴다.
    """
    sign = -1.0 if x < 0 else 1.0
    ax = abs(x)
    a1, a2, a3 = 0.254829592, -0.284496736, 1.421413741
    a4, a5, p = -1.453152027, 1.061405429, 0.3275911
    t = 1.0 / (1.0 + p * ax)
    y = 1.0 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * _exp(-ax * ax)
    return sign * y

# 5등급제(2025 고1~) → 9등급제 근사 환산(백분위 중앙값 기준). 참고용.
_5TO9 = {1: 1.8, 2: 3.0, 3: 5.0, 4: 7.0, 5: 8.3}

# 성취도(A/B/C) → 석차등급 근사 환산 (대학별 상이, 기본 참고값)
ACHIEVEMENT_TO_GRADE = {"A": 1.5, "B": 3.5, "C": 5.5}

def convert_achievement(level):
    """성취도(A/B/C)를 석차등급으로 근사 환산."""
    if isinstance(level, str):
        return ACHIEVEMENT_TO_GRADE.get(level.upper(), 5.0)
    return level


#  ── 등급 추정 사다리 ────────────────────────────────────────────
#
#  진로선택 과목에는 석차등급이 없다. 성취도(A/B/C)만 나온다.
#  전에는 A를 무조건 1.5로 바꿨다 — A를 70% 주는 과목과 12% 주는
#  과목의 A가 같은 값이었다. 성적표에 있는 것을 다 받으면 더 잘 잰다.
#
#      1. 석차등급이 있으면 그대로
#      2. 성취도 + 성취도별 비율 → 그 구간의 가운데 백분위 → 등급
#      3. 원점수 + 과목평균 + 표준편차 → Z점수 → 백분위 → 등급
#      4. 아무것도 없으면 고정표(전과 같음)
#
#  어느 단계를 썼는지 함께 돌려준다. 학생에게 보여주기 위해서다.

#  9등급 누적 구간의 **가운데** 백분위(상위 %). 등급은 이 점들 사이를
#  직선으로 잇는다 — 평균을 낼 수 있게 소수를 돌려주기 위해서다.
_GRADE_CENTER = [2.0, 7.5, 17.0, 31.5, 50.0, 68.5, 83.0, 92.5, 98.0]

#  5등급제(2025 고1~) 누적 구간의 가운데
_GRADE_CENTER5 = [5.0, 22.0, 50.0, 78.0, 95.0]

GRADE_SOURCE_LABEL = {
    "seokcha": "석차등급",
    "dist": "성취도 비율 환산",
    "zscore": "원점수 Z환산",
    "fixed": "성취도 참고값",
}
GRADE_SOURCE_DETAIL = {
    "seokcha": "성적표의 석차등급을 그대로 썼습니다.",
    "dist": "성취도별 학생 비율로 이 성취도 구간의 가운데 백분위를 잡아 "
            "등급으로 바꿨습니다. 같은 A라도 A를 적게 주는 과목이 좋게 "
            "나옵니다.",
    "zscore": "원점수·과목평균·표준편차로 Z점수를 내고 백분위로 바꿔 "
              "등급을 추정했습니다. 성적이 정규분포라고 가정한 값입니다.",
    "fixed": "성취도만 있어 고정 참고값(A 1.5 · B 3.5 · C 5.5)을 "
             "썼습니다. 과목평균·표준편차나 성취도 비율을 넣으면 더 "
             "정확해집니다.",
}


def grade_from_pct(pct, scale=9):
    """상위 백분위(0~100, 작을수록 우수) → 등급(소수)."""
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return None
    cen = _GRADE_CENTER5 if scale == 5 else _GRADE_CENTER
    if p <= cen[0]:
        return 1.0
    if p >= cen[-1]:
        return float(len(cen))
    for i in range(len(cen) - 1):
        if p <= cen[i + 1]:
            span = cen[i + 1] - cen[i]
            return round(i + 1 + (p - cen[i]) / span, 3)
    return float(len(cen))


def pct_from_dist(ach, dist):
    """성취도와 성취도별 비율(%) → 그 구간의 가운데 상위 백분위.

    dist 는 {"A": 34.5, "B": 40.0, "C": 25.5} 처럼 준다. 순서대로 위에서
    쌓아 그 성취도 구간의 가운데를 잡는다.
    """
    a = (ach or "").strip().upper()
    if not a:
        return None
    order = [x for x in ("A", "B", "C", "D", "E") if x in (dist or {})]
    #  한 칸만 적혀 있으면 비율이 아니다. A 비율만 주고 A를 물으면
    #  '위에 아무도 없고 A가 전부' 가 되어 늘 상위 50% 로 나온다.
    #  그건 값이 아니라 우연이다 — 없는 것으로 본다.
    if len(order) < 2 or a not in order:
        return None
    vals = []
    for k in order:
        try:
            v = float(str(dist[k]).replace("%", "").strip())
        except (TypeError, ValueError):
            return None
        if v < 0:
            return None
        vals.append(v)
    tot = sum(vals)
    if tot <= 0:
        return None
    #  합이 100 이 아니어도(반올림·일부 누락) 비율로 정규화해 쓴다
    above = 0.0
    for k, v in zip(order, vals):
        if k == a:
            return round(100.0 * (above + v / 2.0) / tot, 3)
        above += v
    return None


def _norm_cdf(z):
    return 0.5 * (1.0 + _erf(z / _SQRT2))


def pct_from_z(raw, mean, sd):
    """원점수·과목평균·표준편차 → 상위 백분위(작을수록 우수)."""
    try:
        r, m, s = float(raw), float(mean), float(sd)
    except (TypeError, ValueError):
        return None
    if s <= 0:
        return None
    z = (r - m) / s
    if z > 4 or z < -4:
        z = max(-4.0, min(4.0, z))
    return round(100.0 * (1.0 - _norm_cdf(z)), 3)


def subject_grade(rec, scale=9):
    """과목 한 학기 성적 → (등급, 근거).

    rec 은 {"grade","ach","raw","mean","sd","dist"} 중 있는 것만 준다.
    """
    g = rec.get("grade")
    if g not in (None, ""):
        try:
            return float(g), "seokcha"
        except (TypeError, ValueError):
            pass
    p = pct_from_dist(rec.get("ach"), rec.get("dist") or {})
    if p is not None:
        return grade_from_pct(p, scale), "dist"
    p = pct_from_z(rec.get("raw"), rec.get("mean"), rec.get("sd"))
    if p is not None:
        return grade_from_pct(p, scale), "zscore"
    a = (rec.get("ach") or "").strip().upper()
    if a in ACHIEVEMENT_TO_GRADE:
        return ACHIEVEMENT_TO_GRADE[a], "fixed"
    return None, None


def convert_5to9(g):
    """5등급 성적(1~5, 소수 가능)을 9등급 척도로 근사 환산."""
    try:
        g = float(g)
    except (TypeError, ValueError):
        return g
    if g <= 1:
        return _5TO9[1]
    if g >= 5:
        return _5TO9[5]
    lo = int(g); hi = lo + 1
    return round(_5TO9[lo] + (_5TO9[hi] - _5TO9[lo]) * (g - lo), 3)


def _naesin_avg(student):
    num = den = 0.0
    for k, v in (student.get("naesin") or {}).items():
        if k == "한국사":
            continue
        g = None
        u = 1.0
        if isinstance(v, dict):
            g = v.get("grade")
            u = float(v.get("units") or 1.0)
        elif isinstance(v, (int, float)):
            g = v
        if isinstance(g, (int, float)):
            num += g * u
            den += u
    return round(num / den, 3) if den > 0 else None


# 밴드 정의: (라벨, 색)
BANDS = ["안정", "적정", "소신", "위험", "매우위험"]


def admission_band(su, gy, student, unit):
    """
    합격 가능성 밴드(휴리스틱). 입결 데이터가 unit에 있으면 그것으로 대체.
    반환: (band, score, basis) — band는 위 BANDS 또는 특수라벨.
    ⚠️ 입결 미포함 시: '최저 여유 + 내신 수준' 기반 참고치일 뿐 실제 합격확률 아님.
    """
    st = su.get("status")
    if st == "fail":
        return ("지원불가", 0, "수능최저 미충족")
    if st == "unknown":
        return ("판정보류", None, "성적/조건 정보 부족")

    # 입결 기반 정밀 판정(있을 때만, 기능 활성화 시)
    cut = (unit.get("ipgyeol_naesin") if unit else None) if features.IPGYEOL_ENABLED else None
    navg = _naesin_avg(student)
    if cut is not None and navg is not None:
        diff = cut - navg  # +면 학생이 컷보다 우수
        if diff >= 0.5:
            return ("안정", 90, f"내신 {navg:.2f} vs 컷 {cut} (여유 {diff:+.2f})")
        if diff >= 0.0:
            return ("적정", 72, f"내신 {navg:.2f} vs 컷 {cut} (여유 {diff:+.2f})")
        if diff >= -0.3:
            return ("소신", 55, f"내신 {navg:.2f} vs 컷 {cut} ({diff:+.2f})")
        if diff >= -0.7:
            return ("위험", 35, f"내신 {navg:.2f} vs 컷 {cut} ({diff:+.2f})")
        return ("매우위험", 15, f"내신 {navg:.2f} vs 컷 {cut} ({diff:+.2f})")

    # 휴리스틱: 수능최저 여유 + 내신 수준
    su_score = 60  # 최저 없음/통과 기본
    m = su.get("margin")
    if st == "pass" and isinstance(m, (int, float)):
        su_score = 60 + max(0, min(m, 6)) * 6  # 여유 등급만큼 가산(최대 96)
    elif st == "na":
        su_score = 58  # 최저 필터 없음(변별력 낮음) — 중립

    parts = [(su_score, 0.4)]
    basis = [f"최저 {su.get('detail','')[:24]}"]
    if gy.get("applies") and gy.get("pct") is not None:
        parts.append((gy["pct"], 0.6))
        basis.append(f"교과 {gy['pct']}%")
    elif navg is not None:
        # 내신 평균등급 → 점수(1.0=100, 5.0=20 선형)
        ns = max(0, min(100, 100 - (navg - 1.0) * 20))
        parts.append((ns, 0.6))
        basis.append(f"내신평균 {navg:.2f}등급")

    score = sum(v * w for v, w in parts) / sum(w for _, w in parts)
    if score >= 82:
        band = "안정"
    elif score >= 66:
        band = "적정"
    elif score >= 50:
        band = "소신"
    elif score >= 36:
        band = "위험"
    else:
        band = "매우위험"
    return (band, round(score, 1), " · ".join(basis))


#  판정이 무엇에 근거했는지. 라벨은 모바일(app_constants.dart)과 같은 말을 쓴다.
BAND_SOURCE_LABEL = {
    "jeongsi": "작년 정시 70%컷 기준",
    "ipgyeol": "작년 합격컷 기준",
    "gyogwa": "대학 반영기준 계산",
    "heuristic": "참고용 추정",
    "blocked": "판정 불가",
}
BAND_SOURCE_DETAIL = {
    "jeongsi": "어디가에 공개된 작년 정시 70%컷 평균백분위와 비교했습니다.",
    "ipgyeol": "어디가에 공개된 작년 합격자 70%컷 내신과 비교했습니다. "
               "실제 합격 결과라 신뢰도가 높습니다.",
    "gyogwa": "이 대학이 공시한 반영교과·반영비율·등급환산표로 계산했습니다.",
    "heuristic": "이 학과는 작년 합격컷도, 대학의 반영교과 기준도 아직 "
                 "확보되지 않았습니다. 수능최저 여유와 전 과목 단순평균으로 "
                 "대략 추정한 값이라 실제와 다를 수 있습니다.",
    "blocked": "수능최저 미충족 또는 성적 정보 부족으로 판정할 수 없습니다.",
}


def band_source(su, gy, student, unit, is_jeongsi):
    """이 판정이 무엇에 근거했는가.

    모바일은 처음부터 이걸 화면에 배지로 보여줬는데 **PC 에는 아예 없었다.**
    발행본을 세어 보니 수시 판정의 36% 가 `heuristic`(추정)이다. 학생이
    그걸 모르고 보면 추정값을 합격컷 대조와 같은 무게로 믿는다.

    `admission_band` 와 **같은 조건**으로 판단해야 표시가 실제 판정과
    어긋나지 않는다.
    """
    if is_jeongsi:
        return "jeongsi"
    st = (su or {}).get("status")
    if st in ("fail", "unknown"):
        return "blocked"
    cut = (unit.get("ipgyeol_naesin") if unit else None) \
        if features.IPGYEOL_ENABLED else None
    if cut is not None and _naesin_avg(student) is not None:
        return "ipgyeol"
    if (gy or {}).get("applies") and (gy or {}).get("pct") is not None:
        return "gyogwa"
    return "heuristic"


def _student_pct_avg(student):
    """학생 수능 평균백분위(국어·수학·탐구 평균). 입력 없으면 None."""
    b = student.get("baekbunwi") or {}
    vals = [b.get(k) for k in ("국어", "수학", "탐구") if isinstance(b.get(k), (int, float))]
    if len(vals) < 2:
        return None
    return sum(vals) / len(vals)


def jeongsi_band(unit, student):
    """정시: 학생 평균백분위 vs 70%컷 평균백분위."""
    js = unit.get("js") or {}
    cut = js.get("pct_avg70")
    savg = _student_pct_avg(student)
    if cut is None:
        return ("판정보류", None, "전년도 백분위 미제출")
    if savg is None:
        return ("판정보류", None, f"70%컷 평균백분위 {cut} (수능 백분위 입력 시 판정)")
    diff = savg - cut  # +면 학생이 우수(백분위 높음)
    basis = f"평균백분위 {savg:.1f} vs 70%컷 {cut} ({diff:+.1f})"
    if diff >= 3:
        return ("안정", 90, basis)
    if diff >= 0:
        return ("적정", 72, basis)
    if diff >= -3:
        return ("소신", 55, basis)
    if diff >= -6:
        return ("위험", 35, basis)
    return ("매우위험", 15, basis)


def eval_unit(univ, track, unit, student):
    rule = model.resolve_suneung(univ, track, unit)
    su = suneung.evaluate(rule, student.get("suneung", {}))
    gy = gyogwa.evaluate(track, student.get("naesin", {}), univ=univ, unit=unit)
    # 계열 적합성
    gy_ok = True
    if student.get("gyeyeol") and unit.get("gyeyeol") and unit["gyeyeol"] != "공통":
        gy_ok = (unit["gyeyeol"] == student["gyeyeol"])
    is_jeongsi = (track.get("category") == "정시") or (unit.get("admission_type") == "정시")
    if is_jeongsi:
        band, bscore, bbasis = jeongsi_band(unit, student)
    else:
        band, bscore, bbasis = admission_band(su, gy, student, unit)
    return {
        "univ": univ["name"], "univ_code": univ["code"],
        "year": univ.get("year"),
        "admission_type": (track.get("admission_type") or unit.get("admission_type")
                           or univ.get("admission_type", "수시")),
        "track": track["name"], "category": track["category"],
        "unit": unit["unit"], "gyeyeol": unit.get("gyeyeol"),
        "count": unit.get("count"),
        "gyeyeol_match": gy_ok,
        "suneung": su,
        "gyogwa": gy,
        "method": track.get("method"),
        # 학생이 지원 판단에 필요한 '기준' 원본.
        # gyogwa 는 계산 결과라서 어떤 교과를 어떤 환산표로 봤는지가 안 담긴다.
        "gyogwa_spec": track.get("gyogwa"),
        # 평가 세부사항 — 서류·면접을 무엇으로 나눠 보는가(역량·비율·평가내용).
        # 종합전형은 이게 없으면 '서류 100%' 라는 말밖에 남지 않는다.
        "evaluation": track.get("evaluation"),
        # 같은 점수면 무엇으로 가르는가 — 경계에 선 학생에게 필요하다
        "tiebreak": track.get("tiebreak"),
        # 학교폭력 조치사항 반영 · 면접 방식/시간/문항
        "violence": track.get("violence"),
        "interview": track.get("interview"),
        # 이 학과가 직접 쓴 '이런 학생을 뽑는다' 와 중히 보는 교과
        "injaesang": unit.get("injaesang"),
        "gyogwa_focus": unit.get("gyogwa_focus"),
        "profile_source": unit.get("profile_source"),
        "grade_weights": univ.get("grade_weights"),
        "suneung_groups": univ.get("suneung_groups"),
        "auto": bool(univ.get("auto") or track.get("auto")),
        "confidence": (rule or {}).get("confidence") if rule else None,
        "band": band, "band_score": bscore, "band_basis": bbasis,
        # 이 판정이 무엇에 근거했는가 — 추정인지 작년 컷 대조인지
        "band_source": band_source(su, gy, student, unit, is_jeongsi),
        # 상세/원문 정보
        "college": unit.get("college"),
        "match": unit.get("match"),
        "unit_page": unit.get("unit_page"),
        "rule_page": unit.get("rule_page"),
        "rule_src": unit.get("rule_src"),
        "rule_sentence": unit.get("rule_sentence"),
        #  한 전형 유형 안에서 최저가 갈릴 때의 안내
        "su_note": track.get("su_note"),
        #  일반 학생과 무관한 전형(기회균형·특수교육·재직자 등).
        #  자료에는 두고 화면에서 기본으로 접는다 — 버리면 그 전형으로만
        #  뽑는 학과가 목록에서 사라진다.
        "narrow": bool(track.get("narrow")),
        "rule_label": (rule or {}).get("label") if rule else None,
        "source_file": unit.get("source_file") or univ.get("source_file"),
        # 입결(합격컷)
        #  이 컷이 어느 전형의 것인가 — 요강이 없는 대학은 전형을
        #  어디가 이름대로 나눠 담으므로 하나씩이다
        "ipgyeol_label": unit.get("ipgyeol_label"),
        #  전형별 컷이 갈리는데 어느 전형인지 못 가린 경우 — 전형별
        #  목록을 함께 준다. 한 숫자만 보여주면 학생은 그게 자기
        #  전형의 컷이라고 읽는다.
        "ipgyeol_choices": unit.get("ipgyeol_choices"),
        "ipgyeol_naesin": unit.get("ipgyeol_naesin"),
        "ipgyeol_low": unit.get("ipgyeol_low"),
        "ipgyeol_type": unit.get("ipgyeol_type"),
        "ipgyeol_page": unit.get("ipgyeol_page"),
        # 어디가 결과공개(전형별 전년도 결과)
        "eodiga": unit.get("eodiga"),
        "eodiga_year": unit.get("eodiga_year"),
        "eodiga_score70": unit.get("eodiga_score70"),
        "eodiga_comp": unit.get("eodiga_comp"),
        # 정시(백분위) 결과
        "js": unit.get("js"),
        "js_records": unit.get("js_records"),
        # 원문 이미지·강조박스(라이트용, publish가 부착)
        "sources": unit.get("sources"),
    }


def run(student, univs=None, codes=None):
    if univs is None:
        univs = assemble.load_all()
    cats = set(student.get("categories") or [])
    results = []
    for code, univ in univs.items():
        #  `codes` 는 **빈 목록도 뜻이 있다** — '해당하는 대학이 없다'.
        #  예전에는 `if codes and ...` 였다. 빈 목록이 거짓이라 걸러내기를
        #  건너뛰고 전체를 돌려줬고, 화면에서는 대학을 골라도 아무 것도
        #  안 걸러지는 것처럼 보였다. 모바일 엔진은 처음부터 `!= null` 로
        #  판정했는데 PC 만 달랐다.
        if codes is not None and code not in codes:
            continue
        for track in univ.get("tracks", []):
            if cats and track["category"] not in cats:
                continue
            for unit in track.get("units", []):
                results.append(eval_unit(univ, track, unit, student))
    return results


def summarize(r):
    """한 결과의 종합 판정 라벨."""
    if not r["gyeyeol_match"]:
        return "계열불일치"
    if r.get("category") == "정시":
        if r.get("band") == "판정보류":
            return "판정보류(백분위)"
        return "지원가능"
    st = r["suneung"]["status"]
    if st == "fail":
        return "수능최저 미충족"
    if st == "unknown":
        return "판정보류(성적부족)"
    # pass 또는 na
    return "지원가능"
