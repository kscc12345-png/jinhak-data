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


_UNIT_ALIASES = {
    "연기전공": "연극영화영상학부",
    "영화영상전공": "연극영화영상학부",
    "국방일반행정전공": "경찰행정학부",
    "국방일반행정": "경찰행정학부",
    "실용음악학부보컬전공기악전공": "실용음악학부",
    "학부수석장학금": "자율전공학부",
    "학부과수석장학금": "자율전공학부",
    "인문대학자율전공": "자율전공융합학부",
    "사회과학대학자율전공": "자율전공융합학부",
    "경상대학자율전공": "자율전공융합학부",
    "자연과학대학자율전공": "자율전공융합학부",
    "생활과학대학자율전공": "자율전공융합학부",
    "생명시스템과학대학자율전공": "자율전공융합학부",
    "농업생명과학대학자율전공": "자율전공융합학부",
    "공과대학자율전공": "자율전공융합학부",
    "기타농생명융합학부포함": "농생명융합학부",
    "인문사회자율전공계열": "자율전공학부",
}


def _norm_unit(nm):
    """학과명 정규화(공백·특수기호·가운뎃점·군표기·수석장학/SW/단과대 접두사/접미사 제거)."""
    import re as _re
    if not nm:
        return ""
    s = _re.sub(r"[\*\★\◆\■\●\○\※\#\†\^\♣\◈\▲\▼\♠\♥\☆\◇\◎\▷\▶\✓\✔\✦\✧\·\•\☎\㈜]+", " ", nm)
    s = _re.sub(r"\[전공개방\]", "", s)
    s = _re.sub(r"^H(?=[가-힣])", "", s)          # H스크랜튼 -> 스크랜튼
    s = _re.sub(r"\s*-\s*.*", "", s)              # 하이픈 세부전공 분리
    s = _re.sub(r"\bSW\b", "", s)                 # SW 전형 태그 제거
    s = _re.sub(r"[・ㆍ·•\-\_\~\/\,\.\[\]\(\)]", "", s)
    s = _re.sub(r"\s+", "", s)
    s = _re.sub(r"^\(?[가나다]\)?", "", s)         # 정시 군 표기 제거
    s = _re.sub(r"(야간|주간|정원내|정원외|5년제|수석장학금|장학금|\d+)$", "", s)
    return s


def _base_unit(nm):
    """캠퍼스 및 괄호 부가정보를 완전히 제거한 순수 학과명."""
    import re as _re
    if not nm:
        return ""
    s = _re.sub(r"\(.*?\)", "", nm)
    s = _re.sub(r"\[.*?\]", "", s)
    return _norm_unit(s)


def _extract_subunits(nm):
    """(전공) 괄호 안의 세부전공 또는 단과대 분리 학과명 목록 추출."""
    import re as _re
    res = []
    # 1. 괄호 안의 텍스트
    for m in _re.findall(r"\((.*?)\)", nm or ""):
        m_clean = _norm_unit(m)
        if len(m_clean) >= 2 and m_clean not in ["서울", "천안", "죽전", "공주", "예산", "국제", "다빈치", "미래", "세종", "5년제", "야간", "주간", "인문", "자연", "예체능"]:
            res.append(m_clean)
    # 2. 단과대 접두사 제거
    no_college = _re.sub(r"^[가-힣]+대학\s*", "", nm or "")
    if no_college != nm:
        res.append(_norm_unit(no_college))
        res.append(_base_unit(no_college))
    # 3. 공백 분할 학과 (예: 스포츠청소년지도학과 노인체육복지학과)
    words = (nm or "").split()
    if len(words) >= 2:
        for w in words:
            w_c = _norm_unit(w)
            if len(w_c) >= 3 and any(w_c.endswith(s) for s in ["과", "부", "전공"]):
                res.append(w_c)
    return res


