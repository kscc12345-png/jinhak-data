"""
assemble.py — 데이터 소스 통합.

우선순위:
  1) 정제 데이터 data/universities/{code}.json (사람이 검수/보완) → 그대로 사용
  2) 자동 추출 data/auto/{code}.json → 엔진 형식으로 변환(best-effort)

이로써 정제본이 없는 대학도 '수능최저 판정 + 학과 목록'은 자동 제공된다.
교과 환산표는 자동 추출이 어려워, 자동 변환분은 gyogwa=null(최저만 판정).
"""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIV_DIR = os.path.join(BASE, "data", "universities")
AUTO_DIR = os.path.join(BASE, "data", "auto")
MANUAL_IP = os.path.join(BASE, "data", "ipgyeol_manual.json")   # 관리자 수동 입결
EODIGA_DIR = os.path.join(BASE, "data", "eodiga")               # 어디가 결과공개


# 모집요강 전형 category ↔ 어디가 track 매핑
_CAT2TRACK = {"교과": "학생부교과", "종합": "학생부종합"}


def _norm_unit(nm):
    """학과명 정규화(공백·군표기 제거)로 매칭 정확도 향상."""
    import re as _re
    s = _re.sub(r"\s+", "", nm or "")
    s = _re.sub(r"^\(?[가나다]\)?", "", s)   # 정시 군 표기 제거
    return s


