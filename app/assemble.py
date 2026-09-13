"""
assemble.py — 데이터 소스 통합.

우선순위:
  1) 정제 데이터 data/universities/{code}.json (사람이 검수/보완) → 그대로 사용
  2) 자동 추출 data/auto/{code}.json → 엔진 형식으로 변환(best-effort)

이로써 정제본이 없는 대학도 '수능최저 판정 + 학과 목록'은 자동 제공된다.
교과 환산표는 자동 추출이 어려워, 자동 변환분은 gyogwa=null(최저만 판정).
"""
import os, sys, json, glob, re
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
    from srcref import _DOTS
    s = _re.sub(r"[\*\★\◆\■\●\○\※\#\†\^\♣\◈\▲\▼\♠\♥\☆\◇\◎\▷\▶\✓\✔\✦\✧\·\•\☎\㈜]+", " ", nm)
    s = _re.sub(r"\[전공개방\]", "", s)
    s = _re.sub(r"^H(?=[가-힣])", "", s)          # H스크랜튼 -> 스크랜튼
    #  붙임표는 종류가 여럿이다. `-` 만 떼면 '의상디자인학과–인문계'
    #  (en dash)가 '의상디자인학과' 와 다른 학과로 남는다.
    s = _re.sub(r"\s*[-\u2010-\u2015\u2212\uff0d]\s*.*", "", s)
    s = _re.sub(r"\bSW\b", "", s)                 # SW 전형 태그 제거
    #  가운뎃점은 종류가 여럿이다(_DOTS). 눈으로는 같은 점인데 요강과
    #  어디가가 서로 다른 것을 써서, 안 지우면 같은 학과가 안 붙는다.
    #  '목재‧종이과학과'(U+2027) ↔ '목재・종이과학과'(U+30FB)
    s = _re.sub(r"[" + _re.escape(_DOTS) + r"\-\_\~\/\,\.\[\]\(\)]", "", s)
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
    """학과/학부/전공/어과/대학 접미사를 정규화한 어근.

    '대학' 을 떼는 이유 — 어디가가 모집단위를 **단과대학 이름**으로
    적는 대학이 있다. 요강은 학과 이름으로 적는다. 안 떼면 같은
    모집단위가 둘로 실린다(실측).

        고려대 교과  경영학과(요강, 최저 있음, 입결 없음)
                   경영대학(어디가, 최저 '모름', 입결 1.48)
        서울대 종합  간호학과 ↔ 간호대학

    학생은 한쪽에서 최저를, 다른 쪽에서 입결을 본다. 떼면 붙는다 —
    새로 붙는 쌍 5개, 잘못 뭉치는 것 0건(실측).
    """
    s = _base_unit(nm)
    for suffix in ("어과", "학과", "학부", "전공", "계열", "대학"):
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


def _eodiga_unit(nm, recs, yr, track_name=""):
    """어디가 결과만으로 학과 unit 구성(대표 70%컷 포함)."""
    best, _matched = _pick_eodiga(recs, track_name)
    if best is None:
        best = recs[0] if recs else {}
    return {
        "unit": nm, "college": None, "gyeyeol": _guess_gyeyeol(nm, ""),
        "count": None, "match": "어디가",
        "suneung_rule": {"type": "none", "label": "수능최저 정보 없음(어디가 결과 기준)"},
        "source_file": None, "eodiga": recs, "eodiga_year": yr,
        "ipgyeol_naesin": best.get("grade70"), "ipgyeol_low": None,
        "ipgyeol_type": (f"어디가 70%컷·환산등급({yr or ''})"
                         if best.get("grade70") else None),
        #  이 컷이 어느 전형의 것인지 — 전형을 나눠 담으면 하나씩이다
        "ipgyeol_label": _eodiga_label(best.get("label"), ""),
        "eodiga_score70": best.get("score70"), "eodiga_comp": best.get("competition"),
    }


def _eodiga_label(label, cat):
    """어디가 전형 이름 → 화면에 쓸 전형 이름."""
    s = re.sub(r"\s+", " ", label or "").strip()
    s = s.replace("수시모집", "").replace("정시모집", "")
    s = re.sub(r"[_]+", "·", s)
    s = re.sub(r"\(\s*\)", "", s).strip()
    return s or (cat + "전형")


def _split_eodiga_tracks(univ, cat, unit_recs, yr):
    """어디가 전형 이름마다 전형을 하나씩 만든다.

    요강이 없는 대학에만 쓴다. 요강이 있으면 그 전형 구성이 옳고,
    어디가에만 있는 학과는 거기 얹으면 된다.
    """
    by_label = {}
    for nm, recs in unit_recs.items():
        for r in recs:
            lb = _eodiga_label(r.get("label"), cat)
            by_label.setdefault(lb, {}).setdefault(nm, []).append(r)
    for lb in sorted(by_label):
        slug = re.sub(r"[^0-9A-Za-z가-힣]", "", lb)[:24]
        tr = {"id": "eodiga_%s_%s" % (cat, slug), "name": lb,
              "category": cat, "admission_type": "수시", "method": {},
              "gyogwa": None, "auto": True, "eodiga_only": True,
              "units": []}
        for nm in sorted(by_label[lb]):
            tr["units"].append(_eodiga_unit(nm, by_label[lb][nm], yr, lb))
        if tr["units"]:
            univ.setdefault("tracks", []).append(tr)


def _merge_eodiga_units(univ, ed, yr, used=None):
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
        if tr is None:
            #  요강이 없는 대학(서울대)은 어디가 전형 이름대로 나눈다.
            #  한 학과에 전형이 셋이면 입결도 셋이다. 하나로 합치면
            #  느슨한 쪽이 대표값이 되어 학생이 '적정' 으로 읽는다.
            _split_eodiga_tracks(univ, cat, unit_recs, yr)
            continue
        for nm, recs in unit_recs.items():
            k_norm = _norm_unit(nm)
            k_base = _base_unit(nm)
            if k_norm in have.get(cat, set()) or k_base in have.get(cat, set()):
                continue
            #  이름은 다른데 이미 어느 학과에 붙은 것이다(어근·별칭으로
            #  찾았다). 또 만들면 같은 모집단위가 두 줄이 된다 —
            #  한쪽엔 최저가, 다른 쪽엔 입결이 있는 채로.
            if used and all(id(r) in used for r in recs):
                continue
            if tr is None:
                tr = {"id": f"eodiga_{cat}", "name": f"{cat}전형", "category": cat,
                      "admission_type": "수시", "method": {}, "gyogwa": None,
                      "auto": True, "units": []}
                univ.setdefault("tracks", []).append(tr)
                track_by_cat[cat] = tr
            tr["units"].append(_eodiga_unit(nm, recs, yr, tr.get("name") or ""))
            have.setdefault(cat, set()).add(k_norm)
            have.setdefault(cat, set()).add(k_base)


#  전형 이름을 가르는 낱말 — 어디가 이름과 요강 전형 이름을 잇는다.
#  '일반' 은 맨 뒤에 둔다. 거의 모든 대학에 있어서 가리는 힘이 약하다.
_TRACK_KEYS = [
    "지역균형", "고교추천", "학교장추천", "교과우수", "학생부우수",
    "지역인재", "기회균형", "고른기회", "사회통합", "사회기여", "사회공헌",
    "특성화고", "농어촌", "만학도", "재직자", "특기자", "실기", "실적",
    "논술", "면접형", "서류형", "활동우수", "탐구형", "융합형", "성장형",
    "어울림", "자기추천", "네오르네상스", "다빈치", "탐구", "추천",
    "일반",
]


def _label_keys(s):
    import re as _re
    t = _re.sub(r"\s+", "", s or "")
    return {k for k in _TRACK_KEYS if k in t}


def _pick_eodiga(recs, track_name):
    """이 전형의 70%컷 기록을 고른다.

    반환: (기록, 전형까지 맞췄나)
    """
    pool = [r for r in recs if r.get("grade70") is not None]
    if not pool:
        return None, False
    want = _label_keys(track_name)
    if want:
        scored = []
        for r in pool:
            got = _label_keys(r.get("label"))
            n = len(want & got)
            if n:
                #  겹치는 낱말이 많고, 엇갈리는 낱말이 적은 쪽
                scored.append((n, -len(got ^ want), r))
        if scored:
            scored.sort(key=lambda x: (-x[0], -x[1]))
            return scored[0][2], True
    #  전형을 못 가렸다. 여기서 '일반' 을 고르면 거의 늘 가장 느슨한
    #  컷이 잡힌다 — 학생이 못 갈 곳을 갈 수 있다고 읽는다.
    #  가장 엄격한 것을 쓴다. 범위는 부르는 쪽이 함께 내보낸다.
    pool.sort(key=lambda r: r.get("grade70"))
    return pool[0], False


