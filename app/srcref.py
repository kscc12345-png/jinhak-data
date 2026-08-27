# -*- coding: utf-8 -*-
"""srcref.py — 학과 원문(모집요강+어디가) 참조·강조어 산출(관리자/발행 공용)."""
import re

_DOTS = "·・ㆍ•‧∙"   # 가운뎃점 변형들(표/각주에서 서로 다르게 쓰임)


def _footnote_y(page):
    """각주(※) 시작 y. 이 아래 매치는 비고/각주라 강조 제외."""
    fy = page.rect.height
    try:
        for b in page.get_text("blocks"):
            if len(b) >= 5 and "※" in (b[4] or ""):
                fy = min(fy, b[1])
    except Exception:
        pass
    return fy


def search_unit(page, unit_name):
    """페이지에서 학과 위치(fitz.Rect 리스트) 찾기.
    - 가운뎃점 문자 변형 모두 시도
    - 각주(※ 아래) 영역 매치는 제외(비고 잡는 문제 방지)
    - 본표의 최상단 매치 1건 반환"""
    if not unit_name:
        return []
    cands = {unit_name}
    if any(d in unit_name for d in _DOTS):
        for d in _DOTS:
            cands.add(re.sub(f"[{_DOTS}]", d, unit_name))
    # 점 없는 핵심부(예: 'AI·빅데이터학과'→'빅데이터학과')도 후보
    tail = re.split(f"[{_DOTS}]", unit_name)[-1]
    if len(tail) >= 3:
        cands.add(tail)
    fy = _footnote_y(page)
    hits = []
    for v in cands:
        for rc in page.search_for(v):
            if rc.y0 < fy - 2:            # 각주 위(=본표)만
                hits.append(rc)
        if hits:
            break
    hits.sort(key=lambda r: r.y0)         # 최상단(본표 행) 우선
    return hits[:1]


def highlight_terms(r):
    """원문에서 빨간 박스로 강조할 검색어(학과명 + 괄호 제거형)."""
    terms = [r.get("unit")]
    u = re.sub(r"\s*\(.*?\)\s*", "", r.get("unit") or "")
    if u and u != r.get("unit"):
        terms.append(u)
    return [t for t in terms if t]


def unit_sources(r):
    """학과의 원문 참조 목록: [(label, source_file, page, terms)].
    모집요강(정원/최저) + 어디가(수시 대표결과·정시결과)."""
    out = []
    terms = highlight_terms(r)
    sf = r.get("source_file")
    if sf:
        if r.get("unit_page"):
            out.append(("📋 모집요강 · 모집인원(정원)", sf, r["unit_page"], terms))
        if r.get("rule_page"):
            out.append(("📋 모집요강 · 수능최저 근거", sf, r["rule_page"], terms))
    for e in (r.get("eodiga") or []):
        if e.get("page") and e.get("source"):
            out.append((f"🔎 어디가 · {e.get('label') or '수시결과'}", e["source"], e["page"], terms))
            break
    js = r.get("js") or {}
    if js.get("page") and js.get("source"):
        out.append(("🎯 어디가 · 정시 결과", js["source"], js["page"], terms))
    return out
