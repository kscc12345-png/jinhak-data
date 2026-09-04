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
    if mode == "avg2":
        if len(g) >= 2:
            return sum(g[:2]) / 2.0
        return None  # 2과목 평균 요구 시 1과목만 있으면 성적 부족(None)
    return min(g)  # best1 (상위 1과목)


def _max_for(rule, student):
    """수학 선택과목에 따라 기준 등급이 달라지는 경우를 반영한다.

    공주대 수학교육과: '수학 포함 상위 2개 영역 합 7 이내
    (단, 수학 과목 중 확률과 통계 과목 응시자는 합산 4등급 이내)'.
    이걸 반영하지 않으면 확통 응시자에게 **통과라고 잘못 알려준다**
    (국어3+수학3=6 ≤ 7 로 통과 처리되지만 요강 기준은 4 이내다).
    """
    mx = rule["max"]
    mbm = rule.get("max_by_math")
    if isinstance(mbm, dict):
        sel = (student.get("수학선택") or "").replace(" ", "")
        for k, v in mbm.items():
            if k.replace(" ", "") == sel:
                return v
    return mx


def _remap(area, g, rule):
    """대학이 특정 영역 등급을 통합해 보는 경우를 반영한다.

    중앙대: "영어 등급 반영 시 1등급과 2등급을 통합하여 1등급으로 간주하여
    수능최저학력기준 충족 여부를 산정". 이걸 반영하지 않으면 영어 2등급인
    학생에게 **실제보다 엄격한 판정**을 내려 지원 가능한 학과를 숨긴다.

    형식: rule["area_grade_map"] = {"영어": {"2": 1}}
    """
    m = (rule or {}).get("area_grade_map")
    if not isinstance(m, dict) or g is None:
        return g
    am = m.get(area)
    if not isinstance(am, dict):
        return g
    for k, v in am.items():
        try:
            if float(k) == float(g):
                return v
        except (TypeError, ValueError):
            continue
    return g


def _area_grade(student, area, rule):
    """규칙에 맞는 영역 등급을 반환(수학 선택과목 제한·등급 통합 반영)."""
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
        # 규칙의 라벨을 그대로 쓴다. '요강에 미적용이라고 적혀 있음' 과
        # '요강에서 못 찾음' 은 학생에게 전혀 다른 정보인데, 라벨을 버리면
        # 둘 다 '수능최저 없음' 으로 뭉개진다.
        lab = (rule or {}).get("label") or ""
        return {"status": "na", "detail": lab or "수능최저 미적용",
                "margin": None, "label": lab or "수능최저 없음"}

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

    # 선택조건: 하위 조건 중 **하나만** 충족해도 됨
    if t == "or":
        subs = [evaluate(c, student) for c in rule.get("conditions", [])]
        oks = [x for x in subs if x["status"] == "pass"]
        if oks:
            st = "pass"
        elif any(x["status"] == "unknown" for x in subs):
            st = "unknown"
        else:
            st = "fail"
        pick = oks or subs
        margins = [x["margin"] for x in pick
                   if isinstance(x.get("margin"), (int, float))]
        joiner = " 또는 " if not oks else " / "
        return {"status": st,
                "margin": max(margins) if margins else None,
                "label": rule.get("label", ""),
                "detail": joiner.join(x["detail"] for x in pick)}

    pool = rule.get("pool", ["국어", "수학", "영어", "탐구"])
    label = rule.get("label", "")

    # 각 영역 등급 수집
    grades = {}
    for a in pool:
        g = _remap(a, _area_grade(student, a, rule), rule)
        if g is not None:
            grades[a] = g

    required = rule.get("required", [])
    for req in required:
        if req not in grades:
            return {"status": "unknown", "margin": None, "label": label,
                    "detail": f"필수 반영영역 '{req}' 성적/조건 미충족(예: 수학 선택과목 제한)"}

    if t in ("sum_top_n", "sum"):
        n = rule.get("n", 2)
        mx = _max_for(rule, student)
        
        # 1) required_any (예: 국·수 중 1개 포함) 처리: 해당 목록 중 성적 가장 좋은 1개를 우선 확보
        req_any = rule.get("required_any") or []
        req_any_chosen = None
        if req_any:
            any_cands = [(a, grades[a]) for a in req_any if a in grades]
            if not any_cands:
                return {"status": "unknown", "margin": None, "label": label,
                        "detail": f"필수 선택영역({', '.join(req_any)} 중 1개) 성적 미충족"}
            any_cands.sort(key=lambda x: x[1])
            req_any_chosen = any_cands[0]

        # 2) 필수영역 우선 포함
        chosen = []
        used = set()
        for req in required:
            chosen.append((req, grades[req])); used.add(req)
            
        if req_any_chosen and req_any_chosen[0] not in used:
            chosen.append(req_any_chosen)
            used.add(req_any_chosen[0])

        # P2-4: required가 n보다 많으면 성적 우수순 n개로 방어
        if len(chosen) > n:
            chosen.sort(key=lambda x: x[1])
            chosen = chosen[:n]

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
        n = rule.get("n", len(grades))
        mx = _max_for(rule, student)
        if required:
            target_grades = [(req, grades[req]) for req in required if req in grades]
            if len(target_grades) < len(required):
                return {"status": "unknown", "margin": None, "label": label,
                        "detail": "필수 반영영역 성적 부족"}
        else:
            good = sorted([(a, g) for a, g in grades.items()], key=lambda x: x[1])
            if len(good) < n:
                return {"status": "unknown", "margin": None, "label": label,
                        "detail": f"반영영역 부족({len(good)}/{n})"}
            target_grades = good[:n]

        worst_g = max(g for _, g in target_grades)
        ok = all(g <= mx + 1e-9 for _, g in target_grades)
        picked = ", ".join(f"{a}{_fmt(g)}" for a, g in target_grades)
        return {"status": "pass" if ok else "fail",
                "margin": round(mx - worst_g, 2),
                "label": label,
                "detail": f"각 {mx}등급 이내[{picked}] → {'충족' if ok else '미충족'}"}

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