def _apply_eodiga(univ, ed):
    """대학 dict의 각 학과에 어디가 결과(전형별) 부착 + 대표 70%컷 설정."""
    yr = ed.get("year")
    used = set()          # 실제로 어느 학과에 붙은 결과 행(id)
    for t in univ.get("tracks", []):
        want = _CAT2TRACK.get(t.get("category"))
        for u in t.get("units", []):
            recs = _find_eodiga_recs(ed, u.get("unit", ""))
            if not recs:
                continue
            # 전형(track) 일치분만
            same = [r for r in recs if not want or r.get("track") == want]
            if want:
                #  전형이 맞는 행만 '썼다' 고 친다. 논술·실기는
                #  `_CAT2TRACK` 에 없어 이름만 맞으면 교과·종합 행까지
                #  가져다 쓴다 — 그것까지 치면 진짜 교과 줄이 사라진다.
                for r in same:
                    used.add(id(r))
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
            # 대표 70%컷 — **이 전형의 것**을 고른다(_pick_eodiga 주석)
            best, matched = _pick_eodiga(same or recs, t.get("name") or "")
            if best is None:
                continue
            u["ipgyeol_naesin"] = best.get("grade70")
            u["ipgyeol_low"] = None
            #  어느 전형의 컷인지 화면에 적는다. 못 맞췄을 때 특히 중요하다.
            u["ipgyeol_label"] = _eodiga_label(best.get("label"), "")
            if matched:
                u["ipgyeol_type"] = f"어디가 70%컷·환산등급({yr or ''})"
            else:
                #  전형별 컷이 갈리는데 어느 것인지 못 가렸다. 가장
                #  엄격한 것을 쓰고 범위를 함께 준다 — 학생이 하나의
                #  숫자가 아님을 알아야 한다.
                cand = sorted(
                    ((r.get("grade70"), _eodiga_label(r.get("label"), ""))
                     for r in (same or recs) if r.get("grade70") is not None),
                    key=lambda x: x[0])
                u["ipgyeol_type"] = (
                    f"어디가 70%컷·환산등급({yr or ''}) · "
                    "전형이 여럿이라 가장 엄격한 것")
                if len(cand) > 1:
                    u["ipgyeol_choices"] = [
                        {"track": lb, "cut": g} for g, lb in cand]
                    u["ipgyeol_range"] = [cand[0][0], cand[-1][0]]
            u["eodiga_score70"] = best.get("score70")
            u["eodiga_comp"] = best.get("competition")
    # 어디가에만 있는 학과 추가(모집요강 부실 대학 대응)
    _merge_eodiga_units(univ, ed, yr, used)
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
    #  ── 전형 이름대로 나눈다 ────────────────────────────────────
    #
    #  서울대 사회복지학과의 어디가 기록은 셋이다.
    #
    #      학생부종합전형(지역균형전형)          70%컷 1.30
    #      학생부종합전형(일반전형)              70%컷 2.36
    #      학생부종합전형(기회균형·사회통합)       컷 없음
    #
    #  하나로 합치면 '일반' 이 대표값이 되어 2.36 이 된다. 내신 2.0 인
    #  학생이 서울대를 '적정' 으로 읽는다 — 지역균형은 1.30 이다.
    #  틀린 방향이 위험한 쪽이므로 전형을 나눠 각자의 컷을 붙인다.
    for tk, unit_recs in by_track.items():
        cat = tmap.get(tk, "종합")
        by_label = {}
        for nm, recs in unit_recs.items():
            for r in recs:
                lb = _eodiga_label(r.get("label"), cat)
                by_label.setdefault(lb, {}).setdefault(nm, []).append(r)
        for lb in sorted(by_label):
            units = [_eodiga_unit(nm, by_label[lb][nm], yr, lb)
                     for nm in sorted(by_label[lb])]
            if not units:
                continue
            slug = re.sub(r"[^0-9A-Za-z가-힣]", "", lb)[:24]
            tracks.append({"id": f"eodiga_{cat}_{slug}", "name": lb,
                           "category": cat, "admission_type": "수시",
                           "method": {}, "gyogwa": None, "auto": True,
                           "eodiga_only": True, "units": units})
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


def _su_rule_key(r):
    """규칙을 견줄 수 있는 꼴로 — 같은 기준인지만 가른다."""
    import json as _json
    r = r or {}
    return _json.dumps({k: r.get(k) for k in
                        ("type", "sum", "n", "pool", "required", "each_max",
                         "korean_max", "english_max", "extra")},
                       ensure_ascii=False, sort_keys=True)


