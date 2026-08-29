"""
gyogwa.py — 학생부 교과 환산점수 계산.

학생 내신 입력 예 (교과영역별 평균 등급):
  {"국어":2.3, "수학":2.0, "영어":1.8, "사회":2.1, "과학":2.5, "한국사":3.0}
필요 시 이수단위 가중치도 지원:
  {"국어":{"grade":2.3,"units":12}, ...}
"""

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
            if group in s or s.startswith(group):
                group_subjects.append(s)
                
        if pick == "best" and group_subjects:
            def _get_grade(s):
                g, _ = _get(student_gyogwa, s, univ=univ)
                return g if g is not None else 999
            
            group_subjects.sort(key=_get_grade)
            to_keep = set(group_subjects[:n])
            filtered_subjects = [s for s in filtered_subjects if s not in group_subjects or s in to_keep]
            
    return filtered_subjects


def reflected_avg(student_gyogwa, subjects, univ=None):
    """반영교과의 (이수단위 가중) 평균 등급."""
    num = den = 0.0
    used = []
    for s in subjects:
        g, u = _get(student_gyogwa, s, univ=univ)
        if g is None:
            continue
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


def evaluate(track, student_gyogwa, univ=None):
    """
    반환 dict(applies, avg_grade, score, max_score, pct, subjects, detail)
    """
    g = track.get("gyogwa")
    if not g or track.get("method", {}).get("교과", 0) == 0:
        return {"applies": False, "detail": "교과 미반영 전형"}
    subs = g["subjects"]
    if "selection_rules" in g:
        subs = apply_selection_rules(student_gyogwa, subs, g["selection_rules"], univ=univ)
    avg, used = reflected_avg(student_gyogwa, subs, univ=univ)
    if avg is None:
        return {"applies": True, "avg_grade": None, "score": None,
                "detail": f"반영교과({', '.join(subs)}) 성적 미입력"}
    scale = g.get("scale")
    score = scale_score(avg, scale) if scale else None
    mx = max((float(v) for v in scale.values()), default=None) if scale else None
    pct = round(score / mx * 100, 2) if (score is not None and mx) else None
    return {"applies": True, "avg_grade": round(avg, 3), "score": score,
            "max_score": mx, "pct": pct, "subjects": used,
            "detail": f"반영교과 평균 {avg:.2f}등급"
                       + (f" → {score:.2f}/{mx:g}점({pct}%)" if score is not None else "")}
