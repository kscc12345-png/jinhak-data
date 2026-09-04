"""
gyogwa.py — 학생부 교과 환산점수 계산.

학생 내신 입력 예 (교과영역별 평균 등급):
  {"국어":2.3, "수학":2.0, "영어":1.8, "사회":2.1, "과학":2.5, "한국사":3.0}
필요 시 이수단위 가중치도 지원:
  {"국어":{"grade":2.3,"units":12}, ...}
"""

import re

#  과목명 → 교과군. 대학 반영교과는 교과군으로 적히는데 학생 성적은
#  과목명으로 들어오므로, 둘을 잇는 사전이 필요하다.
#  (학생이 입력하면서 고른 계통 kind 가 있으면 그걸 먼저 믿는다)
_AREA_PAT = [
    #  좁은 쪽부터. '중국어' 는 '국어' 를, '경제수학' 은 '경제' 를 품는다.
    ("한국사", r"한국사"),
    ("제2외국어", r"중국어|일본어|독일어|프랑스어|스페인어|러시아어|아랍어|"
                r"베트남어|제2외국어"),
    ("한문", r"한문"),
    ("예체능", r"체육|운동|스포츠|음악|미술|연극|무용|합창|관현악|"
              r"디자인|사진|영상제작"),
    ("과학", r"물리|화학공학|화학|생명과학|지구과학|통합과학|과학탐구실험|"
             r"융합과학|과학사|생활과\s*과학|첨단과학|^과학"),
    ("수학", r"수학|미적분|기하|확률과\s*통계|대수|경제\s*수학|"
             r"인공지능\s*수학|실용\s*통계|수학과제\s*탐구|기본\s*수학"),
    ("사회", r"지리|역사|동아시아사|세계사|근현대사|윤리|정치|법과\s*사회|"
             r"경제|사회|문화|철학|심리|교육학|논리학|종교학|"
             r"진로와\s*직업|^사회"),
    ("영어", r"영어|영문학|영미\s*문학|영어권\s*문화"),
    ("국어", r"국어|문학|독서|화법|작문|언어와\s*매체|고전\s*읽기|"
             r"주제\s*탐구\s*독서|문학과\s*영상|직무\s*의사소통|매체\s*의사소통"),
    ("기술·가정", r"기술|가정|정보|소프트웨어|공학|지식\s*재산|"
                r"창의\s*경영|생활\s*과학|농업|해양|수산"),
]

_AREA_RE = [(a, re.compile(p)) for a, p in _AREA_PAT]

#  교과군 이름 자체(학생이 '사회'·'과학' 이라고 적은 경우)
_AREAS = {a for a, _ in _AREA_PAT} | {"국어", "수학", "영어", "한국사"}


def subject_area(name, kind=None):
    """과목명이 어느 교과군인지. kind(입력 시 고른 계통)를 먼저 믿는다."""
    nm = (name or "").strip()
    if nm in _AREAS:
        return nm
    if kind and kind in _AREAS:
        return kind
    for area, rx in _AREA_RE:
        if rx.search(nm):
            return area
    return None


def expand_subjects(student_gyogwa, subjects):
    """반영교과(교과군) 목록을 **학생이 가진 과목**들로 펼친다.

    대학이 "반영교과 내 학생 이수 전 과목" 이라고 쓰는 그대로다.
    '과학' 을 반영한다면 학생의 물리학Ⅰ·생명과학Ⅰ 이 다 들어간다.
    """
    out, seen = [], set()
    for want in subjects:
        #  ① 학생이 그 이름 그대로 가지고 있으면 그것(옛 자료 호환)
        if want in student_gyogwa and want not in seen:
            out.append(want)
            seen.add(want)
            continue
        #  ② 그 교과군에 속하는 과목을 모두
        for nm, v in student_gyogwa.items():
            if nm in seen:
                continue
            kind = v.get("kind") if isinstance(v, dict) else None
            if subject_area(nm, kind) == want:
                out.append(nm)
                seen.add(nm)
    return out


def _get(student_gyogwa, subj, univ=None):
    v = student_gyogwa.get(subj)
    if v is None:
        return None, 0
    if isinstance(v, dict):
        if "achievement" in v:
            ach = v["achievement"].upper() if isinstance(v["achievement"], str) else ""
            grade = {"A": 1.5, "B": 3.5, "C": 5.5}.get(ach, 5.0)
            return grade, v.get("units", 1)
            
        yearly = v.get("yearly_grades")
        if yearly and univ and univ.get("grade_weights"):
            w_dict = univ["grade_weights"].get("weights", {"1": 1, "2": 1, "3": 1})
            tw = 0.0
            w_sum = 0.0
            for y in ["1", "2", "3"]:
                if yearly.get(y) is not None:
                    wy = float(w_dict.get(y, 1))
                    w_sum += yearly[y] * wy
                    tw += wy
            if tw > 0:
                grade = w_sum / tw
                return grade, v.get("units", 1)
                
        return v.get("grade"), v.get("units", 1)
    return v, 1  # 단위 미제공 → 동일가중