def _rule_index(auto):
    """전형유형(category)별 최저 규칙 색인: 이름/계열/공통 매칭용."""
    from collections import Counter
    idx = {}

    def ensure(cat):
        return idx.setdefault(cat, {"by_name": {}, "by_gye": {},
                                    "by_college": {}, "all": []})

    #  요강은 최저 범위를 **단과대학**으로 적는 일이 많다(충남대 간호대학·
    #  약학대학·의과대학, 한국외대 상경대학·영어대학). 학과 목록은 학과
    #  단위라 이름으로는 안 닿는다 — '간호대학' 규칙을 간호학과가 못
    #  받아 전형 대표값을 받았다. 학과→단과대학 자료가 이미 있으니
    #  그것으로 잇는다.
    _colleges = {_norm_unit(v) for v in
                 (auto.get("unit_colleges") or {}).values() if v}

    #  같은 표를 표 경로와 본문 경로로 두 번 읽으므로 같은 기준이 두 번
    #  들어온다. 한쪽은 범위가 붙고 한쪽은 안 붙는다. 범위 없는 복사본이
    #  대표값 풀에 들어가면 그것이 대표로 뽑혀 엉뚱한 학과에 퍼진다 —
    #  경희대 41학과가 의약 기준(3합 4)을 받았다(요강은 체육 계열에
    #  '1개 영역 이상 3등급'). **범위를 아는 쪽이 더 많이 아는 쪽이다.**
    _scoped_keys = set()
    #  그 규칙의 짝이 **넓은 범위**(계열·전 모집단위)로도 적혔는가.
    #  넓은 짝이 있으면 그 규칙은 전형에 두루 걸리는 기준이므로 범위
    #  없는 사본도 대표값이 될 수 있다(경희대 교과 인문/자연 2합 5).
    _broad_keys = set()
    #  유형마다 규칙이 몇 개고 그중 범위가 적힌 것이 몇 개인가.
    #  대부분에 범위가 적혀 있으면 '전형 공통 기준' 이라는 것이 없다 —
    #  요강이 학과마다 따로 적은 대학이다. 그때 범위 없는 규칙 하나를
    #  대표로 뽑으면 그것은 남의 학과 기준이 된다(충남대 교과 49학과).
    _n_rule, _n_scoped, _n_units = {}, {}, {}
    for _r in ((auto.get("su_scope") or {}).get("scoped") or []):
        if _r.get("narrow") or not _r.get("category"):
            continue
        _c = _r["category"]
        _n_rule[_c] = _n_rule.get(_c, 0) + 1
        if _r.get("units") or _r.get("all_units") or _r.get("gye_scope"):
            _n_scoped[_c] = _n_scoped.get(_c, 0) + 1
            _scoped_keys.add((_c, _su_rule_key(_r.get("rule"))))
            if _r.get("all_units") or _r.get("gye_scope"):
                _broad_keys.add((_c, _su_rule_key(_r.get("rule"))))
        if _r.get("units"):
            _n_units[_c] = _n_units.get(_c, 0) + 1
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
        #  범위와 함께 이미 있는 기준이면 **대표 후보에서 뺀다.**
        #  버리지는 않는다 — 단과일치·이름일치에는 쓸 수 있다.
        #  `common` 은 라벨 최빈값으로 뽑으므로, 같은 표를 두 경로로
        #  읽어 두 번 세어지면 그것이 대표가 된다. 경희대 의약 기준이
        #  그렇게 대표가 되어 119학과가 받았다(실측).
        _k = (cat, _su_rule_key(row.get("rule")))
        if _k in _scoped_keys:
            info["dup"] = True
            #  짝의 범위가 계열·전 모집단위면 대표값이 될 수 있다
            info["dup_broad"] = _k in _broad_keys
        c["all"].append(info)
        if gye in ("인문", "자연"):
            c["by_gye"].setdefault(gye, info)
    #  전형 귀속까지 붙은 규칙(harvest_su_scope) — 문장의 **자리** 위에서
    #  전형 이름을 찾아 붙인 것이라 category 를 믿을 수 있다. 위의
    #  suneung_text 는 category 가 비어 '기타' 로 뭉쳐 있었다.
    for row in ((auto.get("su_scope") or {}).get("scoped") or []):
        if row.get("narrow") or not row.get("category"):
            continue          # 재직자·기회균형 등은 대표값으로 쓰면 안 된다

        c = ensure(row["category"])
        sent = row.get("text") or row.get("sentence") or ""
        gye = _sentence_gye(sent)
        info = {"rule": row["rule"], "page": row.get("page"), "src": "귀속",
                "name": "", "search": sent, "gye": gye, "sentence": sent,
                "track": row.get("track", "")}
        #  범위 없는 복사본은 대표 후보에서 뺀다(위와 같은 이유)
        if not (row.get("units") or row.get("all_units")
                or row.get("gye_scope")):
            _k = (row["category"], _su_rule_key(row.get("rule")))
            if _k in _scoped_keys:
                info["dup"] = True
                info["dup_broad"] = _k in _broad_keys
        #  요강이 '어느 모집단위' 인지 적어 놨으면 그대로 지킨다.
        #  서울대 일반전형은 미술대학 디자인과만 최저가 있다.
        if row.get("exclude_units"):
            info["exclude"] = list(row["exclude_units"])
        #  범위가 **계열**로 적힌 규칙 — 그 계열 학과만 받는다.
        #  대표값 풀(`all`)에는 넣지 않는다. 넣으면 계열을 못 잡은
        #  학과가 남의 계열 기준을 받는다(경희대 119학과 — 실측).
        #  계열을 못 잡은 학과는 '미확인' 이 되어 요강을 직접 보게 되고,
        #  그게 남의 기준을 받는 것보다 낫다.
        gs = row.get("gye_scope") or []
        if gs:
            for g in gs:
                c["by_gye"].setdefault(g, info)
            continue
        units = row.get("units") or []
        if units:
            info["name"] = units[0]
            info["units"] = list(units)
            for nm in units:
                nk = _norm_unit(nm)
                c["by_name"].setdefault(nk, info)
                #  단과대학 이름이면 소속 학과가 찾을 수 있게 따로 둔다.
                #  괄호는 떼고 본다 — '자연과학대학(수학과, 정보통계학과
                #  외)' 는 자연과학대학 규칙이다.
                bk = _base_unit(nm)
                if nk in _colleges or (bk and bk in _colleges):
                    c["by_college"].setdefault(bk or nk, info)
            #  이름이 박힌 규칙은 다른 학과로 새 나가면 안 된다
            continue
        c["all"].append(info)
        if gye in ("인문", "자연"):
            c["by_gye"].setdefault(gye, info)

    #  세부 전형별 색인 — 같은 유형 안에서 최저가 갈릴 때 쓴다.
    #  서울대 종합은 지역균형 3합 7, 일반 미적용이다. 유형 색인만 쓰면
    #  둘 중 하나가 전체에 붙는다.
    for cat, c in idx.items():
        c["by_track"] = {}
    for row in ((auto.get("su_scope") or {}).get("scoped") or []):
        cat, tr = row.get("category"), (row.get("track") or "").strip()
        if not cat or not tr:
            continue
        c = ensure(cat)
        sent = row.get("text") or row.get("sentence") or ""
        info = {"rule": row["rule"], "page": row.get("page"), "src": "귀속",
                "name": "", "search": sent, "gye": _sentence_gye(sent),
                "sentence": sent, "track": tr}
        if row.get("exclude_units"):
            info["exclude"] = list(row["exclude_units"])
        t = c["by_track"].setdefault(tr, {"by_name": {}, "by_gye": {},
                                          "by_college": {},
                                          "all": [], "common": None})
        units = row.get("units") or []
        if units:
            info["name"] = units[0]
            for nm in units:
                nk = _norm_unit(nm)
                t["by_name"].setdefault(nk, info)
                bk = _base_unit(nm)
                if nk in _colleges or (bk and bk in _colleges):
                    t["by_college"].setdefault(bk or nk, info)
        else:
            t["all"].append(info)
            if info["gye"] in ("인문", "자연"):
                t["by_gye"].setdefault(info["gye"], info)
    for cat, c in idx.items():
        for tr, t in (c.get("by_track") or {}).items():
            t["common"] = t["all"][0] if t["all"] else None

    # 전 전형 통합 색인(__ALL__): 최저가 특정 전형에만 잡혔을 때 교차 폴백용.
    # (많은 대학이 교과·종합에 동일 최저를 적용하나, 파서가 직전 전형헤더로만 분류함)
    #
    #  논술·실기를 여기서 빼 보았고 **되돌렸다**(2026-09-10 실측).
    #  빼면 동국대 컴퓨터･AI학부·약학과가 종합에서 논술 최저를 받는 것이
    #  없어진다(2학과, 엄한 쪽). 그런데 한양대 의예과가 '3개 영역 합 4'
    #  에서 'n=1' 로 무너지고 성균관대 종합 22학과가 느슨해졌다 —
    #  거기서는 이 폴백이 맞는 값을 주고 있었다. 의예과가 느슨해지는 것이
    #  훨씬 위험하다. 동국대 2학과는 '이름일치(타전형)' 로 나가므로
    #  화면에 '다른 전형의 기준 — 참고용' 이라고 밝혀진다.
    allc = {"by_name": {}, "by_gye": {}, "all": []}
    for cat, c in idx.items():
        allc["all"].extend(c["all"])
        for k, v in c["by_name"].items():
            allc["by_name"].setdefault(k, v)
        for k, v in c["by_gye"].items():
            allc["by_gye"].setdefault(k, v)
    idx["__ALL__"] = allc
    for cat, c in idx.items():
        #  규칙 대부분에 범위가 적힌 유형은 대표값을 쓰지 않는다.
        #  '전형 공통 기준' 이라는 것이 없는 대학이다.
        n_all, n_sc = _n_rule.get(cat, 0), _n_units.get(cat, 0)
        #  학과·단과대학 단위 범위가 규칙의 **40% 이상**이면 그 대학은
        #  학과마다 기준을 따로 적은 것이다. 충남대 교과는 23개 중
        #  11개(48%)다 — 대표값을 쓰면 49학과가 남의 학과 기준을 받는다.
        #  계열·전 모집단위 범위는 세지 않는다 — 그건 공통 기준이 있다는
        #  뜻이라 대표값이 맞다(경희대 교과 6개 중 units 1개).
        c["no_common"] = bool(n_all >= 4 and n_sc * 5 >= n_all * 2)
    for cat, c in idx.items():
        #  대표값은 **중복 아닌 것**에서 뽑는다. 같은 표를 두 경로로 읽어
        #  두 번 세어진 규칙이 최빈값이 되면 엉뚱한 기준이 전형 전체에
        #  퍼진다(경희대 의약 기준 → 119학과 — 실측).
        #  중복 아닌 것이 먼저다. 하나도 없으면 **넓은 짝을 가진**
        #  사본만 되살린다 — 좁은 짝만 있는 사본을 되살리면 그 학과들
        #  만의 기준이 전형 전체에 퍼진다(충남대 종합 62학과가
        #  수의과대학 기준을 받았다 — 실측).
        pool = ([x for x in c["all"] if not x.get("dup")]
                or [x for x in c["all"] if x.get("dup_broad")])
        if pool:
            lab = Counter(x["rule"].get("label", "")[:20]
                          for x in pool).most_common(1)[0][0]
            c["common"] = next((x for x in pool
                                if x["rule"].get("label", "")[:20] == lab),
                               pool[0])
        else:
            c["common"] = None
    return idx


# 특수/의약계열: 학과 이름 키워드 → 최저 규칙 단과대학명에 들어갈 토큰
_SPECIAL = [
    ("의예", "의과"), ("의학", "의과"), ("치의", "치의"), ("치과", "치의"),
    ("한의", "한의"), ("약학", "약학"), ("제약", "약학"),
    ("수의", "수의"), ("간호", "간호"),
]


def _su_none_cats(auto):
    """요강이 '최저 없음' 이라고 적은 전형들 — 유형별로 모아 둔다.

    사람이 손으로 적어 온 수능최저 90건 중 40건이 이것이었다. '없음' 도
    학생에게는 정보다 — 최저를 못 맞춰도 쓸 수 있는 전형이 어디인지가
    그것이다.

    그런데 **주장하지 않고 근거로 붙인다.** 요강의 '없음' 은 세부 전형
    단위로 적혀 있는데(충북대 종합Ⅰ·SW는 미적용, 종합Ⅱ는 2개합 8),
    우리가 만드는 자동 전형은 유형 하나뿐이다. '종합은 없음' 이라고
    적으면 종합Ⅱ 지원자에게 거짓이 된다.

    판정은 어차피 안 바뀐다 — `suneung.evaluate` 는 type=none 이면 못
    찾았을 때도 'na'(미적용)를 돌려준다. 바뀌는 것은 라벨뿐이다.

    반환: {유형: [{track, page, text, src}…]}
    """
    scope = auto.get("su_scope") or {}
    out = {}
    for row in (scope.get("none") or []):
        if row.get("narrow"):
            continue
        cat = row.get("category")
        if cat:
            out.setdefault(cat, []).append(row)
    return out