def load_eodiga(code):
    """어디가 결과공개 데이터 로드(학과 정규화 색인)."""
    p = os.path.join(EODIGA_DIR, f"{code}.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    idx = {}
    for nm, recs in d.get("results", {}).items():
        idx.setdefault(_norm_unit(nm), []).extend(recs)
    d["_idx"] = idx
    return d


_CAT_OF_TRACK = {"학생부교과": "교과", "학생부종합": "종합"}


def _eodiga_unit(nm, recs, yr):
    """어디가 결과만으로 학과 unit 구성(대표 70%컷 포함)."""
    pool = [r for r in recs if r.get("grade70") is not None]
    gen = [r for r in pool if "일반" in (r.get("label") or "")]
    best = (gen or pool or recs)[0]
    return {
        "unit": nm, "college": None, "gyeyeol": _guess_gyeyeol(nm, ""),
        "count": None, "match": "어디가",
        "suneung_rule": {"type": "none", "label": "수능최저 정보 없음(어디가 결과 기준)"},
        "source_file": None, "eodiga": recs, "eodiga_year": yr,
        "ipgyeol_naesin": best.get("grade70"), "ipgyeol_low": None,
        "ipgyeol_type": f"어디가 70%컷·환산등급({yr or ''})" if best.get("grade70") else None,
        "eodiga_score70": best.get("score70"), "eodiga_comp": best.get("competition"),
    }


def _merge_eodiga_units(univ, ed, yr):
    """어디가에만 있고 모집요강엔 없는 학과를 해당 전형(교과/종합)에 추가.
    (모집요강 학과 추출이 부실한 대학에서 어디가 학과가 누락되지 않게)"""
    have, track_by_cat = {}, {}
    for t in univ.get("tracks", []):
        c = t.get("category")
        track_by_cat.setdefault(c, t)
        for u in t.get("units", []):
            have.setdefault(c, set()).add(_norm_unit(u.get("unit", "")))
    by = {}
    for nm, recs in ed.get("results", {}).items():
        for r in recs:
            cat = _CAT_OF_TRACK.get(r.get("track"))
            if cat:
                by.setdefault(cat, {}).setdefault(nm, []).append(r)
    for cat, unit_recs in by.items():
        tr = track_by_cat.get(cat)
        for nm, recs in unit_recs.items():
            if _norm_unit(nm) in have.get(cat, set()):
                continue
            if tr is None:
                tr = {"id": f"eodiga_{cat}", "name": f"{cat}전형", "category": cat,
                      "admission_type": "수시", "method": {}, "gyogwa": None,
                      "auto": True, "units": []}
                univ.setdefault("tracks", []).append(tr)
                track_by_cat[cat] = tr
            tr["units"].append(_eodiga_unit(nm, recs, yr))
            have.setdefault(cat, set()).add(_norm_unit(nm))


def _apply_eodiga(univ, ed):
    """대학 dict의 각 학과에 어디가 결과(전형별) 부착 + 대표 70%컷 설정."""
    idx = ed.get("_idx", {})
    yr = ed.get("year")
    for t in univ.get("tracks", []):
        want = _CAT2TRACK.get(t.get("category"))
        for u in t.get("units", []):
            recs = idx.get(_norm_unit(u.get("unit", "")))
            if not recs:
                continue
            # 전형(track) 일치분만
            same = [r for r in recs if not want or r.get("track") == want]
            u["eodiga"] = same or recs
            u["eodiga_year"] = yr
            # 대표 70%컷: 같은 전형의 '일반전형' 우선, 없으면 최소 등급70
            pool = [r for r in (same or recs) if r.get("grade70") is not None]
            if not pool:
                continue
            gen = [r for r in pool if "일반" in (r.get("label") or "")]
            best = (gen or pool)[0]
            u["ipgyeol_naesin"] = best.get("grade70")
            u["ipgyeol_low"] = None
            u["ipgyeol_type"] = f"어디가 70%컷·환산등급({yr or ''})"
            u["eodiga_score70"] = best.get("score70")
            u["eodiga_comp"] = best.get("competition")
    # 어디가에만 있는 학과 추가(모집요강 부실 대학 대응)
    _merge_eodiga_units(univ, ed, yr)
    # 정시 track 생성(어디가 정시 백분위 결과 기반)
    jt = _jeongsi_track(ed.get("jeongsi") or {}, yr)
    if jt:
        univ.setdefault("tracks", []).append(jt)


def _jeongsi_track(js, yr):
    """어디가 정시 백분위 결과 → 정시 track dict(없으면 None)."""
    units = []
    for nm, recs in js.items():
        withdata = [r for r in recs if r.get("pct_avg70") is not None]
        best = (withdata or recs)[0]
        units.append({
            "unit": nm, "college": None,
            "gyeyeol": _guess_gyeyeol(nm, ""),
            "count": int(best["recruit"]) if best.get("recruit") else None,
            "suneung_rule": {"type": "none", "label": "정시 수능위주(최저 없음)"},
            "match": "정시결과", "admission_type": "정시",
            "source_file": None,
            "js_records": recs, "js": best, "eodiga_year": yr,
        })
    if not units:
        return None
    return {"id": "eodiga_jeongsi", "name": "정시(수능)",
            "category": "정시", "admission_type": "정시",
            "method": {}, "gyogwa": None, "auto": True, "units": units}


def _univ_from_eodiga(ed):
    """모집요강 없이 어디가 자료만 있는 대학 → 교과/종합/정시 track 대학 dict.
    (예: 서울대 — 교과 미제공, 학종·수능만)"""
    yr = ed.get("year")
    # 수시: 어디가 track(학생부교과/학생부종합)별 학과 units
    by_track = {}
    for nm, recs in ed.get("results", {}).items():
        for r in recs:
            by_track.setdefault(r.get("track"), {}).setdefault(nm, []).append(r)
    tmap = {"학생부교과": "교과", "학생부종합": "종합"}
    tracks = []
    for tk, unit_recs in by_track.items():
        cat = tmap.get(tk, "종합")
        units = []
        for nm, recs in unit_recs.items():
            pool = [r for r in recs if r.get("grade70") is not None]
            gen = [r for r in pool if "일반" in (r.get("label") or "")]
            best = (gen or pool or recs)[0]
            units.append({
                "unit": nm, "college": None, "gyeyeol": _guess_gyeyeol(nm, ""),
                "count": None, "match": "어디가",
                "suneung_rule": {"type": "none",
                                 "label": "수능최저 정보 없음(어디가 결과 기준)"},
                "source_file": None,
                "eodiga": recs, "eodiga_year": yr,
                "ipgyeol_naesin": best.get("grade70"),
                "ipgyeol_low": None,
                "ipgyeol_type": f"어디가 70%컷·환산등급({yr or ''})" if best.get("grade70") else None,
                "eodiga_score70": best.get("score70"),
                "eodiga_comp": best.get("competition"),
            })
        if units:
            tracks.append({"id": f"eodiga_{cat}", "name": f"{cat}전형",
                           "category": cat, "admission_type": "수시",
                           "method": {}, "gyogwa": None, "auto": True, "units": units})
    jt = _jeongsi_track(ed.get("jeongsi") or {}, yr)
    if jt:
        tracks.append(jt)
    if not tracks:
        return None
    # 어디가 결과는 전년도(yr)라, 입학연도(=yr+1)를 대학 학년도로 사용
    adm_year = (yr + 1) if isinstance(yr, int) else None
    return {"code": ed["code"], "name": ed.get("name") or ed["code"],
            "source": None, "source_file": None, "auto": True, "year": adm_year,
            "admission_type": "수시", "grade_weights": None,
            "categories_detected": [t["category"] for t in tracks],
            "tracks": tracks, "suneung_groups": {}, "eodiga_only": True}


def _load_manual():
    if os.path.exists(MANUAL_IP):
        try:
            return json.load(open(MANUAL_IP, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def set_manual_ipgyeol(code, unit, cut, low=None):
    """관리자: 특정 대학·학과의 합격 내신컷을 수동 저장."""
    m = _load_manual()
    m.setdefault(code, {})[unit] = {"cut": cut, "low": low}
    os.makedirs(os.path.dirname(MANUAL_IP), exist_ok=True)
    with open(MANUAL_IP, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


SELECTIVE = {"논술", "실기"}  # 계열/학과 선택적으로 뽑는 전형

# 실기 전형이 있는 예체능 계열 학과 키워드
_ARTS_KW = ("체육", "음악", "미술", "무용", "회화", "조소", "조형", "디자인", "관현악",
            "실용음악", "연극", "영화", "무대", "작곡", "성악", "기악", "피아노", "공예",
            "서양화", "동양화", "한국화", "패션", "예술", "만화", "애니", "연기", "뮤지컬",
            "국악", "스포츠", "태권도", "무예", "사진", "영상")


def _is_arts(unit):
    return any(k in (unit or "") for k in _ARTS_KW)


def _sentence_gye(s):
    s = s or ""
    has_h = "인문" in s
    has_n = "자연" in s
    if has_h and not has_n:
        return "인문"
    if has_n and not has_h:
        return "자연"
    return ""


def _rule_index(auto):
    """전형유형(category)별 최저 규칙 색인: 이름/계열/공통 매칭용."""
    from collections import Counter
    idx = {}
    def ensure(cat):
        return idx.setdefault(cat, {"by_name": {}, "by_gye": {}, "all": []})
    for row in auto.get("suneung_detected", []):
        cat = row.get("category") or _guess_cat(row.get("track", "")) or "기타"
        c = ensure(cat)
        name = (row.get("unit") or "").strip()
        gye = _guess_gyeyeol(name, row.get("college", ""))
        info = {"rule": row["rule"], "page": row.get("page"), "src": "표",
                "name": name, "search": name + " " + (row.get("college") or ""),
                "gye": gye, "track": row.get("track", "")}
        c["all"].append(info)
        generic = (not name) or ("전 모집" in name) or ("전모집" in name) or ("모집단위" == name)
        if not generic:
            c["by_name"].setdefault(name, info)
        if gye in ("인문", "자연"):
            c["by_gye"].setdefault(gye, info)
    for row in auto.get("suneung_text", []):
        cat = row.get("category") or _guess_cat(row.get("track", "")) or "기타"
        c = ensure(cat)
        gye = _sentence_gye(row.get("sentence", ""))
        sent = row.get("sentence", "")
        info = {"rule": row["rule"], "page": row.get("page"), "src": "본문",
                "name": "", "search": sent, "gye": gye, "sentence": sent,
                "track": row.get("track", "")}
        c["all"].append(info)
        if gye in ("인문", "자연"):
            c["by_gye"].setdefault(gye, info)
    # 전 전형 통합 색인(__ALL__): 최저가 특정 전형에만 잡혔을 때 교차 폴백용.
    # (많은 대학이 교과·종합에 동일 최저를 적용하나, 파서가 직전 전형헤더로만 분류함)
    allc = {"by_name": {}, "by_gye": {}, "all": []}
    for cat, c in idx.items():
        allc["all"].extend(c["all"])
        for k, v in c["by_name"].items():
            allc["by_name"].setdefault(k, v)
        for k, v in c["by_gye"].items():
            allc["by_gye"].setdefault(k, v)
    idx["__ALL__"] = allc
    for cat, c in idx.items():
        if c["all"]:
            lab = Counter(x["rule"].get("label", "")[:20] for x in c["all"]).most_common(1)[0][0]
            c["common"] = next((x for x in c["all"] if x["rule"].get("label", "")[:20] == lab), c["all"][0])
        else:
            c["common"] = None
    return idx


# 특수/의약계열: 학과 이름 키워드 → 최저 규칙 단과대학명에 들어갈 토큰
_SPECIAL = [
    ("의예", "의과"), ("의학", "의과"), ("치의", "치의"), ("치과", "치의"),
    ("한의", "한의"), ("약학", "약학"), ("제약", "약학"),
    ("수의", "수의"), ("간호", "간호"),
]


def _match_one(cat_idx, unit_name, gye, college, tag="", allow_gye=True):
    """단일 색인에서 매칭 시도. (info, kind) 또는 (None,None).
    allow_gye=False면 계열추정(광범위) 제외 — 타전형 폴백 시 오적용 방지."""
    if not cat_idx:
        return None, None
    if unit_name in cat_idx["by_name"]:
        return cat_idx["by_name"][unit_name], "이름일치" + tag
    allrules = cat_idx.get("all", [])

    def _txt(info):
        return (info.get("search") or info.get("name") or "")

    for trig, coll in _SPECIAL:
        if trig in unit_name:
            for info in allrules:
                if coll in _txt(info):
                    return info, "단과일치" + tag
    if college:
        for info in allrules:
            if college in _txt(info):
                return info, "단과일치" + tag
    if allow_gye and gye in cat_idx.get("by_gye", {}):
        return cat_idx["by_gye"][gye], "계열추정" + tag
    return None, None


def _match_rule(cat_idx, unit_name, gye, college="", all_idx=None):
    """학과에 최저 규칙 매칭. 반환: (info, match_kind)
    우선순위: 이름일치 > 의약/특수 단과일치 > 단과일치 > 계열추정 > (타전형 폴백) > 전형공통"""
    if not cat_idx and not all_idx:
        return None, "미확인"
    info, kind = _match_one(cat_idx, unit_name, gye, college)
    if info:
        return info, kind
    # 이 전형에 최저가 없거나 못 찾음 → 전 전형 통합 색인에서 폴백(교과↔종합 동일 최저 흔함)
    if all_idx:
        info, kind = _match_one(all_idx, unit_name, gye, college,
                                tag="(타전형)", allow_gye=False)
        if info:
            return info, kind
    if cat_idx and cat_idx.get("common"):
        return cat_idx["common"], "전형공통"
    return None, "미확인"


def convert_auto(auto):
    """auto 추출 JSON → 엔진 호환 대학 dict (학과 중심)."""
    src_file = auto.get("file")
    idx = _rule_index(auto)
    cats = auto.get("categories_detected", []) or []

    # 캐노니컬 학과 목록 (모집인원 표) — 이름 기준 dedup, 정원/페이지 유지
    all_units = {}
    for u in auto.get("units_detected", []):
        nm = u["unit"]
        if nm not in all_units:
            all_units[nm] = {
                "unit": nm, "college": u.get("college"),
                "gyeyeol": u.get("gyeyeol") or _guess_gyeyeol(nm, u.get("college", "")),
                "count": u.get("count"), "unit_page": u.get("page"),
                "cats": set(),   # 이 학과가 실제로 검출된 전형(교과/종합/실기/논술)
            }
        else:
            cur = all_units[nm]
            # 정원(count)이 있는 항목을 우선 — 출처 페이지도 그 항목(진짜 모집인원 표)으로
            if cur.get("count") is None and u.get("count") is not None:
                cur["count"] = u["count"]
                cur["unit_page"] = u.get("page")
                if u.get("college"):
                    cur["college"] = u["college"]
        if u.get("category"):
            all_units[nm]["cats"].add(u["category"])

    # 입결(합격컷) 색인 — 학과명 기준
    ipg = {ip["unit"]: ip for ip in auto.get("ipgyeol_detected", [])}

    tracks = []

    all_idx = idx.get("__ALL__")
    if all_units:  # 학과 중심 구성
        for cat in cats:
            cat_idx = idx.get(cat)
            # 교과·종합만 타전형 최저 폴백 허용(논술·실기는 고유 최저라 폴백 배제)
            fb = all_idx if cat not in SELECTIVE else None
            units = []
            for nm, base in all_units.items():
                gye = base["gyeyeol"]
                info, kind = _match_rule(cat_idx, nm, gye, base.get("college") or "", all_idx=fb)
                # 선택형(논술/실기)은 과다나열 방지.
                if cat in SELECTIVE:
                    detected = cat in base.get("cats", set())
                    named = bool(cat_idx and nm in cat_idx["by_name"])
                    # 실기: 예체능 학과는 실기 전형이 있으므로 표기(정보 제공)
                    arts = cat == "실기" and _is_arts(nm)
                    if not (detected or named or arts):
                        continue
                rule = info["rule"] if info else {"type": "none",
                        "label": "수능최저 정보 미검출(미적용일 수 있음)"}
                ipinfo = ipg.get(nm)
                units.append({
                    "unit": nm, "college": base["college"], "gyeyeol": gye,
                    "count": base["count"],
                    "suneung_rule": rule,
                    "match": kind,
                    "unit_page": base["unit_page"],
                    "rule_page": info["page"] if info else None,
                    "rule_src": info["src"] if info else None,
                    "rule_sentence": (info.get("sentence") if info else None),
                    "source_file": src_file,
                    "ipgyeol_naesin": ipinfo["cut"] if ipinfo else None,
                    "ipgyeol_low": ipinfo["low"] if ipinfo else None,
                    "ipgyeol_type": ipinfo["cut_type"] if ipinfo else None,
                    "ipgyeol_page": ipinfo.get("page") if ipinfo else None,
                })
            if units:
                tracks.append({
                    "id": f"auto_{cat}", "name": f"{cat}전형", "category": cat,
                    "method": {}, "gyogwa": None, "auto": True, "units": units,
                })
    else:  # 학과 미검출 → 기존 방식(최저 엔트리/플레이스홀더)
        for cat, c in idx.items():
            units = []
            seen = set()
            for info in c["all"]:
                nm = info["name"] or ("［본문기준］ " + info.get("sentence", "")[:36])
                sig = (nm, info["rule"].get("label", "")[:20])
                if sig in seen:
                    continue
                seen.add(sig)
                units.append({
                    "unit": nm, "college": None,
                    "gyeyeol": info["gye"] or "공통", "count": None,
                    "suneung_rule": info["rule"], "match": "이름일치" if info["name"] else "본문",
                    "rule_page": info.get("page"), "rule_src": info["src"],
                    "rule_sentence": info.get("sentence"), "source_file": src_file,
                })
            if units:
                tracks.append({"id": f"auto_{cat}", "name": f"{cat}전형",
                               "category": cat, "method": {}, "gyogwa": None,
                               "auto": True, "units": units})
        if not tracks:
            for cat in (cats or ["기타"]):
                tracks.append({
                    "id": f"auto_ph_{cat}", "name": f"{cat}전형", "category": cat,
                    "method": {}, "gyogwa": None, "auto": True,
                    "units": [{"unit": "［정보 미검출 — 원문 확인 필요］",
                               "gyeyeol": "공통", "count": None,
                               "suneung_rule": {"type": "none", "label": "미검출"},
                               "source_file": src_file}],
                })

    return {
        "code": auto["code"], "name": auto["name"],
        "source": src_file, "source_file": src_file, "auto": True,
        "year": auto.get("year"),
        "admission_type": auto.get("admission_type", "수시"),
        "grade_weights": auto.get("grade_weights"),
        "categories_detected": cats,
        "confidence_counts": auto.get("confidence_counts", {}),
        "tracks": tracks, "suneung_groups": {},
    }


def _guess_cat(track_name):
    for k, c in [("교과", "교과"), ("종합", "종합"), ("논술", "논술"), ("실기", "실기"), ("실적", "실기")]:
        if k in track_name:
            return c
    return ""


NAT_KW = ["공학", "이학", "자연", "수학", "물리", "화학", "생명", "컴퓨터", "전자", "기계",
          "의예", "약학", "간호", "수의", "생물", "정보", "건축", "토목", "식품", "농", "산림"]
HUM_KW = ["국어", "영어", "문학", "경영", "경제", "행정", "사회", "인문", "철학", "사학",
          "법학", "정치", "미디어", "교육", "심리", "문화", "무역", "관광", "복지"]


def _guess_gyeyeol(unit, college):
    s = unit + " " + (college or "")
    if any(k in s for k in NAT_KW):
        return "자연"
    if any(k in s for k in HUM_KW):
        return "인문"
    return "공통"


def load_all():
    """정제본 우선, 없으면 자동 변환본으로 통합한 대학 딕셔너리."""
    univs = {}
    # 자동 변환본 먼저
    for f in sorted(glob.glob(os.path.join(AUTO_DIR, "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        with open(f, encoding="utf-8") as fh:
            auto = json.load(fh)
        if not auto.get("code") or not auto.get("name"):
            continue                      # 코드/이름 없는 불량 데이터 건너뜀
        # 표최저·본문최저·감지전형 중 하나라도 있으면 포함(없으면 스캔 등 → 그래도 표시)
        univs[auto["code"]] = convert_auto(auto)
    # 정제본으로 덮어쓰기
    for f in sorted(glob.glob(os.path.join(UNIV_DIR, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        univs[d["code"]] = d
    # 학년도 부착
    for code, d in univs.items():
        if not d.get("year"):
            d["year"] = meta.year_for_code(code)
    # 어디가 결과공개(전년도 입시결과) 부착 + 대표 70%컷 설정
    for code, d in univs.items():
        ed = load_eodiga(code)
        if ed:
            _apply_eodiga(d, ed)
    # 모집요강 없이 어디가만 있는 대학(예: 서울대) → 어디가로 대학 생성
    for f in glob.glob(os.path.join(EODIGA_DIR, "*.json")):
        code = os.path.splitext(os.path.basename(f))[0]
        if code in univs:
            continue
        ed = load_eodiga(code)
        u = _univ_from_eodiga(ed) if ed else None
        if u:
            if not u.get("year"):
                u["year"] = meta.year_for_code(code)
            univs[code] = u
    # 관리자 수동 입결 적용(어디가·자동추출값보다 우선)
    manual = _load_manual()
    for code, mp in manual.items():
        d = univs.get(code)
        if not d:
            continue
        for t in d.get("tracks", []):
            for u in t.get("units", []):
                v = mp.get(u.get("unit"))
                if v and v.get("cut") is not None:
                    u["ipgyeol_naesin"] = v["cut"]
                    u["ipgyeol_low"] = v.get("low")
                    u["ipgyeol_type"] = "수동 입력"
    return univs


if __name__ == "__main__":
    u = load_all()
    for code, d in u.items():
        src = "정제" if not d.get("auto") else "자동"
        nt = len(d.get("tracks", []))
        nu = sum(len(t.get("units", [])) for t in d.get("tracks", []))
        print(f"{code:10s} [{src}] 전형 {nt:2d} · 모집단위 {nu:3d} · {d['name']}")