def apply_selection_rules(student_gyogwa, subjects, rules, univ=None):
    filtered_subjects = list(subjects)
    for rule in rules:
        group = rule.get("group")
        pick = rule.get("pick")
        n = rule.get("n", 1)
        
        group_subjects = []
        for s in filtered_subjects:
            v = student_gyogwa.get(s)
            kind = v.get("kind") if isinstance(v, dict) else None
            #  '사회' 그룹이면 생활과윤리·한국지리처럼 **그 교과군 과목**을
            #  모은다. 이름에 '사회' 가 들어가는지로 보면 다 놓친다.
            if subject_area(s, kind) == group or group in s:
                group_subjects.append(s)
                
        if pick == "best" and group_subjects:
            def _get_grade(s):
                g, _ = _get(student_gyogwa, s, univ=univ)
                return g if g is not None else 999
            
            group_subjects.sort(key=_get_grade)
            to_keep = set(group_subjects[:n])
            filtered_subjects = [s for s in filtered_subjects if s not in group_subjects or s in to_keep]
            
    return filtered_subjects


def spec_for(g, unit=None):
    """이 모집단위에 적용할 반영교과 설정을 고른다.

    우선순위: 학과명(by_unit) > 단과대학(by_college) > 계열(by_gyeyeol) > 기본
    (동국대는 인문계열이면 사회, 자연계열이면 과학을 본다)
    """
    if not unit:
        return g
    for key, val in (("by_unit", unit.get("unit")),
                     ("by_college", unit.get("college")),
                     ("by_gyeyeol", unit.get("gyeyeol"))):
        table = g.get(key)
        if isinstance(table, dict) and val and val in table:
            sub = table[val]
            merged = dict(g)
            merged.update(sub if isinstance(sub, dict) else {"subjects": sub})
            return merged
    return g


def reflected_avg(student_gyogwa, subjects, univ=None, weights=None):
    """반영교과의 (이수단위 가중) 평균 등급.

    weights 가 있으면 교과군별 가중치를 함께 건다 —
    건국대 연기우수자의 '국어(50%), 영어(50%)' 같은 경우다.
    """
    num = den = 0.0
    used = []
    for s in subjects:
        g, u = _get(student_gyogwa, s, univ=univ)
        if g is None:
            continue
        if weights:
            v = student_gyogwa.get(s)
            kind = v.get("kind") if isinstance(v, dict) else None
            area = subject_area(s, kind)
            w = weights.get(area, weights.get(s))
            if w is None:
                continue          # 가중치를 안 준 교과는 반영하지 않는다
            u = u * float(w)
        num += g * u
        den += u
        used.append(s)
    if den == 0:
        return None, used
    return num / den, used


def scale_score(avg_grade, scale):
    """등급환산표(scale: {"1":100,"2":99,...})로 점수 환산(선형보간)."""
    if avg_grade is None or not scale:
        return None
    pts = sorted((float(k), float(v)) for k, v in scale.items())
    lo = pts[0][0]; hi = pts[-1][0]
    if avg_grade <= lo:
        return pts[0][1]
    if avg_grade >= hi:
        return pts[-1][1]
    for (g1, s1), (g2, s2) in zip(pts, pts[1:]):
        if g1 <= avg_grade <= g2:
            r = (avg_grade - g1) / (g2 - g1)
            return s1 + r * (s2 - s1)
    return None


def evaluate(track, student_gyogwa, univ=None, unit=None):
    """
    반환 dict(applies, avg_grade, score, max_score, pct, subjects, detail)
    """
    g = track.get("gyogwa")
    if not g or track.get("method", {}).get("교과", 0) == 0:
        return {"applies": False, "detail": "교과 미반영 전형"}
    #  계열·모집단위마다 반영교과가 다른 대학이 있다(동국대 인문=사회 /
    #  자연=과학). 이 모집단위에 맞는 설정을 먼저 고른다.
    g = spec_for(g, unit)
    #  반영교과(교과군) → 학생이 가진 과목으로 펼친다.
    #  이걸 안 하면 학생의 선택과목(물리학Ⅰ·생활과윤리 …)이 통째로 빠진다.
    subs = expand_subjects(student_gyogwa, g["subjects"])
    if "selection_rules" in g:
        subs = apply_selection_rules(student_gyogwa, subs, g["selection_rules"], univ=univ)
    avg, used = reflected_avg(student_gyogwa, subs, univ=univ,
                              weights=g.get("weights"))
    if avg is None:
        return {"applies": True, "avg_grade": None, "score": None,
                "detail": f"반영교과({', '.join(g['subjects'])}) 성적 미입력"}
    scale = g.get("scale")
    score = scale_score(avg, scale) if scale else None
    mx = max((float(v) for v in scale.values()), default=None) if scale else None
    pct = round(score / mx * 100, 2) if (score is not None and mx) else None
    return {"applies": True, "avg_grade": round(avg, 3), "score": score,
            "max_score": mx, "pct": pct, "subjects": used,
            "detail": f"반영교과 평균 {avg:.2f}등급"
                       + (f" → {score:.2f}/{mx:g}점({pct}%)" if score is not None else "")}