def _su_split_note(auto, cat):
    """이 전형 유형 안에서 최저가 갈리는가. 갈리면 한 줄로 적는다.

    요강은 세부 전형마다 최저를 따로 적는다. 우리 자동 전형은 유형
    하나뿐이라 그중 하나가 유형 전체에 붙는다. 어느 전형 기준인지,
    어느 전형은 미적용인지 학생이 알아야 한다.
    """
    scope = auto.get("su_scope") or {}
    have, none = [], []
    for r in (scope.get("scoped") or []):
        if r.get("category") != cat or r.get("narrow"):
            continue
        p = r.get("printed_page") or r.get("page")
        t = (r.get("track") or "").strip()
        if t and (t, p) not in have:
            have.append((t, p))
    for r in (scope.get("none") or []):
        if r.get("category") != cat or r.get("narrow"):
            continue
        p = r.get("printed_page") or r.get("page")
        t = (r.get("track") or "").strip()
        if t and (t, p) not in none:
            none.append((t, p))
    #  한쪽만 있으면 갈리는 게 아니다
    if not have or not none:
        return None

    def fmt(xs):
        return " · ".join("«%s»(%s쪽)" % (t, p) for t, p in xs[:3])

    return ("요강은 세부 전형마다 최저를 따로 적었습니다 — %s 은 기준이 "
            "있고 %s 은 미적용입니다. 이 화면은 전형 유형(%s)으로 묶여 "
            "있어 기준이 있는 쪽을 보여줍니다. 지원할 전형을 요강에서 "
            "확인하세요." % (fmt(have), fmt(none), cat))


def _su_none_label(rows):
    """'없음' 근거를 한 줄로. 어느 전형인지·몇 쪽인지를 남긴다."""
    names, pages = [], []
    for r in rows[:4]:
        t = (r.get("track") or "").strip()
        if t and t not in names:
            names.append(t)
        p = r.get("printed_page") or r.get("page")
        if p and p not in pages:
            pages.append(p)
    who = " · ".join("«%s»" % n for n in names) if names else "일부 전형"
    where = ("요강 %s쪽" % "·".join(str(p) for p in pages[:3])) if pages else "요강"
    return ("%s 은 수능최저 미적용이라고 %s에 적혀 있습니다. "
            "같은 유형 안에서도 세부 전형·학과에 따라 다를 수 있습니다 — "
            "요강을 확인하세요." % (who, where))


#  예체능인지는 **요강이 적은 단과대학**으로 본다. `_guess_gyeyeol` 은
#  체육·무용·미술을 '공통' 으로 보는데 그것을 바꾸면 교과 계산까지
#  흔들리므로, 최저 계열 매칭에만 쓰는 판정을 따로 둔다.
_ART_COLLEGE = __import__("re").compile(
    r"예술|디자인|체육|음악|미술|무용|연극|영화|공연|스포츠|조형")
#  단과대학을 못 읽은 학과만 이름으로 본다. 낱말을 좁게 둔다 —
#  '디자인' · '의상' · '영상' 은 예체능이 아닌 학과에도 들어간다
#  (경희대 조리&푸드디자인학과는 호텔관광대학, 의상학과는 생활과학대학).
_ART_UNIT = __import__("re").compile(
    r"체육|스포츠|태권도|유도|무용|성악|작곡|기악|피아노|관현악|"
    r"미술|회화|조소|한국화|공예|연극|연기|실용음악|예체능|예술")


def _match_one(cat_idx, unit_name, gye, college, tag="", allow_gye=True):
    """단일 색인에서 매칭 시도. (info, kind) 또는 (None,None).
    allow_gye=False면 계열추정(광범위) 제외 — 타전형 폴백 시 오적용 방지."""
    if not cat_idx:
        return None, None
    if unit_name in cat_idx["by_name"]:
        return cat_idx["by_name"][unit_name], "이름일치" + tag
    #  요강이 적은 이름과 학과 목록의 표기가 조금 다를 수 있다
    #  ('미술대학 디자인과' ↔ '디자인과')
    _nk = _norm_unit(unit_name)
    if _nk and _nk in cat_idx["by_name"]:
        return cat_idx["by_name"][_nk], "이름일치" + tag
    #  여럿에 붙으면 **긴 이름**이 이긴다 — 더 좁게 적은 쪽이 그 학과를
    #  말한 것이다. 그리고 낱말 자리를 본다('약학과' ≠ '한약학과').
    if _nk and len(_nk) >= 3:
        for _k in sorted(cat_idx["by_name"], key=len, reverse=True):
            if _name_match(_nk, _k):
                return cat_idx["by_name"][_k], "이름일치" + tag
    allrules = cat_idx.get("all", [])

    def _txt(info):
        return (info.get("search") or info.get("name") or "")

    #  범위가 **단과대학**으로 적힌 규칙 — 그 단과대학 소속 학과가 받는다.
    #  `all` 순회로는 못 찾는다. 이름이 박힌 규칙은 `by_name` 에만 들어가고
    #  `all` 에는 안 들어가기 때문이다(다른 학과로 새 나가면 안 되니까).
    if college:
        bc = cat_idx.get("by_college") or {}
        for key in (_norm_unit(college), _base_unit(college)):
            if key and key in bc:
                return bc[key], "단과일치" + tag

    for trig, coll in _SPECIAL:
        if trig in unit_name:
            for info in allrules:
                if coll in _txt(info):
                    return info, "단과일치" + tag
    if college:
        for info in allrules:
            if college in _txt(info):
                return info, "단과일치" + tag
    #  예체능 계열 규칙이 있으면 예체능 학과가 받는다. 없으면 그
    #  학과들이 인문/자연 기준이나 전형 대표값을 받는다(경희대
    #  아동가족학과가 체육 기준을 받았다 — 실측).
    #
    #  단과대학이 읽혔으면 그것이 정한다. 단과대학이 예체능이 아니면
    #  예체능 규칙을 주지 않는다 — 이름 낱말만 보면 조리&푸드디자인학과
    #  (호텔관광대학)가 체육 기준을 받는다.
    if allow_gye and "예체능" in cat_idx.get("by_gye", {}):
        if college:
            if _ART_COLLEGE.search(college):
                return cat_idx["by_gye"]["예체능"], "계열추정" + tag
        elif _ART_UNIT.search(unit_name or ""):
            return cat_idx["by_gye"]["예체능"], "계열추정" + tag
    if allow_gye and gye in cat_idx.get("by_gye", {}):
        return cat_idx["by_gye"][gye], "계열추정" + tag
    return None, None


#  학과 이름이 끝나는 글자. 짧은 이름이 이 뒤에서 시작하면 이름 자리다.
_UNIT_END = set("과부열공원학군계")


def _name_touch(short, long_):
    """`short` 가 `long_` 안의 **이름 자리**에 있는가.

    부분 일치만 보면 '약학과' 가 '한약학과' 에 붙는다. 앞 글자가 학과
    이름의 끝 글자('전자공학부|전자공학과')일 때만 받는다.
    """
    if not short or not long_:
        return False
    if short == long_:
        return True
    i = long_.find(short)
    while i >= 0:
        if i == 0 or long_[i - 1] in _UNIT_END:
            return True
        i = long_.find(short, i + 1)
    return False


def _name_match(a, b):
    """두 학과 이름이 같은 학과를 말하는가 — 어느 쪽이 길어도 좋다."""
    if not a or not b:
        return False
    return _name_touch(a, b) if len(a) <= len(b) else _name_touch(b, a)


def _excluded(info, unit_name):
    """이 규칙이 이 학과를 **뺀다고** 적혀 있는가."""
    ex = (info or {}).get("exclude") or []
    if not ex:
        return False
    nk = _norm_unit(unit_name)
    for e in ex:
        #  '약학과 제외' 가 한약학과까지 빼면, 한약학과는 '그 외' 규칙
        #  에서도 빠지고 남의 규칙을 받는다(경희대 — 실측).
        if _name_match(_norm_unit(e), nk):
            return True
    return False


def _match_rule(cat_idx, unit_name, gye, college="", all_idx=None):
    """학과에 최저 규칙 매칭. 반환: (info, match_kind)
    우선순위: 이름일치 > 의약/특수 단과일치 > 단과일치 > 계열추정 > (타전형 폴백) > 전형공통"""
    if not cat_idx and not all_idx:
        return None, "미확인"
    info, kind = _match_one(cat_idx, unit_name, gye, college)
    if info and not _excluded(info, unit_name):
        return info, kind
    # 이 전형에 최저가 없거나 못 찾음 → 전 전형 통합 색인에서 폴백(교과↔종합 동일 최저 흔함)
    if all_idx:
        info, kind = _match_one(all_idx, unit_name, gye, college,
                                tag="(타전형)", allow_gye=False)
        if info and not _excluded(info, unit_name):
            return info, kind
    if cat_idx and cat_idx.get("common") \
            and not cat_idx.get("no_common") \
            and not _excluded(cat_idx["common"], unit_name):
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
    return _curated_pick(scopes, unit_name, college, campus)


def _curated_pick(scopes, unit_name, college, campus=""):
    """scope 목록을 순서대로 보며 이 학과에 걸리는 규칙을 고른다.

    scope 하나는 {"rules": [...], "all": {...}} 모양이다. 세부 전형(트랙)도
    같은 모양이라 이 함수를 그대로 쓴다.
    """
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


