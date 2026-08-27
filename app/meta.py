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


if __name__ == "__main__":
    for f in sorted(glob.glob(os.path.join(RAW, "*.txt"))):
        code = os.path.splitext(os.path.basename(f))[0]
        print(code, year_for_code(code))
