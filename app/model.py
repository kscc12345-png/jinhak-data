"""
model.py — 데이터 스키마 및 로더.

대학별 정제 데이터(jinhak/data/universities/{code}.json) 구조
--------------------------------------------------------------
{
  "code": "chungbuk",
  "name": "충북대학교",
  "region": "충북 청주",
  "type": "국립",
  "tracks": [                      # 전형 목록
    {
      "id": "gyogwa_ilban",
      "name": "학생부교과(일반전형)",
      "category": "교과",          # 교과 | 종합 | 논술 | 실기 | 실적
      "method": {                  # 전형방법(요소별 반영비율, 합계 100)
        "교과": 100, "서류": 0, "면접": 0, "논술": 0, "실기": 0, "수능": 0
      },
      "gyogwa": {                  # 교과 성적 산출 규칙 (교과 반영 시)
        "subjects": ["국어","영어","수학","사회","과학"],
        "scale": {"1":1.0,"2":0.99,...},   # 등급 -> 반영률(만점대비) 또는 점수
        "note": "..."
      },
      "suneung_min": { ... 또는 null },     # 아래 SuneungRule 참조
      "units": [                   # 이 전형으로 뽑는 모집단위(학과)
        {"unit":"수학과","gyeyeol":"자연","count":7,"suneung_group":"자연_수학"}
      ],
      "schedule": {"원서접수":"...","합격발표":"..."}
    }
  ],
  "suneung_groups": {              # 모집단위 그룹별 수능최저 (전형이 공유)
    "인문": {"type":"sum_top_n","n":2,"max":8, ...},
    ...
  }
}

수능최저 규칙(SuneungRule) 표현
--------------------------------
{
  "type": "sum_top_n" | "each_max" | "count_le" | "none",
  "n": 2,                    # 반영 영역 수
  "max": 8,                  # 등급 합(또는 각 등급) 상한
  "pool": ["국어","수학","영어","탐구"],   # 선택 가능 영역
  "required": ["수학"],      # 반드시 포함해야 하는 영역(있으면)
  "math_restrict": ["미적분","기하"] 또는 null,
  "tamgu": "best1" | "avg2", # 탐구 반영 방식
  "korea_history": "필수응시",
  "label": "상위 2개 등급 합 8 이내"
}
"""
import json, os, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIV_DIR = os.path.join(BASE, "data", "universities")

AREAS = ["국어", "수학", "영어", "탐구", "한국사"]


def load_all():
    univs = {}
    for f in sorted(glob.glob(os.path.join(UNIV_DIR, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        univs[d["code"]] = d
    return univs


def load_one(code):
    with open(os.path.join(UNIV_DIR, f"{code}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def resolve_suneung(univ, track, unit):
    """모집단위의 수능최저 규칙을 해석해 돌려준다."""
    # 우선순위: unit.suneung_rule(inline) > suneung_group 참조 > track.suneung_min
    if unit and unit.get("suneung_rule"):
        return unit["suneung_rule"]
    if unit and unit.get("suneung_group"):
        grp = univ.get("suneung_groups", {}).get(unit["suneung_group"])
        if grp:
            return grp
    return track.get("suneung_min")