#  격자 머리글에 붙는 꼬리 — '#3' 같은 열 번호와 정원 구분
_HDR_TAIL = re.compile(r"#\d+$")
_HDR_NOISE = re.compile(r"수시\s*모집(?:인원)?|정원\s*내|정원\s*외|모집\s*인원"
                        r"|\(정원\s*[내외]\)|전년\s*대비|명$|\d+$")


_BR_OPEN = "([（［"
_BR_CLOSE = ")]）］"
_BR_EMPTY = re.compile("[" + re.escape(_BR_OPEN) + r"]\s*[" + re.escape(_BR_CLOSE) + "]")
#  맨 앞의 [○○캠퍼스] — 전형 이름이 아니라 어디서 뽑는지다.
_BR_CAMPUS = re.compile("^[" + re.escape(_BR_OPEN) + r"]\s*"
                        r"([^" + re.escape(_BR_CLOSE) + r"]*캠퍼스)\s*"
                        "[" + re.escape(_BR_CLOSE) + "]\\s*")


def _strip_unpaired(t):
    """짝 없는 괄호만 앞뒤에서 뗀다.

    통째로 떼면 '학생부종합(SW인재)' 가 '학생부종합(SW인재' 가 된다 —
    학생 화면의 탭 이름이다(실측 8건).
    """
    for _ in range(8):
        if not t:
            break
        op = sum(t.count(c) for c in _BR_OPEN)
        cl = sum(t.count(c) for c in _BR_CLOSE)
        if t[0] in _BR_CLOSE or (t[0] in _BR_OPEN and op > cl):
            t = t[1:].strip()
            continue
        if t[-1] in _BR_OPEN or (t[-1] in _BR_CLOSE and cl > op):
            t = t[:-1].strip()
            continue
        break
    return t


def _hdr_name(h):
    """격자 머리글을 화면에 쓸 전형 이름으로 다듬는다."""
    t = _HDR_TAIL.sub("", str(h or "")).strip()
    t = _HDR_NOISE.sub("", t)
    #  껍데기만 남은 괄호는 통째로 뺀다 — '…특성화고교졸업자[정원외]'
    #  에서 '정원외' 가 빠지면 '[]' 만 남는다(실측).
    t = _BR_EMPTY.sub("", t)
    #  괄호는 짝이 안 맞을 때만 뗀다. `.strip(" ()[]...")` 로 통째로
    #  떼면 이름의 일부인 닫는 괄호가 사라진다.
    t = _strip_unpaired(t.strip(" \u00b7-_"))
    #  캠퍼스는 뒤로. 떼지는 않는다 — 건양대는 두 캠퍼스가 같은 이름의
    #  전형을 따로 쓴다(`교과일반[교과]` 17과·16과). 떼면 같은 이름이
    #  되어 `_tidy_subtracks` 가 합치고 두 캠퍼스 학과가 섞인다.
    m = _BR_CAMPUS.match(t)
    if m and len(t) > len(m.group(0)):
        #  가운뎃점·쉼표·빗금은 쓰지 않는다. `_tidy_subtracks` 가
        #  그런 이름을 '전형 여럿을 나열한 줄' 로 보고 버린다 —
        #  건양대 전형 여덟 개가 다섯 개가 됐다(실측).
        t = "%s (%s)" % (t[m.end():].strip(), m.group(1).strip())
    return t


#  일반 학생과 무관한 전형 — 나누면 모두의 목록만 길어진다.
#  해당하는 학생은 소수이고, 유형에 묶여 있어도 최저·컷은 보인다.
_SUB_NARROW = re.compile(
    r"기회\s*균형|고른\s*기회|사회\s*통합|사회\s*기여|사회\s*공헌"
    r"|특수\s*교육|장애|농어촌|만학도|재직자|특성화고|계약\s*학과"
    r"|북한이탈|서해5도|지역\s*의사|국방|국가\s*안보|다문화|보훈|기초\s*생활"
    r"|재외국민|외국인|편입|정원\s*외|취업자|평생\s*학습")


def _auto_subtracks(auto, cat, ucounts):
    """파서가 만드는 세부 전형. 사람이 적어 준 것이 없을 때 쓴다."""
    subs = _subtracks_from_grid(cat, ucounts)
    if not subs:
        subs = _subtracks_from_sections(auto, cat)
    return _tidy_subtracks(subs)


def _tidy_subtracks(subs):
    """겹친 이름을 합치고, 좁은 전형과 전형이 아닌 것을 뺀다."""
    out, by_name = [], {}
    for sb in subs or []:
        nm = (sb.get("name") or "").strip()
        if not nm:
            continue
        #  '학교추천, 학업우수' 는 최저가 걸리는 전형 둘을 적은 것이지
        #  전형 이름이 아니다
        if re.search(r"[,·/]", nm) and len(nm) > 6:
            continue
        #  좁은 전형은 **버리지 않고 적어 둔다.** 버리면 그 전형으로만
        #  뽑는 학과가 목록에서 사라진다(아주대 종합 46 → 38).
        #  화면에서 기본으로 접어 두면 모두의 목록은 깔끔해진다.
        if _SUB_NARROW.search(nm):
            sb = dict(sb)
            sb["narrow"] = True
        old = by_name.get(nm)
        if old is None:
            by_name[nm] = sb
            out.append(sb)
            continue
        #  같은 이름은 하나로 — 격자 열이 정원내/정원외로 갈린 것이다
        for key in ("count_hdr", "units"):
            a, b = old.get(key) or [], sb.get(key) or []
            if a or b:
                old[key] = sorted(set(a) | set(b))
    #  일반 전형이 둘 이상이어야 나눌 값이 있다. 좁은 전형만 여럿인
    #  경우는 나누지 않는다 — 유형 하나로 두는 것이 낫다.
    wide = [x for x in out if not x.get("narrow")]
    return out if len(wide) >= 2 else []


def _subtracks_from_grid(cat, ucounts):
    """모집인원 표의 전형별 칸에서 세부 전형을 만든다.

    이게 가장 확실하다 — 어느 학과를 뽑는지까지 숫자가 말해 준다.
    0이면 그 전형으로는 안 뽑으므로 그 전형에 안 내놓는다.
    """
    hdr_units = {}
    for nm, v in (ucounts or {}).items():
        for h, n in ((v or {}).get("by") or {}).items():
            try:
                n = float(n)
            except (TypeError, ValueError):
                continue
            if n > 0:
                hdr_units.setdefault(h, []).append(nm)
    out = []
    for h in sorted(hdr_units):
        nm = _hdr_name(h)
        if not nm or len(nm) > 40:
            continue
        if _su_cat_like(nm) != cat:
            continue
        out.append({"name": nm, "count_hdr": [h],
                    "units": sorted(hdr_units[h]), "src": "모집인원표"})
    #  하나뿐이면 나눌 것이 없다
    return out if len(out) >= 2 else []


def _subtracks_from_sections(auto, cat):
    """요강의 전형 절 제목에서 세부 전형을 만든다.

    어느 학과를 뽑는지는 절 제목만으로 못 가린다(서울대는 모집단위표가
    앞쪽에 통째로 있다). 그래서 학과는 전부 담고 **최저만** 절별로
    갈라 붙인다 — 그게 유형으로 묶여 있던 것의 가장 큰 문제였다.
    """
    scope = auto.get("su_scope") or {}
    #  최저가 갈리지 않으면 나눌 이유가 없다
    trs = set()
    for key in ("scoped", "none"):
        for r in (scope.get(key) or []):
            if r.get("category") == cat and not r.get("narrow"):
                t = (r.get("track") or "").strip()
                if t:
                    trs.add(t)
    if len(trs) < 2:
        return []
    out, seen = [], set()
    for sec in (scope.get("sections") or []):
        if sec.get("category") != cat:
            continue
        #  완화로 겨우 찾은 절로는 나누지 않는다. 요강이 번호를 붙여
        #  뚜렷이 나눠 적은 절만 근거가 된다 — 그러지 않으면 사람이
        #  읽어 적어 둔 값이 밀려난다(충북대·충남대·경희대 학과 115개가
        #  느슨해졌다 — 실측).
        if sec.get("loose"):
            continue
        nm = (sec.get("track") or "").strip()
        if not nm or nm in seen or nm not in trs:
            continue
        seen.add(nm)
        out.append({"name": nm, "page": sec.get("page"), "src": "요강 절"})
    #  최저 기준 줄의 이름은 전형 이름이 아닐 수 있다('학교추천,
    #  학업우수' 는 그 최저가 걸리는 전형 둘을 적은 것이다). 전형은
    #  절 제목과 모집인원표에서만 만든다.
    return out if len(out) >= 2 else []


def _su_cat_like(name):
    """전형 이름 → 유형. autoparse._su_cat_of 와 같은 규칙."""
    t = re.sub(r"\s+", "", name or "")
    if re.search(r"정시|수능위주|수능/|수능100", t):
        return "정시"
    if re.search(r"학생부\(?교과|교과전형|교과성적|교과우수|교과정성"
                 r"|고교추천|학교추천|교과일반|교과지역", t):
        return "교과"
    if re.search(r"학생부\(?종합|종합전형|학업우수|계열적합|활동우수"
                 r"|자기추천|탐구형|융합형|성장형|서류형|면접형", t):
        return "종합"
    if re.search(r"논술", t):
        return "논술"
    if re.search(r"실기|실적|특기자", t):
        return "실기"
    return ""