def _root_unit(nm):
    """학과/학부/전공/어과 접미사를 정규화한 어근."""
    s = _base_unit(nm)
    for suffix in ("어과", "학과", "학부", "전공", "계열"):
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            return s[:-len(suffix)]
    return s


def load_eodiga(code):
    """어디가 결과공개 데이터 로드(정밀 다단계 학과 색인 구축)."""
    p = os.path.join(EODIGA_DIR, f"{code}.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    idx = {}
    base_idx = {}
    root_idx = {}
    for nm, recs in d.get("results", {}).items():
        k_norm = _norm_unit(nm)
        k_base = _base_unit(nm)
        k_root = _root_unit(nm)
        idx.setdefault(k_norm, []).extend(recs)
        base_idx.setdefault(k_base, []).extend(recs)
        if len(k_root) >= 2:
            root_idx.setdefault(k_root, []).extend(recs)
        for sub in _extract_subunits(nm):
            idx.setdefault(sub, []).extend(recs)
            base_idx.setdefault(sub, []).extend(recs)
    d["_idx"] = idx
    d["_base_idx"] = base_idx
    d["_root_idx"] = root_idx
    return d


def _find_eodiga_recs(ed, unit_name):
    """어디가 데이터에서 학과명에 대한 레코드를 5단계 다단계 지능형 탐색."""
    if not ed or not unit_name:
        return None
    idx = ed.get("_idx", {})
    base_idx = ed.get("_base_idx", {})
    root_idx = ed.get("_root_idx", {})
    
    # 1단계: 정규화 완전 일치
    k_norm = _norm_unit(unit_name)
    if k_norm in idx:
        return idx[k_norm]
        
    # 2단계: 괄호/캠퍼스 제거 기본 학과명 일치
    k_base = _base_unit(unit_name)
    if k_base in base_idx:
        return base_idx[k_base]
        
    # 3단계: 괄호 안 세부전공/단과대 분리 학과명 탐색
    for sub in _extract_subunits(unit_name):
        if sub in idx:
            return idx[sub]
        if sub in base_idx:
            return base_idx[sub]
            
    # 4단계: 별칭 사전 매칭
    alias = _UNIT_ALIASES.get(k_norm) or _UNIT_ALIASES.get(k_base)
    if alias:
        a_norm = _norm_unit(alias)
        if a_norm in idx:
            return idx[a_norm]
        if a_norm in base_idx:
            return base_idx[a_norm]
            
    # 5단계: 어근(Root) 일치
    k_root = _root_unit(unit_name)
    if len(k_root) >= 2 and k_root in root_idx:
        return root_idx[k_root]
        
    return None


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
            have.setdefault(c, set()).add(_base_unit(u.get("unit", "")))
    by = {}
    for nm, recs in ed.get("results", {}).items():
        for r in recs:
            cat = _CAT_OF_TRACK.get(r.get("track"))
            if cat:
                by.setdefault(cat, {}).setdefault(nm, []).append(r)
    for cat, unit_recs in by.items():
        tr = track_by_cat.get(cat)
        for nm, recs in unit_recs.items():
            k_norm = _norm_unit(nm)
            k_base = _base_unit(nm)
            if k_norm in have.get(cat, set()) or k_base in have.get(cat, set()):
                continue
            if tr is None:
                tr = {"id": f"eodiga_{cat}", "name": f"{cat}전형", "category": cat,
                      "admission_type": "수시", "method": {}, "gyogwa": None,
                      "auto": True, "units": []}
                univ.setdefault("tracks", []).append(tr)
                track_by_cat[cat] = tr
            tr["units"].append(_eodiga_unit(nm, recs, yr))
            have.setdefault(cat, set()).add(k_norm)
            have.setdefault(cat, set()).add(k_base)


def _apply_eodiga(univ, ed):
    """대학 dict의 각 학과에 어디가 결과(전형별) 부착 + 대표 70%컷 설정."""
    yr = ed.get("year")
    for t in univ.get("tracks", []):
        want = _CAT2TRACK.get(t.get("category"))
        for u in t.get("units", []):
            recs = _find_eodiga_recs(ed, u.get("unit", ""))
            if not recs:
                continue
            # 전형(track) 일치분만
            same = [r for r in recs if not want or r.get("track") == want]
            u["eodiga"] = same or recs
            u["eodiga_year"] = yr
            # 정원(count) 누락 시 어디가 모집인원으로 보완 (P3-1)
            if not u.get("count"):
                for r in (same or recs):
                    if r.get("recruit"):
                        try:
                            u["count"] = int(float(r["recruit"]))
                            break
                        except (ValueError, TypeError):
                            pass
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


#  전형 카테고리 → 표 머리글에서 찾을 낱말
_CAT_HDR_WORDS = {
    "교과": ("학생부교과", "교과"),
    "종합": ("학생부종합", "종합"),
    "논술": ("논술",),
    "실기": ("실기", "실적", "특기"),
}


#  카테고리 → 전형명에서 찾을 낱말 (요강 요약표의 전형명과 맞추기 위한 것)
_CAT_TRACK_WORDS = {
    "교과": ("학생부교과", "교과전형", "교과"),
    "종합": ("학생부종합", "종합전형", "종합"),
    "논술": ("논술",),
    "실기": ("실기", "실적", "특기"),
}


def _curated_criteria(curated, cat):
    """사람(또는 AI)이 요강을 **읽어서** 채운 값. 파서 결과보다 우선한다.

    왜 이 경로가 필요한가 —
    요강 27개는 표 구조가 27가지다. 범용 파서로 다 훑으려면 형식마다
    대응해야 하고, 그렇게 해도 커버리지가 33% 에서 멈췄다.
    반면 **읽어서 채우면** 정확하고 빠르다. 대학당 채울 값은 10개 정도다.

    단, 읽어 넣은 값은 검수가 필요하므로 `_source.text`(원문)를 반드시
    함께 넣어 원문과 대조할 수 있게 한다. `by: "read"` 로 표시한다.

    형식: auto["curated"] = {"교과": {"method": {...}, "gyogwa": {...}}, ...}
    """
    c = ((curated or {}).get(cat) or {})
    m = c.get("method")
    g = c.get("gyogwa")
    if not m and not g:
        return None, None
    method = dict(m) if m else None
    if method and "_source" not in method:
        method["_source"] = dict(c.get("_source") or {})
    gyogwa = dict(g) if g else None
    if gyogwa and "_source" not in gyogwa:
        gyogwa["_source"] = dict(c.get("_source") or {})
    return method, gyogwa


def _curated_suneung(curated, cat, unit_name, college, campus=""):
    """요강을 **읽어서** 채운 수능최저. 파서 결과보다 우선한다.

    왜 이 경로가 필요한가 —
    최저 규칙은 표 형식이 대학마다 다르고, 무엇보다 **귀속 단위가 다르다.**
    어떤 대학은 전 학과 공통, 어떤 대학은 계열별, 공주대는 단과대학별,
    건국대 논술은 인문·자연·수의예과가 각각 다르다. 범용 파서로는
    "이 값이 어느 학과에 걸리는가" 를 맞히지 못해 규칙 33% 에서 멈췄고,
    나머지 54% 는 '미확인' 으로 남아 학생에게 아무 정보도 못 줬다.

    그리고 '미확인' 과 '요강에 없음' 은 전혀 다른 정보다.
    목원대·우송대·한밭대는 요강에 **"모든 전형 미적용"** 이 적혀 있다.
    이걸 '미확인' 으로 두면 학생은 최저를 걱정하며 지원을 망설인다.

    형식:
      auto["curated"]["_suneung"] = {
        "all":  {"rule": {...}, "text": "원문", "page": 16},   # 전 전형·전 학과
        "cats": {"교과": {"rules": [{"units": [...], "colleges": [...],
                                     "rule": {...}, "text": ..., "page": ...}],
                          "all": {...}}},
      }
    우선순위: 학과명 > 단과대학 > 캠퍼스 > 전형 전체 > 대학 전체

    (계열 단위 지정은 없다. `gyeyeol` 은 _guess_gye() 의 추정값이어서
     이걸로 최저를 걸면 추정이 틀린 학과에 틀린 기준이 붙는다.
     계열별로 갈리는 대학은 학과명·단과대학으로 지정한다.)
    반환: (rule, src) 또는 (None, None)
    """
    cs = (curated or {}).get("_suneung")
    if not cs:
        return None, None
    scopes = []
    node = (cs.get("cats") or {}).get(cat)
    if node:
        scopes.append(node)
    if cs.get("all"):
        scopes.append({"all": cs["all"]})
    for node in scopes:
        ents = node.get("rules") or []
        for key, val in (("units", unit_name), ("colleges", college),
                         ("campuses", campus)):
            if not val:
                continue
            for ent in ents:
                if val in (ent.get(key) or []):
                    #  skip=True 는 "이 학과는 읽어서 채우지 않는다" 는 뜻이다.
                    #  이 전형으로 모집하지 않는 학과에 전형 기준을 걸면
                    #  틀린 정보가 된다. 중앙대 학생부교과(지역균형)는
                    #  의학부를 모집하지 않는데(15쪽 모집단위 표) 캠퍼스
                    #  기준(서울 3합 7)이 걸려 의대에 느슨한 기준을
                    #  보여주고 있었다. 그런 학과는 미확인으로 남긴다.
                    if ent.get("skip"):
                        return None, None
                    return ent["rule"], ent
        if node.get("all"):
            return node["all"]["rule"], node["all"]
    return None, None


def _track_criteria(tmethods, gyoinfo, cat):
    """이 카테고리에 해당하는 전형방법·반영교과를 요강 추출 결과에서 고른다.

    반환: (method, gyogwa) — 못 찾으면 (None, None).
    **근거(쪽·원문·신뢰도)를 값 안에 함께 넣어** 사람이 원문과 대조할 수 있게 한다.
    애매하면 채우지 않는다 — 틀린 기준은 잘못된 상담으로 이어진다.
    """
    words = _CAT_TRACK_WORDS.get(cat)
    if not words:
        return None, None

    # 이 카테고리에 속하는 전형들 중 신뢰도 높은 것 우선.
    # confidence 가 'low' 면 요소가 잘려 나간 것이라 쓰지 않는다
    # (일부만 보여주면 나머지 전형요소를 놓친 것처럼 오해를 부른다).
    cands = [(k, v) for k, v in (tmethods or {}).items()
             if any(w in k for w in words) and v.get("confidence") != "low"]
    if not cands:
        # 전형방법은 못 읽었지만 **반영교과는 읽은** 경우.
        # 교과 전형이면 교과를 반영하는 게 자명하므로, 교과 계산이 죽지 않게
        # method 는 자리표시자로 두고(화면엔 '확인되지 않음' 으로 표시됨)
        # 반영교과만 실제값으로 채운다. 이러면 계산은 **진짜 반영교과**로 하고
        # 공시 여부는 정직하게 알린다.
        # (이걸 안 하면 동국대·단국대·충북대·외대에서 읽은 반영교과가 버려진다)
        if cat == "교과" and gyoinfo and gyoinfo.get("subjects"):
            return ({"교과": 100, "placeholder": True},
                    {"subjects": list(gyoinfo["subjects"]),
                     "_source": {"page": gyoinfo.get("page"),
                                 "section": gyoinfo.get("section"),
                                 "text": gyoinfo.get("text"),
                                 "confidence": gyoinfo.get("confidence")}})
        return None, None
    cands.sort(key=lambda kv: (kv[1].get("confidence") != "high",
                               -sum(kv[1].get("elements", {}).values())))
    name, info = cands[0]

    method = dict(info.get("elements") or {})
    if not method:
        return None, None
    method["_source"] = {
        "page": info.get("page"), "section": info.get("section"),
        "text": info.get("text"),
        "track_name": name, "confidence": info.get("confidence"),
        "stages": info.get("stages"), "multiplier": info.get("multiplier"),
    }

    gyogwa = None
    # 교과 반영이 있는 전형에만 반영교과를 붙인다 (종합·논술엔 의미 없음)
    if gyoinfo and gyoinfo.get("subjects") and (method.get("교과") or cat == "교과"):
        gyogwa = {"subjects": list(gyoinfo["subjects"]),
                  "_source": {"page": gyoinfo.get("page"),
                              "section": gyoinfo.get("section"),
                              "text": gyoinfo.get("text"),
                              "confidence": gyoinfo.get("confidence")}}
    return method, gyogwa


def _count_for(ucounts, unit_name, cat, fallback):
    """이 학과의 **이 전형** 모집인원을 표 격자에서 찾는다.

    앱은 결과를 전형별로 보여주므로, '정원'도 그 전형의 모집인원이어야 한다.
    (요강 한 학과에는 입학정원 / 전형별 / 합계가 다 적혀 있어서
     텍스트에서 첫 숫자를 집으면 엉뚱한 값이 들어간다)

    같은 카테고리 안에 세부 전형이 여럿이면(고교추천·지역인재 …) 합산한다.
    못 찾으면 fallback(기존 값)을 그대로 둔다 — **추측해서 채우지 않는다.**
    """
    rec = (ucounts or {}).get(unit_name)
    if not rec:
        return fallback
    by = rec.get("by") or {}
    words = _CAT_HDR_WORDS.get(cat)
    if by and words:
        vals = [v for h, v in by.items() if any(w in h for w in words)]
        if vals:
            return sum(vals)
    return fallback


def convert_auto(auto):
    """auto 추출 JSON → 엔진 호환 대학 dict (학과 중심)."""
    src_file = auto.get("file")
    idx = _rule_index(auto)
    cats = auto.get("categories_detected", []) or []
    # 표에서 읽은 모집인원 격자 {학과: {"total":n, "by":{전형머리글:n}}}
    ucounts = auto.get("unit_counts") or {}
    # 요강에서 읽은 전형방법(근거 쪽·원문 포함) / 반영교과
    tmethods = auto.get("track_methods") or {}
    gyoinfo = auto.get("gyogwa_info") or None
    # 사람/AI 가 요강을 읽어서 채운 값 — 파서 결과보다 우선
    curated = auto.get("curated") or {}

    # 캐노니컬 학과 목록 (모집인원 표) — 이름 기준 dedup, 정원/페이지 유지
    all_units = {}
    for u in auto.get("units_detected", []):
        nm = u["unit"]
        if nm not in all_units:
            all_units[nm] = {
                "unit": nm, "college": u.get("college"),
                "campus": u.get("campus"),
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
            # 단과대학·캠퍼스는 빈 칸만 채운다(표에서 늦게 읽히는 경우가 있다)
            if not cur.get("college") and u.get("college"):
                cur["college"] = u["college"]
            if not cur.get("campus") and u.get("campus"):
                cur["campus"] = u["campus"]
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
                rpage = info["page"] if info else None
                rsrc = info["src"] if info else None
                rsent = info.get("sentence") if info else None
                # 읽어서 채운 최저가 있으면 그것이 최우선(원문 첨부 필수)
                crule, csrc = _curated_suneung(curated, cat, nm,
                                               base.get("college") or "",
                                               base.get("campus") or "")
                if crule:
                    rule, kind = crule, "요강확인"
                    rpage = csrc.get("page")
                    rsrc = "요강 직접확인"
                    rsent = csrc.get("text")
                ipinfo = ipg.get(nm)
                units.append({
                    "unit": nm, "college": base["college"],
                    "campus": base.get("campus"), "gyeyeol": gye,
                    "count": _count_for(ucounts, nm, cat, base["count"]),
                    "suneung_rule": rule,
                    "match": kind,
                    "unit_page": base["unit_page"],
                    "rule_page": rpage,
                    "rule_src": rsrc,
                    "rule_sentence": rsent,
                    "source_file": src_file,
                    "ipgyeol_naesin": ipinfo["cut"] if ipinfo else None,
                    "ipgyeol_low": ipinfo["low"] if ipinfo else None,
                    "ipgyeol_type": ipinfo["cut_type"] if ipinfo else None,
                    "ipgyeol_page": ipinfo.get("page") if ipinfo else None,
                })
            if units:
                # 읽어서 채운 값이 최우선. 다만 **항목별로** 우선한다.
                # (읽은 값에 method 만 있는데 통째로 덮어쓰면 파서가 찾은
                #  반영교과가 날아간다 — 실제로 10건이 6건으로 줄었다)
                cur_m, cur_g = _curated_criteria(curated, cat)
                par_m, par_g = _track_criteria(tmethods, gyoinfo, cat)
                real_m = cur_m or par_m
                real_g = cur_g or par_g
                if real_m or real_g:
                    tracks.append({
                        "id": f"auto_{cat}", "name": f"{cat}전형", "category": cat,
                        "method": real_m or {}, "gyogwa": real_g,
                        "auto": True, "units": units,
                    })
                    continue

                # ⚠️ 아래 method / gyogwa 는 **요강에서 읽은 값이 아니라 기본값**이다.
                # 자동 추출본은 전형요소 비율·반영교과를 아직 못 읽으므로,
                # 교과 계산이 아예 죽지 않게 넣어 두는 자리표시자다.
                #
                # 이걸 앱이 "대학이 공시한 기준" 으로 보여주면 학생은
                # **틀린 기준을 공시값으로 믿는다.** 그래서 placeholder 를 붙여
                # 화면에서 구분할 수 있게 한다. (발행본 5,577 학과 중 5,498 개가
                # 이 기본값이었고, 진짜 공시값은 배재대 3개 전형뿐이다)
                method = ({"교과": 100, "placeholder": True}
                          if cat == "교과" else {})
                gyogwa = ({"subjects": ["국어", "수학", "영어", "사회", "과학"],
                           "placeholder": True} if cat == "교과" else None)
                tracks.append({
                    "id": f"auto_{cat}", "name": f"{cat}전형", "category": cat,
                    "method": method, "gyogwa": gyogwa, "auto": True, "units": units,
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


_INVALID_UNIV_NAMES = {
    "back", "filesave", "forward", "hand", "help", "home", "matplotlib",
    "move", "qt4_editor_options", "subplots", "zoom_to_rect", "test", "untitled"
}

def _is_valid_univ(name):
    """유효한 대학교 이름인지 검증(시스템 아이콘, 더미 영문명 등 제외)."""
    if not name or not isinstance(name, str):
        return False
    name_clean = name.strip().lower()
    if name_clean in _INVALID_UNIV_NAMES:
        return False
    # 한글이 최소 1글자 이상 포함되어 있어야 정상적인 국내 대학임 (예: 아주대학교, 서울대 등)
    has_kor = any("가" <= c <= "힣" for c in name)
    return has_kor


def load_all():
    """정제본 우선, 없으면 자동 변환본으로 통합한 대학 딕셔너리."""
    univs = {}
    # 자동 변환본 먼저
    for f in sorted(glob.glob(os.path.join(AUTO_DIR, "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        with open(f, encoding="utf-8") as fh:
            auto = json.load(fh)
        if not auto.get("code") or not auto.get("name") or not _is_valid_univ(auto.get("name")):
            continue                      # 코드/이름 없는 불량 데이터 및 시스템 더미 건너뜀
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
        if u and _is_valid_univ(u.get("name")) :
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
