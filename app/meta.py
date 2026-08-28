"""meta.py — 학년도 자동 인식 등 메타 유틸."""
import os, re, glob, json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw_text")


def _filename_for(code):
    idx = os.path.join(BASE, "data", "raw_index.json")
    if os.path.exists(idx):
        with open(idx, encoding="utf-8") as f:
            d = json.load(f)
        if code in d:
            return d[code].get("file", "")
    return ""


def detect_year(text, fallback=None):
    """'2027학년도' 등에서 학년도(int) 추출. 없으면 fallback."""
    if not text:
        return fallback
    m = re.search(r"(20\d{2})\s*학년도", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(20\d{2})", text)
    return int(m.group(1)) if m else fallback


def year_for_code(code, name_hint=""):
    """raw_text 앞부분 + 파일명에서 학년도 추정."""
    fname = name_hint or _filename_for(code)
    # 파일명의 '2027학년도'를 최우선
    y = detect_year(fname)
    if y:
        return y
    p = os.path.join(RAW, f"{code}.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            txt = f.read(30000)
        y = detect_year(txt)
    return y


def get_admission_guide(univ_name, category, track_name, rule_sentence, gyogwa_detail=""):
    """각 대학/전형별 선발 방식 요약 및 수험생 필수 체크리스트 생성."""
    cat = category or "교과"
    tr = track_name or f"{cat}전형"
    
    # 1. 선발 방식 요약
    if "정시" in cat or "수능" in cat:
        method = "수능 성적(백분위/표준점수) 중심 선발 (수능 100% 또는 실기/면접 병행)"
    elif "논술" in cat:
        method = "논술고사 성적 중심 + 학생부 교과/비교과 반영"
    elif "실기" in cat or "실적" in cat:
        method = "실기/면접 고사 성적 + 학생부 교과 반영"
    elif "종합" in cat:
        if any(kw in tr for kw in ["면접", "DoDream", "활동우수", "미래"]):
            method = "1단계: 학생부 서류평가 100% → 2단계: 1단계 성적 + 면접 평가"
        else:
            method = "학생부 서류평가 100% (정성평가, 면접 없음/서류형)"
    else:  # 교과
        if any(kw in tr for kw in ["추천", "학교장"]):
            method = "학생부 교과 성적 100% 정량 반영 (고교별 학교장 추천 필요)"
        elif "면접" in tr:
            method = "1단계: 학생부 교과 100% → 2단계: 교과 성적 + 면접 평가"
        else:
            method = "학생부 교과 성적 100% 정량 선발 (환산등급/환산점수 산출)"

    # 2. 수능최저 요약
    if rule_sentence and "미적용" not in rule_sentence and "정보 없음" not in rule_sentence:
        suneung_summary = f"⚠️ 수능최저 충족 필수: {rule_sentence}"
    else:
        suneung_summary = "✅ 수능최저 기준 없음 (내신 및 전형 요소에만 집중 가능)"

    # 3. 챙겨야 할 핵심 준비사항 (수험생 체크포인트)
    checkpoints = []
    if any(kw in tr for kw in ["추천", "학교장", "지역균형"]):
        checkpoints.append("소속 고등학교 '학교장 추천' 사전 인원 확인 및 명단 등록")
    if "면접" in tr or ("종합" in cat and "서류" not in tr):
        checkpoints.append("제시문/학생부 기반 면접 대비 (지원동기, 활동경험, 전공지식)")
    if "논술" in cat:
        checkpoints.append("대학별 수시 논술 기출문제 풀이 및 시험 시간 배분 훈련")
    if "수능" in suneung_summary and "⚠️" in suneung_summary:
        checkpoints.append("수능 필수 응시 영역 및 탐구 반영 과목수/선택과목 필수조건 준수")
    if "종합" in cat:
        checkpoints.append("학생부 세부능력및특기사항(세특) 및 진로 역량 기재 내용 점검")
    if not checkpoints:
        checkpoints.append("모집요강 상의 전형 일정(원서접수, 합격자발표, 문서등록) 숙지")

    return {
        "method": method,
        "suneung": suneung_summary,
        "checkpoints": checkpoints
    }


if __name__ == "__main__":
    for f in sorted(glob.glob(os.path.join(RAW, "*.txt"))):
        code = os.path.splitext(os.path.basename(f))[0]
        print(code, year_for_code(code))