def _curated_subtracks(curated, cat):
    """이 전형유형이 세부 전형으로 나뉘는지 본다. 없으면 None.

    형식:
      "cats": {"교과": {"tracks": [
          {"name": "지역균형",            # 화면에 나올 전형 이름
           "rules": [...], "all": {...},  # 이 전형의 최저 규칙
           "units": [...], "colleges": [...],   # 이 전형이 뽑는 모집단위
           "exclude_units": [...],
           "count_hdr": ["지역균형"]},    # 모집인원 표 머리글 낱말
          ...]}}
    """
    cs = (curated or {}).get("_suneung") or {}
    node = (cs.get("cats") or {}).get(cat) or {}
    tks = node.get("tracks")
    return tks if isinstance(tks, list) and tks else None


def _subtrack_takes(ent, unit_name, college):
    """이 세부 전형이 이 모집단위를 뽑는가.

    units/colleges 를 하나도 안 적으면 '전 모집단위' 로 본다. 적었으면
    거기 든 것만 — 뽑지 않는 학과에 그 전형 기준을 걸면 틀린 정보가 된다.
    """
    ex = ent.get("exclude_units") or []
    if unit_name in ex:
        return False
    us, cols = ent.get("units"), ent.get("colleges")
    if not us and not cols:
        return True
    if us and unit_name in us:
        return True
    if cols and college and college in cols:
        return True
    #  표 이름에는 ★·가운뎃점이 붙어 있어서 글자 그대로 견주면
    #  대부분 놓친다. 정규화해서 한 번 더 본다.
    nk = _norm_unit(unit_name)
    if nk:
        if any(_norm_unit(e) == nk for e in ex):
            return False
        if us and any(_norm_unit(u) == nk for u in us):
            return True
        bk = _base_unit(unit_name)
        if us and bk and any(_base_unit(u) == bk for u in us):
            return True
    return False


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
    #  **이름 낱말 또는 유형**으로 모은다. 차례로 보면, 이름으로 걸린
    #  것이 하나라도 있을 때 유형으로 찾는 갈래로 못 간다 — 그 하나가
    #  좁은 전형이면 후보가 비어 자리표시자가 나간다(가천대 교과에
    #  '학생부우수자 교과 100%' 가 있는데 '농어촌(교과)' 만 걸렸다).
    cands = [(k, v) for k, v in (tmethods or {}).items()
             if (any(w in k for w in words) or v.get("cat") == cat)
             and v.get("confidence") != "low"]
    if not cands:
        #  이름 낱말로는 못 찾는 전형이 있다 — 고려대(세종) '크림슨인재',
        #  '미래인재' 에는 '종합' 이라는 낱말이 없다. 그런데 요강 절
        #  제목이 '학생부종합(크림슨인재전형)' 이라고 스스로 말해 준다.
        #  파서가 그때 실어 보낸 유형을 쓴다.
        cands = [(k, v) for k, v in (tmethods or {}).items()
                 if v.get("cat") == cat and v.get("confidence") != "low"]
    #  **좁은 전형만 남았으면 대표값을 만들지 않는다.** `_rank` 로 뒤로
    #  밀어도 하나뿐이면 그것이 뽑힌다 — 공주대 종합의 유일한 후보가
    #  '특성화고교졸업자전형 서류 100' 이어서, 일반 학생이 그 비율로
    #  계산됐다(요강은 서류 70 + 면접 30 — 실측).
    if cands and all(_SUB_NARROW.search(k) for k, _v in cands):
        cands = []
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
    def _rank(kv):
        """유형 대표값 고르는 순서.

        전에는 **합이 큰 것**이 이겼다. 점으로 적은 표는 총점이 100 을
        넘으므로 늘 이기고, 좁은 전형이 유형 전체의 대표가 됐다 —
        충남대 교과가 국가안보교과전형의 '1단계 100점 + 면접 20점'
        (합 120)을 받아 일반 학생이 남의 비율로 계산됐다(실측).
        """
        k, v = kv
        el = v.get("elements") or {}
        tot = sum(x for x in el.values() if isinstance(x, (int, float)))
        #  비율로 적고 합이 100 인 것이 가장 믿을 만하다
        pct100 = (v.get("unit") == "%" and 98 <= tot <= 102)
        return (v.get("confidence") != "high",
                bool(_SUB_NARROW.search(k)),
                not pct100,
                -len(el),
                k)

    cands.sort(key=_rank)
    return _criteria_of(cands[0][0], cands[0][1], gyoinfo, cat)


def _criteria_of(name, info, gyoinfo, cat):
    """추출 항목 하나 → (method, gyogwa). 근거를 값 안에 함께 넣는다."""
    method = dict(info.get("elements") or {})
    if not method:
        return None, None
    #  요강이 '점' 으로 적은 전형요소는 %로 말하면 안 된다.
    #  충북대는 '학생부교과 80점' 이라고 적는다 — 80점 만점 전형요소다.
    if info.get("unit") == "점":
        method["_unit"] = "점"
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


def _subtrack_criteria(tmethods, gyoinfo, cat, name):
    """**이 세부 전형 절**에서 읽은 전형요소. 이름이 딱 맞아야 쓴다.

    유형 공통값보다 정확하다 — 요강이 그 절에 적어 둔 값이다.
    이름이 어긋나면 (None, None) 을 내고 공통값으로 물러난다.
    """
    if not name:
        return None, None
    want = re.sub(r"\s+", "", name)[:40]
    for k, v in (tmethods or {}).items():
        if v.get("confidence") == "low":
            continue
        if re.sub(r"\s+", "", k)[:40] != want:
            continue
        return _criteria_of(k, v, gyoinfo, cat)
    return None, None


#  모집인원 표의 줄이지만 모집단위가 아닌 것 — 안내·묶음 이름이다
_GRID_NOTUNIT = re.compile(r"전공\s*예약|합\s*계|소\s*계|총\s*계|^계$"
                           r"|모집\s*단위|정원\s*내|정원\s*외|비고|참고")


def _count_index(ucounts):
    """모집인원 표의 학과 이름을 정규화해 색인한다.

    표 이름에는 ★·공백·가운뎃점 종류가 제각각 붙어 있어서 글자 그대로
    찾으면 대부분 놓친다. 원래 이름 > 정규화 이름 > 괄호 뗀 이름 순으로
    담되, 먼저 담긴 것을 덮어쓰지 않는다(정확한 쪽을 우선).
    """
    idx = {}
    for k, v in (ucounts or {}).items():
        idx.setdefault(k, v)
    for k, v in (ucounts or {}).items():
        n = _norm_unit(k)
        if n:
            idx.setdefault(n, v)
    for k, v in (ucounts or {}).items():
        b = _base_unit(k)
        if b:
            idx.setdefault(b, v)
    return idx


def _count_total(ucounts, unit_name):
    """요강 모집인원 표의 **총계**(전형 구분 없음). 없으면 None.

    전형별 열이 없는 학과가 966개다. 총계를 '이 전형 정원' 으로 쓰면
    과장이지만(중앙대 약학부 총계 20 · 지역균형 10), 총계라고 밝혀서
    보여주면 학생이 규모를 가늠할 수 있다.
    """
    rec = (ucounts or {}).get(unit_name)
    if rec is None:
        for key in (_norm_unit(unit_name), _base_unit(unit_name)):
            if key and key in ucounts:
                rec = ucounts[key]
                break
    if not rec:
        return None
    t = rec.get("total")
    return t if isinstance(t, int) else None


def _count_for(ucounts, unit_name, cat, fallback, words=None):
    """이 학과의 **이 전형** 모집인원을 표 격자에서 찾는다.

    앱은 결과를 전형별로 보여주므로, '정원'도 그 전형의 모집인원이어야 한다.
    (요강 한 학과에는 입학정원 / 전형별 / 합계가 다 적혀 있어서
     텍스트에서 첫 숫자를 집으면 엉뚱한 값이 들어간다)

    같은 카테고리 안에 세부 전형이 여럿이면(고교추천·지역인재 …) 합산한다.
    못 찾으면 fallback(기존 값)을 그대로 둔다 — **추측해서 채우지 않는다.**
    """
    rec = (ucounts or {}).get(unit_name)
    if rec is None:
        #  이름 그대로 없으면 정규화해서 다시 찾는다
        for key in (_norm_unit(unit_name), _base_unit(unit_name)):
            if key and key in ucounts:
                rec = ucounts[key]
                break
    if not rec:
        return fallback
    by = rec.get("by") or {}
    words = words or _CAT_HDR_WORDS.get(cat)
    if by and words:
        vals = [v for h, v in by.items() if any(w in h for w in words)]
        if vals:
            return sum(vals)
    return fallback


