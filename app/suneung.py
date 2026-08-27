"""
suneung.py — 수능최저학력기준 충족 여부 판정.

학생 수능 성적 입력 예:
  {"국어":3, "수학":2, "영어":2, "탐구1":3, "탐구2":4, "한국사":4,
   "수학선택":"미적분", "탐구과목":["생명과학","지구과학"]}
등급은 1(최상)~9. 미응시 영역은 생략 또는 None.
"""

def _tamgu_grade(student, mode):
    """탐구 영역 대표 등급을 mode(best1/avg2)에 따라 계산."""
    g = [student.get("탐구1"), student.get("탐구2")]
    g = [x for x in g if isinstance(x, (int, float))]
    if not g:
        return None
    if mode == "avg2" and len(g) == 2:
        return sum(g) / 2.0
    return min(g)  # best1 (상위 1과목)


def _area_grade(student, area, rule):
    """규칙에 맞는 영역 등급을 반환(수학 선택과목 제한 반영)."""
    if area == "탐구":
        return _tamgu_grade(student, rule.get("tamgu", "best1"))
    if area == "수학":
        restrict = rule.get("math_restrict")
        if restrict:
            sel = student.get("수학선택")
            if sel:
                allowed = restrict + (["미적분Ⅱ"] if "미적분" in restrict else [])
                if sel not in allowed:
                    # 제한 선택과목 미충족 → 수학 반영 불가
                    return None
        return student.get("수학")
    return student.get(area)


def evaluate(rule, student):
    """
    반환: dict(status, detail, margin)
      status: 'pass' | 'fail' | 'na'(미적용) | 'unknown'(성적 부족)
      margin: 여유 등급수(+면 충족 여유, -면 부족). sum류에서만 의미.
    """
    if not rule or rule.get("type") in (None, "none"):
        return {"status": "na", "detail": "수능최저 미적용", "margin": None,
                "label": "수능최저 없음"}

    t = rule["type"]

    # 복합조건: 모든 하위 조건을 충족해야 함
    if t == "and":
        subs = [evaluate(c, student) for c in rule.get("conditions", [])]
        # 하나라도 fail → fail, unknown 있으면 unknown, 아니면 pass
        details = " / ".join(s["detail"] for s in subs)
        if any(s["status"] == "fail" for s in subs):
            st = "fail"
        elif any(s["status"] == "unknown" for s in subs):
            st = "unknown"
        else:
            st = "pass"
        margins = [s["margin"] for s in subs if isinstance(s.get("margin"), (int, float))]
        return {"status": st, "margin": min(margins) if margins else None,
                "label": rule.get("label", ""), "detail": details}

    pool = rule.get("pool", ["국어", "수학", "영어", "탐구"])
    label = rule.get("label", "")

    # 각 영역 등급 수집
    grades = {}
    for a in pool:
        g = _area_grade(student, a, rule)
        if g is not None:
            grades[a] = g

    required = rule.get("required", [])
    for req in required:
        if req not in grades:
            return {"status": "unknown", "margin": None, "label": label,
                    "detail": f"필수 반영영역 '{req}' 성적/조건 미충족(예: 수학 선택과목 제한)"}

    if t == "sum_top_n":
        n = rule["n"]
        mx = rule["max"]
        # 필수영역 우선 포함
        chosen = []
        used = set()
        for req in required:
            chosen.append((req, grades[req])); used.add(req)
        rest = sorted([(a, grades[a]) for a in grades if a not in used],
                      key=lambda x: x[1])
        for a, g in rest:
            if len(chosen) >= n:
                break
            chosen.append((a, g)); used.add(a)
        if len(chosen) < n:
            return {"status": "unknown", "margin": None, "label": label,
                    "detail": f"반영영역 부족({len(chosen)}/{n}개 응시)"}
        s = sum(g for _, g in chosen)
        ok = s <= mx + 1e-9
        picked = ", ".join(f"{a}{_fmt(g)}" for a, g in chosen)
        return {"status": "pass" if ok else "fail",
                "margin": round(mx - s, 2),
                "label": label,
                "detail": f"상위{n}개[{picked}] 합 {_fmt(s)} {'≤' if ok else '>'} {mx}"}

    if t == "each_max":
        # n개 영역이 각각 max 이내
        n = rule["n"]; mx = rule["max"]
        good = sorted([g for g in grades.values()])
        if len(good) < n:
            return {"status": "unknown", "margin": None, "label": label,
                    "detail": f"반영영역 부족({len(good)}/{n})"}
        picked = good[:n]
        ok = all(g <= mx + 1e-9 for g in picked)
        return {"status": "pass" if ok else "fail", "margin": None, "label": label,
                "detail": f"{n}개 영역 각 {mx}등급 이내 → {'충족' if ok else '미충족'}"}

    if t == "count_le":
        # max등급 이내 영역이 n개 이상
        n = rule["n"]; mx = rule["max"]
        cnt = sum(1 for g in grades.values() if g <= mx + 1e-9)
        ok = cnt >= n
        return {"status": "pass" if ok else "fail", "margin": cnt - n, "label": label,
                "detail": f"{mx}등급 이내 {cnt}개 (필요 {n}개)"}

    return {"status": "unknown", "margin": None, "label": label,
            "detail": f"미지원 규칙 type={t}"}


def _fmt(x):
    if isinstance(x, float) and not x.is_integer():
        return f"{x:.1f}"
    return str(int(x))