def convert_auto(auto):
    """auto 추출 JSON → 엔진 호환 대학 dict (학과 중심)."""
    src_file = auto.get("file")
    idx = _rule_index(auto)
    su_none = _su_none_cats(auto)
    cats = list(auto.get("categories_detected", []) or [])
    # 표에서 읽은 모집인원 격자 {학과: {"total":n, "by":{전형머리글:n}}}
    #  이름이 ★·공백·가운뎃점 때문에 안 맞는 일이 많아 정규화 색인을 쓴다
    ucounts = _count_index(auto.get("unit_counts") or {})
    # 요강에서 읽은 전형방법(근거 쪽·원문 포함) / 반영교과
    tmethods = auto.get("track_methods") or {}
    gyoinfo = auto.get("gyogwa_info") or None
    # 사람/AI 가 요강을 읽어서 채운 값 — 파서 결과보다 우선
    curated = auto.get("curated") or {}

    # 요강을 열어 확인한 '모집단위가 아닌 이름' — 계열 묶음·인증 표기·
    # 줄바꿈에 잘린 이름. 있지도 않은 학과를 학생에게 보여주지 않는다.
    drop = set(curated.get("_drop_units") or [])

    # 캐노니컬 학과 목록 (모집인원 표) — 이름 기준 dedup, 정원/페이지 유지
    all_units = {}
    for u in auto.get("units_detected", []):
        nm = u["unit"]
        if nm in drop:
            continue
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

    #  이름 표기가 표와 본문에서 조금씩 다르다(★·공백·가운뎃점 종류).
    _units_by_norm = {}
    for nm2, b2 in all_units.items():
        for key in (_norm_unit(nm2), _base_unit(nm2)):
            if key:
                _units_by_norm.setdefault(key, b2)

    #  **모집인원 표에만 있는 학과를 더한다.** 학과 목록은 본문 글에서
    #  만드는데, 표에만 적힌 학과가 62개(13대학) 있었다 — 이화 성악과·
    #  관현악과, 충남대 음악과·회화과, 한국외대 독일어과, 한국체대
    #  공연예술학과 발레… 어느 전형에도 안 나와 학생이 찾을 수 없었다.
    #  표는 숫자가 적힌 으뜸 근거다.
    _colmap = auto.get("unit_colleges") or {}
    for cnm in sorted((auto.get("unit_counts") or {})):
        if cnm in drop or _GRID_NOTUNIT.search(cnm):
            continue
        nk, bk = _norm_unit(cnm), _base_unit(cnm)
        if not nk or nk in _units_by_norm or bk in _units_by_norm:
            continue
        _col = _colmap.get(cnm) or ""
        _tot = ((auto.get("unit_counts") or {}).get(cnm) or {}).get("total")
        all_units[cnm] = {
            "unit": cnm, "college": _col or None, "campus": None,
            "gyeyeol": _guess_gyeyeol(cnm, _col),
            "count": _tot if isinstance(_tot, int) else None,
            "unit_page": None, "cats": set(), "from_counts": True,
        }
        for key in (nk, bk):
            if key:
                _units_by_norm.setdefault(key, all_units[cnm])

    #  모집인원 표가 **어느 전형으로 뽑는지 숫자로** 말한다. 본문 글에는
    #  칼럼이 없어 그걸 알 수 없는 요강이 많다 — 아주대 논술은 본문으로
    #  1학과인데 표에는 34학과다(실측). 논술·실기는 학과가 검출되지
    #  않으면 목록에서 빠지므로, 학생이 갈 수 있는 곳을 못 본다.
    #
    #  값이 **1명 이상**인 열만 센다. 0 이나 '-' 는 그 전형으로 안
    #  뽑는다는 뜻이고, 그게 이 표를 쓰는 이유다.
    for cnm, rec in (auto.get("unit_counts") or {}).items():
        base = all_units.get(cnm)
        if base is None:
            for key in (_norm_unit(cnm), _base_unit(cnm)):
                if key:
                    base = _units_by_norm.get(key)
                    if base is not None:
                        break
        if base is None:
            continue
        for hdr, n in ((rec or {}).get("by") or {}).items():
            if not isinstance(n, int) or n < 1:
                continue
            c = _su_cat_like(re.sub(r"#\d+$", "", hdr))
            if c and c != "정시":
                base["cats"].add(c)
                #  표에서 온 것만 따로 — '실기로만 뽑는가' 를 가리는
                #  근거는 표여야 한다. 본문에서 온 유형과 섞으면 안 된다.
                base.setdefault("grid_cats", set()).add(c)

    #  **유형 목록에 모집인원 표가 말하는 유형을 더한다.**
    #  `categories_detected` 는 본문 글에서 만든다. 성균관대는 거기에
    #  논술이 없어서(표에는 논술위주 24학과, 최저 규칙도 전형요소도
    #  있는데) 논술 전형이 아예 안 만들어졌다 — 학생이 볼 수 없었다.
    #  표는 숫자로 말하므로 더 센 근거다.
    for _b in all_units.values():
        for _c in (_b.get("grid_cats") or ()):
            if _c not in cats:
                cats.append(_c)

    # 입결(합격컷) 색인 — 학과명 기준
    ipg = {ip["unit"]: ip for ip in auto.get("ipgyeol_detected", [])}

    tracks = []

    all_idx = idx.get("__ALL__")

    def _build_units(cat, cat_idx, fb, sub=None):
        """이 전형(cat) 또는 그 안의 세부 전형(sub)의 학과 목록을 만든다."""
        out = []
        for nm, base in all_units.items():
            gye = base["gyeyeol"]
            college = base.get("college") or ""
            if sub is not None and not _subtrack_takes(sub, nm, college):
                continue
            #  **표가 '실기로만 뽑는다' 고 말한 학과는 교과·종합에
            #  내놓지 않는다.** 교과·종합은 학과를 전부 담는 설계라서,
            #  실기 전용 학과가 거기 나와 '갈 수 있다' 로 읽혔다
            #  (이화 성악과·관현악과, 충남대 음악과·회화과 — 실측).
            #
            #  거꾸로는 하지 않는다 — 교과 열에만 값이 있는 학과를
            #  종합에서 빼면, 표의 종합 열을 못 읽은 대학에서 갈 수
            #  있는 곳을 못 보게 된다(충남대가 그렇다).
            if cat not in SELECTIVE and (base.get("grid_cats") or set()) \
                    == {"실기"}:
                continue
            info, kind = _match_rule(cat_idx, nm, gye, college, all_idx=fb)
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
            #  요강이 '최저 없음' 이라고 적은 것이 있으면 **근거로** 붙인다.
            #  주장하지 않는 이유는 `_su_none_cats` 주석에 있다. 규칙을
            #  못 찾았을 때만 바꾼다 — 찾은 규칙은 건드리지 않는다.
            nrows = su_none.get(cat)
            #  학과마다 기준이 갈리는 유형은 '없음' 도 붙이지 않는다.
            #  대표값을 안 쓰기로 한 자리에 '없음' 이 들어오면 최저가
            #  있는 학과를 없다고 말한다(충남대 교과 49학과 — 실측).
            #  진짜 미확인으로 두어 학생이 요강을 보게 한다.
            if (cat_idx or {}).get("no_common"):
                nrows = None
            #  요강이 '모든 모집단위에서 없음' 이라고 **범위를 명시**한
            #  경우는 규칙을 찾았어도 주장한다. 건국대(글로컬)은
            #  '의예과를 제외한 모든 모집단위에서 수능최저 없음' 이라고
            #  적는데, 지금은 대표값 규칙이 이겨서 교과 41학과 중
            #  40학과가 있어선 안 되는 '3개 합 6' 을 받았다(실측).
            #
            #  이름이 박힌 규칙(의예과)은 그대로 둔다 — 그게 요강이
            #  말한 예외다.
            if nrows and info is not None and kind == "전형공통":
                #  **예외가 명시된 것만** 주장한다. `all_units` 만으로는
                #  안 된다 — '미적용' 이라는 말에 범위가 없는데 zone
                #  전체에서 '전 모집단위' 를 주워 온 경우가 있고, 그때
                #  좁은 전형의 '없음' 이 유형 전체에 퍼진다
                #  (충남대 교과 49학과 — 실측. 충남대 교과에는 최저가 있다)
                claim = [r for r in nrows
                         if r.get("all_units") and r.get("exclude_units")
                         and not _excluded(
                             {"exclude": r.get("exclude_units") or []}, nm)]
                if claim:
                    info, kind = None, "요강근거"
                    nrows = claim
            if nrows and info is None:
                rule = {"type": "none", "label": _su_none_label(nrows)}
                kind = "요강근거"
                rpage = nrows[0].get("page")
                rsrc = "요강 " + (nrows[0].get("src") or "")
                rsent = nrows[0].get("text")
            # 읽어서 채운 최저가 있으면 그것이 최우선(원문 첨부 필수).
            # 세부 전형이면 **그 전형의 규칙만** 본다 — 다른 세부 전형의
            # 기준을 끌어오면 애초에 나눈 이유가 없어진다.
            _campus = base.get("campus") or ""
            if sub is not None and ((sub.get("rules") or sub.get("all"))):
                #  사람이 **이 세부 전형에** 적어 뒀으면 그것만 쓴다 —
                #  다른 세부 전형의 기준을 끌어오면 나눈 뜻이 없어진다.
                crule, csrc = _curated_pick([sub], nm, college, _campus)
            else:
                #  세부 전형에 적힌 것이 없으면 **유형 값**을 쓴다.
                #  그건 남의 세부 전형 것이 아니라 그 유형에 대한 사람의
                #  답이다. 버리면 공주대 교과 91학과가 미확인이 된다
                #  (모집인원 표의 전형 열을 읽어 세부 전형이 생기자
                #   사람이 채운 108건이 통째로 떨어졌다 — 실측).
                crule, csrc = _curated_suneung(curated, cat, nm, college,
                                               _campus)
            if crule:
                rule, kind = crule, "요강확인"
                rpage = csrc.get("page")
                rsrc = "요강 직접확인"
                rsent = csrc.get("text")
            #  0명 모집은 지원할 수 없다. 보여주면 학생이 헛되게 검토한다.
            #  (아주대 스포츠레저학과 — 수시는 안 뽑고 실기로만 뽑는다.
            #   5,480 학과 중 2건이라 좁게 걸러도 잃는 게 없다)
            _cnt = _count_for(ucounts, nm, cat, base["count"],
                              words=(sub or {}).get("count_hdr"))
            if isinstance(_cnt, (int, float)) and _cnt <= 0:
                continue
            ipinfo = ipg.get(nm)
            out.append({
                "unit": nm, "college": base["college"],
                "campus": base.get("campus"), "gyeyeol": gye,
                "count": _cnt,
                #  이 전형 정원을 못 찾았을 때 쓸 '표의 총계'(전형 구분 없음)
                "count_total": _count_total(ucounts, nm),
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
        return out

    if all_units:  # 학과 중심 구성
        for cat in cats:
            cat_idx = idx.get(cat)
            # 교과·종합만 타전형 최저 폴백 허용(논술·실기는 고유 최저라 폴백 배제)
            fb = all_idx if cat not in SELECTIVE else None

            # ── 세부 전형이 선언된 유형은 트랙을 나눠서 낸다 ──────────
            subs = _curated_subtracks(curated, cat)
            #  사람이 적어 준 것이 없으면 파서가 만든 것을 쓴다
            auto_sub = False
            if not subs:
                subs = _auto_subtracks(auto, cat,
                                       auto.get("unit_counts") or {})
                auto_sub = bool(subs)
            if subs:
                cur_m, cur_g = _curated_criteria(curated, cat)
                par_m, par_g = _track_criteria(tmethods, gyoinfo, cat)
                real_m, real_g = (cur_m or par_m), (cur_g or par_g)
                if not real_m and cat == "교과":
                    real_m = {"교과": 100, "placeholder": True}
                    real_g = real_g or {"subjects": ["국어", "수학", "영어",
                                                     "사회", "과학"],
                                        "placeholder": True}
                for i, sub in enumerate(subs):
                    #  이 세부 전형의 최저만 보는 색인이 있으면 그것을
                    #  쓴다. 없으면 유형 공통 색인으로 물러난다.
                    sidx = ((cat_idx or {}).get("by_track") or {}).get(
                        sub.get("name")) or cat_idx
                    su = _build_units(cat, sidx, fb, sub=sub)
                    if not su:
                        continue
                    #  전형요소·반영교과도 세부 전형마다 다를 수 있다
                    #  (연세대 미래는 교과우수자 일반형/추천형/기회균형이
                    #   각각 다른 방법으로 뽑는다). 트랙에 적혀 있으면
                    #  그것을 쓰고, 없으면 유형 공통값을 쓴다.
                    #  이 절에서 읽은 전형요소가 있으면 그것이 맞다.
                    #  (사람이 읽어 채운 값은 그대로 우선한다)
                    sub_m, sub_g = _subtrack_criteria(
                        tmethods, gyoinfo, cat, sub.get("name"))
                    tracks.append({
                        "id": "auto_%s_%d" % (cat, i),
                        "name": sub.get("name") or ("%s전형" % cat),
                        "category": cat,
                        "method": (sub.get("method") or cur_m or sub_m
                                   or par_m or real_m or {}),
                        "gyogwa": (sub.get("gyogwa") or cur_g or sub_g
                                   or par_g or real_g),
                        "auto": True, "units": su,
                        #  파서가 나눈 것인지 사람이 적어 준 것인지
                        "sub_src": sub.get("src") if auto_sub else None,
                        #  일반 학생과 무관한 전형 — 화면에서 접어 둔다
                        "narrow": bool(sub.get("narrow")),
                    })
                continue

            units = _build_units(cat, cat_idx, fb)
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

    #  평가 세부사항은 전형 유형별로 하나씩 붙인다.
    #  트랙을 만드는 자리가 네 군데라 여기서 한 번에 얹는다.
    #  한 유형 안에서 최저가 갈리면 그 사실을 트랙에 적어 둔다
    #  나뉜 유형은 각 전형이 자기 최저를 갖는다 — 안내가 필요 없다.
    _split = {t.get("category") for t in tracks if t.get("sub_src")}
    for _t in tracks:
        if _t.get("category") in _split:
            continue
        _n = _su_split_note(auto, _t.get("category"))
        if _n:
            _t["su_note"] = _n

    evals = auto.get("evaluation") or {}
    ties = auto.get("tiebreak") or {}
    #  학교폭력 반영과 면접 안내는 대학 공통이라 모든 전형에 같이 붙인다.
    #  (요강도 전형별로 나눠 적지 않고 공통사항으로 한 번 적는다)
    vio = auto.get("violence") or {}
    itv = auto.get("interview") or {}
    if evals or ties or vio or itv:
        for tr in tracks:
            ev = evals.get(tr.get("category"))
            if ev:
                tr["evaluation"] = ev
            tb = ties.get(tr.get("category"))
            if tb:
                tr["tiebreak"] = tb
            if vio:
                tr["violence"] = vio
            if itv:
                tr["interview"] = itv
    #  등급환산표·성취도 환산 — 내신 계산의 근간이다.
    #
    #  **반영교과가 실제값일 때만 계산에 넣는다.** 반영교과가 자리표시자인데
    #  환산표만 붙이면, 엔진이 '대학 반영기준으로 계산했다' 는 판정을 내면서
    #  실제로는 짐작한 교과를 쓴다. 판정 근거가 거짓이 된다.
    #  그래서 자리표시자일 때는 `grade_scale` 로 따로 두어 **보여주기만** 한다.
    scales = auto.get("grade_scale") or {}
    if scales:
        def _pick(cat, name):
            for k, v in scales.items():
                if k == "공통":
                    continue
                kk = re.sub(r"\s+", "", k)
                if cat and cat in kk:
                    return v
                if name and re.sub(r"\s+", "", name) in kk:
                    return v
            return scales.get("공통")

        for tr in tracks:
            sc = _pick(tr.get("category"), tr.get("name"))
            if not sc or not sc.get("scale"):
                continue
            g = tr.get("gyogwa")
            real = isinstance(g, dict) and g and not g.get("placeholder")
            if real:
                g.setdefault("scale", sc["scale"])
                if sc.get("ach"):
                    g.setdefault("ach_scale", sc["ach"])
                g.setdefault("_scale_source",
                             {k: sc.get(k) for k in
                              ("page", "printed_page", "section")})
            else:
                tr["grade_scale"] = sc


    #  모집단위별 인재상·핵심교과는 **학과마다** 다르므로 학과에 붙인다.
    #  이름이 요강 표기와 조금씩 다르므로(★·공백·가운뎃점) 정규화 색인을
    #  쓴다 — 정원 매칭에서 이미 겪은 문제다(§6-21).
    prof = auto.get("unit_profile") or {}
    inja, focus = prof.get("injaesang") or {}, prof.get("gyogwa_focus") or {}
    if inja or focus:
        psrc = prof.get("_source") or {}
        ix_i, ix_f = {}, {}
        for src, ix in ((inja, ix_i), (focus, ix_f)):
            for k, v in src.items():
                for key in (k, _norm_unit(k), _base_unit(k)):
                    if key:
                        ix.setdefault(key, v)
        for tr in tracks:
            for u in tr.get("units", []):
                nm = u.get("unit") or ""
                for key in (nm, _norm_unit(nm), _base_unit(nm)):
                    if key in ix_i and "injaesang" not in u:
                        u["injaesang"] = ix_i[key]
                    if key in ix_f and "gyogwa_focus" not in u:
                        u["gyogwa_focus"] = ix_f[key]
                if ("injaesang" in u or "gyogwa_focus" in u) and psrc:
                    u["profile_source"] = psrc

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
