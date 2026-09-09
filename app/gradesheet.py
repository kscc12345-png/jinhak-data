# -*- coding: utf-8 -*-
"""성적표 그대로 입력 — 학생부·수능 전체 항목을 한 표에서 받는다.

왜 따로 창을 두나
  서랍(성적 입력 및 설정)은 폭이 320px 다. 성적표 한 줄에는 교과·과목·
  단위수·석차등급·원점수·과목평균·표준편차·수강자수·성취도·성취도별
  분포까지 열 칸이 넘게 있다. 서랍에 밀어 넣으면 어느 것도 못 읽는다.
  그래서 서랍은 자주 쓰는 넉 칸만 두고, **성적표를 그대로 옮기는 일**은
  넓은 창에서 한다.

왜 다 받나
  빈 칸을 채우려는 게 아니다. 진로선택 과목에는 석차등급이 없다.
  전에는 성취도 A를 무조건 1.5등급으로 바꿨다 — A를 70% 주는 과목과
  12% 주는 과목의 A가 같은 값이었다. 성취도별 분포와 과목평균·
  표준편차가 있으면 그 A가 실제로 어디쯤인지 계산된다
  (`engine.subject_grade`).

라이트(lite.py)와 관리자(desktop.py)가 같이 쓴다. 두 번 쓰지 않는다.
"""
import re
import tkinter as tk

import customtkinter as ctk


#  ── 교과군 ──────────────────────────────────────────────────────
#
#  왼쪽이 화면에 보이는 말(성적표에 적힌 말), 오른쪽이 대학 반영교과가
#  쓰는 교과군 이름이다(`gyogwa.subject_area`). 학생이 고른 교과군을
#  과목명 추측보다 먼저 믿으므로, 여기가 넓어지면 판정이 정확해진다.
GYOGWA_CHOICES = [
    ("국어", "국어"),
    ("수학", "수학"),
    ("영어", "영어"),
    ("한국사", "한국사"),
    ("사회", "사회"),
    ("과학", "과학"),
    ("체육·예술", "예체능"),
    ("기술·가정/정보", "기술·가정"),
    ("제2외국어", "제2외국어"),
    ("한문", "한문"),
    ("교양", "교양"),
]
GYOGWA_LABELS = [a for a, _ in GYOGWA_CHOICES]
AREA_OF_LABEL = dict(GYOGWA_CHOICES)
LABEL_OF_AREA = {b: a for a, b in GYOGWA_CHOICES}
#  예전 자료 호환 — 서랍에서 '일반/사회/과학' 셋으로만 고를 수 있었다
LABEL_OF_AREA.setdefault("일반", "교양")

#  성적표의 '교과 종류' 칸
#
#  '융합선택' 은 2022 개정 교육과정(2025년 고1~)에서 생긴 유형이다.
#  공통 / 일반선택 / 진로선택 / 융합선택 네 가지가 된다. 미리 넣어 둔다 —
#  없으면 그 과목을 넣을 자리가 없어 학생이 유형을 잘못 고른다.
SUBJ_TYPES = ["일반선택", "진로선택", "융합선택", "공통",
              "과학탐구실험", "전문교과"]

#  학기별로 값이 따로 있는 칸들
#
#  D·E 는 2022 개정의 5단계 성취평가(A~E)용이다. `engine.pct_from_dist`
#  는 이미 A~E 를 다루는데 입력 칸이 셋뿐이어서 적을 수가 없었다.
SEM_FIELDS = ("unit", "grade", "raw", "mean", "sd", "cnt",
              "ach", "dstA", "dstB", "dstC", "dstD", "dstE")

#  (머리글, 필드, 폭, 설명)
COLS = [
    ("교과", "_kind", 78, ""),
    ("유형", "_type", 88, ""),
    ("과목명", "_name", 130, ""),
    ("단위", "unit", 44, "이수단위"),
    ("석차등급", "grade", 56, "1~9"),
    ("원점수", "raw", 52, "0~100"),
    ("과목평균", "mean", 60, "성적표의 과목평균"),
    ("표준편차", "sd", 60, "성적표의 표준편차"),
    ("수강자", "cnt", 52, "수강자수"),
    ("성취도", "ach", 52, "A/B/C (5단계는 A~E)"),
    ("A%", "dstA", 44, "성취도별 분포 A"),
    ("B%", "dstB", 44, "성취도별 분포 B"),
    ("C%", "dstC", 44, "성취도별 분포 C"),
    #  5단계 성취평가(2022 개정)용. 3단계 성적표에서는 비워 둔다.
    ("D%", "dstD", 44, "성취도별 분포 D (5단계)"),
    ("E%", "dstE", 44, "성취도별 분포 E (5단계)"),
]

GUIDE = (
    "성적표에 적힌 대로 옮기면 됩니다. 모르는 칸은 비워 두세요 — "
    "비어 있어도 계산은 됩니다.\n"
    "· 석차등급이 없는 진로선택 과목은 성취도(A/B/C)와 그 옆의 "
    "A/B/C 비율을 넣으면 등급을 추정합니다.\n"
    "· 비율을 모르면 원점수·과목평균·표준편차만으로도 추정합니다. "
    "둘 다 없으면 성취도만으로 대략 잡습니다(참고값).\n"
    "· 어느 방법을 썼는지 맨 오른쪽 '근거' 에 적힙니다."
)


def subject_record(subj, sem):
    """과목 한 줄의 그 학기 값을 `engine.subject_grade` 가 받는 꼴로."""
    def g(f):
        return str((subj.get(f) or {}).get(sem, "") or "").strip()

    dist = {}
    for key, f in (("A", "dstA"), ("B", "dstB"), ("C", "dstC"),
                   ("D", "dstD"), ("E", "dstE")):
        v = g(f)
        if v:
            dist[key] = v
    #  한 칸만 적혀 있으면 비율이 아니다 — 그것만으로는 위치를 못 잡는다
    return {"grade": g("grade"), "ach": g("ach").upper(), "raw": g("raw"),
            "mean": g("mean"), "sd": g("sd"),
            "dist": dist if len(dist) >= 2 else {}}


def blank_subject(sems, kind=None, type_="일반선택", name=""):
    return {"name": name, "fixed": False, "kind": kind, "type": type_,
            "sems": list(sems),
            "grade": {}, "ach": {}, "raw": {}, "unit": {},
            "mean": {}, "sd": {}, "cnt": {},
            "dstA": {}, "dstB": {}, "dstC": {}, "dstD": {}, "dstE": {}}


#  ── 표 붙여넣기 ─────────────────────────────────────────────────
#
#  성적표를 엑셀·한글 표에서 긁어 오면 탭이나 여러 칸 공백으로 갈린다.
#  한 줄씩 받아 우리 칸에 앉힌다. 첫 칸이 교과 이름이면 교과·유형까지
#  적힌 꼴로 보고, 아니면 과목명부터인 꼴로 본다.
_SPLIT = re.compile(r"\t|\s{2,}|\s*\|\s*")
_PASTE_ORDER = ["unit", "grade", "raw", "mean", "sd", "cnt",
                "ach", "dstA", "dstB", "dstC"]


_LETTER = re.compile(r"^[A-Ea-e]$")


def _cells_of(line):
    """한 줄을 칸으로 나눈다.

    탭으로 갈린 줄(엑셀에서 긁은 것)은 **빈 칸을 지우면 안 된다.**
    진로선택 과목은 석차등급이 비어 있는데, 빈 칸을 지우면 뒤 값들이
    한 칸씩 앞으로 밀려 원점수가 석차등급 자리에 앉는다.
    """
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in _SPLIT.split(line.strip()) if c.strip()]


def parse_paste(text):
    """붙여넣은 표 → [{kind, type, name, 값들}] 목록."""
    out = []
    areas = set(AREA_OF_LABEL.values())
    for line in (text or "").splitlines():
        cells = _cells_of(line)
        while cells and not cells[-1]:
            cells.pop()
        if len([c for c in cells if c]) < 2:
            continue
        kind = type_ = None
        if cells[0] in GYOGWA_LABELS or cells[0] in areas:
            kind = AREA_OF_LABEL.get(cells[0], cells[0])
            cells = cells[1:]
        elif len(cells) > 1 and cells[1] in SUBJ_TYPES:
            #  전문교과 계열 이름(건설·전기 등)은 우리 교과군에 없다.
            #  뒤에 유형이 붙어 있으면 그 칸이 교과 자리인 것은 확실하다.
            cells = cells[1:]
        if cells and cells[0] in SUBJ_TYPES:
            type_ = cells[0]
            cells = cells[1:]
        if not cells:
            continue
        #  머리글 줄은 건너뛴다
        if cells[0] in ("과목", "과목명", "교과", "교과목", "번호"):
            continue
        #  번호가 앞에 붙어 있으면 떼어 낸다 ("1  문학  4  2 …")
        if cells[0].isdigit() and len(cells) > 2:
            cells = cells[1:]
        #  칸 수는 표마다 다르다. 진로선택 줄은 석차등급이 비어 있고,
        #  원점수·평균·편차를 아예 안 적은 표도 있다. 자리만 세면 값이
        #  한 칸씩 밀린다.
        #
        #  성취도는 이 줄에서 **유일하게 글자**다. 그것을 기둥으로 삼아
        #  앞은 숫자 칸들, 뒤는 성취도별 비율로 가른다.
        vals = cells[1:]
        ai = next((i for i, v in enumerate(vals)
                   if _LETTER.match(v or "")), None)
        if ai is None:
            head, ach, tail = vals, "", []
        else:
            head, ach, tail = vals[:ai], vals[ai], vals[ai + 1:]
        row = {"kind": kind, "type": type_ or "일반선택", "name": cells[0]}
        for f, v in zip(("unit", "grade", "raw", "mean", "sd", "cnt"), head):
            if v:
                row[f] = v
        if ach:
            row["ach"] = ach.upper()
        for f, v in zip(("dstA", "dstB", "dstC"), tail):
            if v:
                row[f] = v
        if not type_ and ach and not row.get("grade"):
            row["type"] = "진로선택"      # 석차등급 없이 성취도만 나온 줄
        out.append(row)
    return out


class GradeSheet(ctk.CTkToplevel):
    """성적표 한 장을 그대로 옮기는 창.

    app 은 lite.Lite 또는 desktop.App 이다. 둘 다 self.subjects·
    self.student·self.sem_active 를 같은 꼴로 들고 있어서 그대로 쓴다.
    """

    #  성적표에는 영역마다 선택과목·표준점수·백분위·등급이 있다.
    #  영어·한국사는 절대평가라 등급만 나온다 — 그 칸은 아예 안 만든다.
    SU_ROWS = [
        ("한국사", None, False),
        ("국어", ["선택없음", "화법과작문", "언어와매체", "공통"], True),
        ("수학", ["선택없음", "미적분", "기하", "확률과통계", "공통"], True),
        ("영어", None, False),
        ("탐구1", "free", True),
        ("탐구2", "free", True),
        ("제2외국어/한문", "free", False),
    ]

    def __init__(self, app, C, FONT, SEMESTERS, engine):
        super().__init__(app)
        self.app, self.C, self.FONT = app, C, FONT
        self.SEMESTERS, self.engine = list(SEMESTERS), engine
        self.title("성적표 그대로 입력")
        self.geometry("1180x760")
        self.minsize(900, 560)
        self.configure(fg_color=C["bg"])
        self.sem = getattr(app, "active_semester", None) or self.SEMESTERS[0]
        self.cells = {}          # (sid, field) → 위젯
        self.menus = {}          # (sid, "_kind"/"_type") → StringVar
        self.why = {}            # sid → 근거 라벨
        self.su_cells = {}
        self._build()
        self.lift()
        self.attributes("-topmost", True)
        self.after(60, lambda: self.winfo_exists() and self.focus_force())
        self.after(700,
                   lambda: self.winfo_exists()
                   and self.attributes("-topmost", False))
        self.protocol("WM_DELETE_WINDOW", self._close)

    #  ── 뼈대 ────────────────────────────────────────────────────
    def _build(self):
        C, FONT = self.C, self.FONT
        head = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0)
        head.pack(fill="x")
        ctk.CTkLabel(head, text="성적표 그대로 입력",
                     font=(FONT, 18, "bold"),
                     text_color=C["text"]).pack(side="left", padx=16, pady=10)
        self.view = ctk.CTkSegmentedButton(
            head, values=["학생부", "수능·모의고사"], font=(FONT, 12),
            command=self._switch_view, fg_color=C["card2"],
            selected_color=C["accent"], unselected_color=C["card2"])
        self.view.set("학생부")
        self.view.pack(side="left", padx=10)
        ctk.CTkButton(head, text="닫기", width=70, height=28, font=(FONT, 12),
                      fg_color=C["card2"], hover_color=C["line"],
                      text_color=C["text"],
                      command=self._close).pack(side="right", padx=14)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)
        self._build_naesin()

    def _switch_view(self, val):
        if val == "수능·모의고사":
            self._save_rows()
        else:
            self._save_suneung()
        for w in self.body.winfo_children():
            w.destroy()
        self.cells.clear()
        self.menus.clear()
        self.why.clear()
        self.su_cells.clear()
        if val == "학생부":
            self._build_naesin()
        else:
            self._build_suneung()

    #  ── 학생부 ──────────────────────────────────────────────────
    def _build_naesin(self):
        C, FONT = self.C, self.FONT
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(bar, text="학기", font=(FONT, 12),
                     text_color=C["muted"]).pack(side="left", padx=(0, 6))
        self.sem_seg = ctk.CTkSegmentedButton(
            bar, values=self.SEMESTERS, font=(FONT, 12),
            command=self._switch_sem, fg_color=C["card2"],
            selected_color=C["blue"], unselected_color=C["card2"])
        self.sem_seg.set(self.sem)
        self.sem_seg.pack(side="left")
        ctk.CTkButton(bar, text="표 붙여넣기", width=104, height=28,
                      font=(FONT, 12), fg_color=C["card2"],
                      hover_color=C["purple"], text_color=C["text"],
                      command=self._paste_dialog).pack(side="right")
        ctk.CTkButton(bar, text="다른 학기로 복사", width=124, height=28,
                      font=(FONT, 12), fg_color=C["card2"],
                      hover_color=C["green"], text_color=C["text"],
                      command=self._copy_dialog).pack(side="right", padx=6)
        ctk.CTkButton(bar, text="＋ 과목 추가", width=104, height=28,
                      font=(FONT, 12), fg_color=C["card2"],
                      hover_color=C["blue"], text_color=C["text"],
                      command=self._add_row).pack(side="right", padx=6)

        ctk.CTkLabel(self.body, text=GUIDE, font=(FONT, 11), justify="left",
                     text_color=C["muted"]).pack(anchor="w", padx=16,
                                                 pady=(0, 6))

        wrap = ctk.CTkFrame(self.body, fg_color=C["card"], corner_radius=10)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        hdr = tk.Frame(wrap, bg=C["card"])
        hdr.pack(fill="x", padx=8, pady=(8, 2))
        for title, _f, w, tip in COLS:
            lb = tk.Label(hdr, text=title, width=max(4, w // 8),
                          bg=C["card"], fg=C["muted"], font=(FONT, 9))
            lb.pack(side="left", padx=1)
            if tip:
                self._tip(lb, tip)
        tk.Label(hdr, text="근거", width=11, bg=C["card"], fg=C["muted"],
                 font=(FONT, 9)).pack(side="left", padx=1)
        tk.Label(hdr, text="", width=3, bg=C["card"],
                 fg=C["muted"]).pack(side="left")

        self.rows = ctk.CTkScrollableFrame(wrap, fg_color="transparent")
        self.rows.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.foot = ctk.CTkLabel(wrap, text="", font=(FONT, 11),
                                 justify="left", text_color=C["muted"])
        self.foot.pack(anchor="w", padx=14, pady=(0, 8))
        self._fill_rows()

    def _tip(self, widget, text):
        C, FONT = self.C, self.FONT
        box = {"w": None}

        def enter(_=None):
            if box["w"]:
                return
            t = tk.Toplevel(self)
            t.overrideredirect(True)
            t.configure(bg=C["line"])
            tk.Label(t, text=text, bg=C["card2"], fg=C["text"],
                     font=(FONT, 10), padx=8, pady=4).pack(padx=1, pady=1)
            t.geometry("+%d+%d" % (widget.winfo_rootx(),
                                   widget.winfo_rooty() + 22))
            box["w"] = t

        def leave(_=None):
            if box["w"]:
                box["w"].destroy()
                box["w"] = None

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _entry(self, parent, w, field, sid):
        C = self.C
        e = tk.Entry(parent, width=max(3, w // 8), justify="center",
                     bg=C["card2"], fg=C["text"], insertbackground=C["text"],
                     relief="flat", highlightthickness=1,
                     highlightbackground=C["line"],
                     highlightcolor=C["accent"], font=(self.FONT, 11))
        e.pack(side="left", padx=1, ipady=3)
        self.cells[(sid, field)] = e
        e.bind("<KeyRelease>", lambda _=None, s=sid: self._touched(s))
        return e

    def _menu(self, parent, w, field, sid, values, initial):
        C = self.C
        var = tk.StringVar(value=initial)
        m = tk.OptionMenu(parent, var, *values)
        m.configure(bg=C["card2"], fg=C["text"], activebackground=C["line"],
                    activeforeground=C["text"], relief="flat",
                    highlightthickness=1, highlightbackground=C["line"],
                    font=(self.FONT, 10), width=max(4, w // 10), anchor="w",
                    indicatoron=0)
        m["menu"].configure(bg=C["card2"], fg=C["text"], font=(self.FONT, 10),
                            activebackground=C["blue"])
        m.pack(side="left", padx=1)
        self.menus[(sid, field)] = var
        var.trace_add("write", lambda *_a, s=sid: self._touched(s))
        return m

    def _sems(self, subj):
        if subj.get("fixed"):
            return list(self.SEMESTERS)
        s = subj.get("sems")
        return list(s) if s else list(self.SEMESTERS)

    def _subjects(self):
        return [s for s in self.app.subjects
                if s.get("fixed") or self.sem in self._sems(s)]

    def _fill_rows(self):
        C, FONT = self.C, self.FONT
        for w in self.rows.winfo_children():
            w.destroy()
        self.cells.clear()
        self.menus.clear()
        self.why.clear()
        for subj in self._subjects():
            sid = self.app._subj_key(subj)
            row = tk.Frame(self.rows, bg=C["card2"], highlightthickness=0)
            row.pack(fill="x", pady=1)
            fixed = bool(subj.get("fixed"))
            for _title, f, w, _tip in COLS:
                if f == "_kind":
                    if fixed:
                        tk.Label(row, text=subj.get("name") or "",
                                 width=max(4, w // 8), bg=C["card2"],
                                 fg=C["text"],
                                 font=(FONT, 11)).pack(side="left", padx=1)
                    else:
                        cur = LABEL_OF_AREA.get(subj.get("kind") or "", "사회")
                        self._menu(row, w, "_kind", sid, GYOGWA_LABELS, cur)
                elif f == "_type":
                    self._menu(row, w, "_type", sid, SUBJ_TYPES,
                               subj.get("type") or "일반선택")
                elif f == "_name":
                    if fixed:
                        tk.Label(row, text="(교과 전체)",
                                 width=max(4, w // 8), bg=C["card2"],
                                 fg=C["muted"],
                                 font=(FONT, 10)).pack(side="left", padx=1)
                    else:
                        e = self._entry(row, w, "_name", sid)
                        nm = str(subj.get("name") or "")
                        if nm and not re.fullmatch(r"(?:일반|사회|과학)\d*", nm):
                            e.insert(0, nm)
                else:
                    e = self._entry(row, w, f, sid)
                    v = (subj.get(f) or {}).get(self.sem, "")
                    if v not in ("", None):
                        e.insert(0, str(v))
            lb = tk.Label(row, text="", width=11, bg=C["card2"],
                          fg=C["muted"], font=(FONT, 9))
            lb.pack(side="left", padx=1)
            self.why[sid] = lb
            if fixed:
                tk.Label(row, text="", width=3,
                         bg=C["card2"]).pack(side="left")
            else:
                tk.Button(row, text="✕", width=2, bg=C["card2"],
                          fg=C["muted"], relief="flat",
                          activebackground=C["red"], font=(FONT, 9),
                          command=lambda s=subj: self._drop(s)
                          ).pack(side="left")
            self._touched(sid, quiet=True)
        self._summary()

    #  ── 값이 바뀔 때 ────────────────────────────────────────────
    def _rec_of(self, sid):
        rec = {}
        for f in ("grade", "ach", "raw", "mean", "sd"):
            e = self.cells.get((sid, f))
            rec[f] = (e.get().strip() if e is not None else "")
        rec["ach"] = rec["ach"].upper()
        dist = {}
        for key, f in (("A", "dstA"), ("B", "dstB"), ("C", "dstC"),
                       ("D", "dstD"), ("E", "dstE")):
            e = self.cells.get((sid, f))
            v = e.get().strip() if e is not None else ""
            if v:
                dist[key] = v
        rec["dist"] = dist if len(dist) >= 2 else {}
        return rec

    def _touched(self, sid, quiet=False):
        """그 줄의 등급을 다시 추정해 '근거' 를 적는다."""
        g, why = self.engine.subject_grade(self._rec_of(sid))
        lb = self.why.get(sid)
        if lb is not None and lb.winfo_exists():
            if g is None:
                lb.configure(text="—", fg=self.C["muted"])
            else:
                col = {"seokcha": self.C["green"], "dist": self.C["accent"],
                       "zscore": self.C["blue"],
                       "fixed": self.C["orange"]}.get(why, self.C["muted"])
                short = {"seokcha": "석차", "dist": "비율", "zscore": "Z환산",
                         "fixed": "참고값"}.get(why, str(why))
                lb.configure(text="%.2f %s" % (g, short), fg=col)
        if not quiet:
            self._summary()

    def _summary(self):
        n = {"seokcha": 0, "dist": 0, "zscore": 0, "fixed": 0}
        for sid in list(self.why):
            _g, why = self.engine.subject_grade(self._rec_of(sid))
            if why in n:
                n[why] += 1
        parts = []
        for key, word in (("seokcha", "석차등급"), ("dist", "성취도 비율 환산"),
                          ("zscore", "원점수 Z환산"),
                          ("fixed", "성취도 참고값")):
            if n[key]:
                parts.append("%s %d" % (word, n[key]))
        msg = "이 학기 " + (" · ".join(parts) if parts else "입력 없음")
        if n["fixed"]:
            msg += ("   ⚠ 참고값으로 잡은 %d과목은 A/B/C 비율이나 "
                    "과목평균·표준편차를 넣으면 정확해집니다." % n["fixed"])
        if hasattr(self, "foot") and self.foot.winfo_exists():
            self.foot.configure(text=msg)

    def _by_sid(self, sid):
        for s in self.app.subjects:
            if s.get("sid") == sid:
                return s
        return None

    #  ── 저장·이동 ───────────────────────────────────────────────
    def _save_rows(self):
        for subj in list(self.app.subjects):
            sid = subj.get("sid")
            if not sid:
                continue
            var = self.menus.get((sid, "_kind"))
            if var is not None:
                subj["kind"] = AREA_OF_LABEL.get(var.get(), var.get())
            var = self.menus.get((sid, "_type"))
            if var is not None:
                subj["type"] = var.get()
            e = self.cells.get((sid, "_name"))
            if e is not None:
                subj["name"] = e.get().strip()
            for f in SEM_FIELDS:
                e = self.cells.get((sid, f))
                if e is None:
                    continue
                if not isinstance(subj.get(f), dict):
                    subj[f] = {}
                v = e.get().strip()
                subj[f][self.sem] = v.upper() if f == "ach" else v

    def _switch_sem(self, val):
        self._save_rows()
        self.sem = val
        self._fill_rows()

    def _add_row(self):
        self._save_rows()
        subj = blank_subject([self.sem])
        self.app._subj_key(subj)
        self.app.subjects.append(subj)
        self._fill_rows()

    def _drop(self, subj):
        """이 학기에서만 뺀다. 어느 학기에도 안 남으면 아예 지운다."""
        self._save_rows()
        sems = [x for x in self._sems(subj) if x != self.sem]
        for f in SEM_FIELDS:
            if isinstance(subj.get(f), dict):
                subj[f].pop(self.sem, None)
        if sems:
            subj["sems"] = sems
        else:
            self.app.subjects = [s for s in self.app.subjects if s is not subj]
        self._fill_rows()

    #  ── 다른 학기로 복사 ────────────────────────────────────────
    #
    #  과목은 학기마다 따로 둔다. 학기마다 듣는 과목이 다르기 때문이다.
    #  그런데 한 해 두 학기에 같은 과목을 듣는 일이 흔하다. 이름·교과·
    #  유형·단위까지 스무 번 다시 적게 하지 않는다. 성적은 학기마다
    #  다르므로 **틀만 옮기고 값은 안 옮긴다.**
    def _copy_dialog(self):
        C, FONT = self.C, self.FONT
        self._save_rows()
        movable = [s for s in self._subjects() if not s.get("fixed")]
        win = ctk.CTkToplevel(self)
        win.title("다른 학기로 복사")
        win.geometry("420x330")
        win.configure(fg_color=C["bg"])
        win.transient(self)
        ctk.CTkLabel(win, text="%s 의 과목 %d개를 어느 학기로?"
                     % (self.sem, len(movable)),
                     font=(FONT, 14, "bold"),
                     text_color=C["text"]).pack(pady=(16, 2))
        ctk.CTkLabel(win, justify="left", font=(FONT, 11),
                     text_color=C["muted"],
                     text="과목명·교과·유형·단위만 옮깁니다. 등급과 점수는 "
                          "학기마다 다르므로\n옮기지 않습니다. 이미 있는 "
                          "학기는 그대로 둡니다."
                     ).pack(padx=16, pady=(0, 10))
        picks = {}
        grid = ctk.CTkFrame(win, fg_color="transparent")
        grid.pack(padx=20, fill="x")
        for i, sm in enumerate([x for x in self.SEMESTERS if x != self.sem]):
            v = tk.BooleanVar(value=False)
            picks[sm] = v
            r, cc = divmod(i, 2)
            grid.grid_columnconfigure(cc, weight=1)
            ctk.CTkCheckBox(grid, text=sm, variable=v, font=(FONT, 12),
                            checkbox_width=18, checkbox_height=18,
                            fg_color=C["green"], text_color=C["text"]
                            ).grid(row=r, column=cc, sticky="w",
                                   padx=6, pady=5)
        note = ctk.CTkLabel(win, text="", font=(FONT, 11),
                            text_color=C["orange"])
        note.pack(pady=(8, 0))

        def go():
            targets = [sm for sm, v in picks.items() if v.get()]
            if not targets:
                note.configure(text="옮길 학기를 고르세요.")
                return
            made = 0
            for src in movable:
                for sm in targets:
                    if sm in self._sems(src):
                        continue        # 이미 그 학기에 있다
                    new = blank_subject([sm], kind=src.get("kind"),
                                        type_=src.get("type") or "일반선택",
                                        name=src.get("name") or "")
                    new["unit"] = {sm: (src.get("unit") or {}).get(self.sem,
                                                                   "")}
                    self.app._subj_key(new)
                    self.app.subjects.append(new)
                    made += 1
            win.destroy()
            self._fill_rows()
            if hasattr(self, "foot") and self.foot.winfo_exists():
                self.foot.configure(text="과목 %d개를 %s 로 옮겼습니다. "
                                         "성적은 각 학기에서 넣으세요."
                                    % (made, " · ".join(targets)))

        brow = ctk.CTkFrame(win, fg_color="transparent")
        brow.pack(pady=(12, 14))
        ctk.CTkButton(brow, text="복사", width=100, height=32,
                      font=(FONT, 13), fg_color=C["green"],
                      command=go).pack(side="left", padx=6)
        ctk.CTkButton(brow, text="취소", width=100, height=32,
                      font=(FONT, 13), fg_color=C["card2"],
                      hover_color=C["line"], text_color=C["text"],
                      command=win.destroy).pack(side="left", padx=6)
        try:
            win.grab_set()
        except Exception:
            pass

    #  ── 표 붙여넣기 ─────────────────────────────────────────────
    def _paste_dialog(self):
        C, FONT = self.C, self.FONT
        self._save_rows()
        win = ctk.CTkToplevel(self)
        win.title("표 붙여넣기")
        win.geometry("640x450")
        win.configure(fg_color=C["bg"])
        win.transient(self)
        ctk.CTkLabel(win, text="성적표 표를 그대로 붙여넣으세요",
                     font=(FONT, 15, "bold"),
                     text_color=C["text"]).pack(pady=(14, 2))
        ctk.CTkLabel(
            win, justify="left", font=(FONT, 11), text_color=C["muted"],
            text=("엑셀·한글 표에서 긁어 붙이면 됩니다. 칸 순서는\n"
                  "  [교과] [유형] 과목명 단위 석차등급 원점수 과목평균 "
                  "표준편차 수강자 성취도 A% B% C%\n"
                  "교과·유형이 없으면 과목명부터 읽습니다. 나중에 "
                  "표에서 고르면 됩니다. 없는 칸은 비워 두세요.")
        ).pack(padx=16, anchor="w")
        box = tk.Text(win, height=12, bg=C["card2"], fg=C["text"],
                      insertbackground=C["text"], relief="flat",
                      font=(FONT, 11))
        box.pack(fill="both", expand=True, padx=16, pady=10)
        note = ctk.CTkLabel(win, text="", font=(FONT, 11),
                            text_color=C["orange"])
        note.pack()

        def go():
            rows = parse_paste(box.get("1.0", "end"))
            if not rows:
                note.configure(text="읽을 줄을 못 찾았습니다.")
                return
            for r in rows:
                subj = blank_subject([self.sem], kind=r.get("kind"),
                                     type_=r.get("type"),
                                     name=r.get("name") or "")
                for f in SEM_FIELDS:
                    if r.get(f):
                        subj[f] = {self.sem: (r[f].upper() if f == "ach"
                                              else r[f])}
                self.app._subj_key(subj)
                self.app.subjects.append(subj)
            win.destroy()
            self._fill_rows()

        brow = ctk.CTkFrame(win, fg_color="transparent")
        brow.pack(pady=(0, 14))
        ctk.CTkButton(brow, text="넣기", width=100, height=32, font=(FONT, 13),
                      fg_color=C["blue"], command=go).pack(side="left", padx=6)
        ctk.CTkButton(brow, text="취소", width=100, height=32, font=(FONT, 13),
                      fg_color=C["card2"], hover_color=C["line"],
                      text_color=C["text"],
                      command=win.destroy).pack(side="left", padx=6)
        try:
            win.grab_set()
        except Exception:
            pass

    #  ── 수능·모의고사 ───────────────────────────────────────────
    def _build_suneung(self):
        C, FONT = self.C, self.FONT
        self.app.student.setdefault("suneung", {})
        det = self.app.student.setdefault("suneung_detail", {})

        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(top, text="시험 회차", font=(FONT, 12),
                     text_color=C["muted"]).pack(side="left")
        self.exam_e = tk.Entry(top, width=26, bg=C["card2"], fg=C["text"],
                               insertbackground=C["text"], relief="flat",
                               highlightthickness=1,
                               highlightbackground=C["line"],
                               font=(FONT, 11))
        self.exam_e.insert(0, det.get("회차", ""))
        self.exam_e.pack(side="left", padx=8, ipady=3)
        ctk.CTkLabel(top, text="예) 2027 수능 · 2026 9월 모평",
                     font=(FONT, 11),
                     text_color=C["muted"]).pack(side="left")

        ctk.CTkLabel(
            self.body, justify="left", font=(FONT, 11), text_color=C["muted"],
            text=("성적표의 영역별 표준점수·백분위·등급을 그대로 넣으세요.\n"
                  "· 영어와 한국사는 절대평가라 등급만 나옵니다 — 그 칸만 "
                  "만들어 두었습니다.\n"
                  "· 표준점수는 받아서 함께 저장합니다. 대학별 정시 환산은 "
                  "요강의 환산표를 읽은 대학부터 씁니다.\n"
                  "· 여기서 넣은 등급·백분위는 서랍(성적 입력 및 설정)에도 "
                  "그대로 들어갑니다.")
        ).pack(anchor="w", padx=16, pady=(6, 8))

        wrap = ctk.CTkFrame(self.body, fg_color=C["card"], corner_radius=10)
        wrap.pack(fill="x", padx=14, pady=(0, 12))
        hdr = tk.Frame(wrap, bg=C["card"])
        hdr.pack(fill="x", padx=10, pady=(10, 2))
        for t, w in (("영역", 12), ("선택과목", 18), ("표준점수", 10),
                     ("백분위", 10), ("등급", 8)):
            tk.Label(hdr, text=t, width=w, bg=C["card"], fg=C["muted"],
                     font=(FONT, 10)).pack(side="left", padx=3)

        for name, choices, has_score in self.SU_ROWS:
            d = det.setdefault(name, {})
            row = tk.Frame(wrap, bg=C["card"])
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=name, width=12, bg=C["card"], fg=C["text"],
                     font=(FONT, 12), anchor="w").pack(side="left", padx=3)
            if choices == "free":
                e = tk.Entry(row, width=18, bg=C["card2"], fg=C["text"],
                             insertbackground=C["text"], relief="flat",
                             highlightthickness=1,
                             highlightbackground=C["line"], font=(FONT, 11))
                e.insert(0, d.get("sel", "") or self._drawer_name(name))
                e.pack(side="left", padx=3, ipady=3)
                self.su_cells[(name, "sel")] = e
            elif choices:
                cur = d.get("sel") or self._drawer_sel(name) or choices[0]
                if cur not in choices:
                    cur = choices[0]
                var = tk.StringVar(value=cur)
                m = tk.OptionMenu(row, var, *choices)
                m.configure(bg=C["card2"], fg=C["text"], relief="flat",
                            highlightthickness=1,
                            highlightbackground=C["line"],
                            activebackground=C["line"], width=15,
                            font=(FONT, 10), indicatoron=0, anchor="w")
                m["menu"].configure(bg=C["card2"], fg=C["text"],
                                    font=(FONT, 10),
                                    activebackground=C["blue"])
                m.pack(side="left", padx=3)
                self.su_cells[(name, "sel")] = var
            else:
                tk.Label(row, text="—", width=18, bg=C["card"],
                         fg=C["muted"],
                         font=(FONT, 11)).pack(side="left", padx=3)
            for f, w, on in (("std", 10, has_score), ("pct", 10, has_score),
                             ("g", 8, True)):
                if not on:
                    tk.Label(row, text="", width=w, bg=C["card"],
                             fg=C["muted"]).pack(side="left", padx=3)
                    continue
                e = tk.Entry(row, width=w, justify="center", bg=C["card2"],
                             fg=C["text"], insertbackground=C["text"],
                             relief="flat", highlightthickness=1,
                             highlightbackground=C["line"], font=(FONT, 11))
                v = d.get(f, "")
                if f == "g" and not v:
                    v = self._drawer_grade(name)
                if f == "pct" and not v:
                    v = self._drawer_pct(name)
                if v not in ("", None):
                    e.insert(0, str(v))
                e.pack(side="left", padx=3, ipady=3)
                self.su_cells[(name, f)] = e
        tk.Label(wrap, text="", bg=C["card"]).pack(pady=4)

    #  서랍에 이미 적어 둔 값을 끌어온다 — 두 번 적게 하지 않는다
    def _drawer_grade(self, name):
        try:
            if name in ("국어", "수학", "영어", "한국사"):
                e = (getattr(self.app, "suneung_entries", {}) or {}).get(name)
                v = e.get().strip() if e is not None else ""
                if v:
                    return v
                #  서랍이 아직 안 그려졌거나 비어 있을 수 있다.
                #  학생 자료에 있는 값을 그때는 그것으로 채운다.
                v = (self.app.student.get("suneung") or {}).get(name, "")
                return "" if v in (None, "") else str(v)
            if name.startswith("탐구"):
                i = int(name[2:]) - 1
                tg = getattr(self.app, "tamgu", []) or []
                return str(tg[i].get("g", "")) if i < len(tg) else ""
        except Exception:
            pass
        return ""

    def _drawer_pct(self, name):
        try:
            if name in ("국어", "수학"):
                e = (getattr(self.app, "baekbunwi_entries", {})
                     or {}).get(name)
                return e.get().strip() if e is not None else ""
            if name.startswith("탐구"):
                i = int(name[2:]) - 1
                tg = getattr(self.app, "tamgu", []) or []
                return str(tg[i].get("pct", "")) if i < len(tg) else ""
        except Exception:
            pass
        return ""

    def _drawer_name(self, name):
        try:
            if name.startswith("탐구"):
                i = int(name[2:]) - 1
                tg = getattr(self.app, "tamgu", []) or []
                return str(tg[i].get("name", "")) if i < len(tg) else ""
        except Exception:
            pass
        return ""

    def _drawer_sel(self, name):
        if name == "수학":
            try:
                v = self.app.math_var.get()
                return "공통" if v.startswith("공통") else v
            except Exception:
                return ""
        return ""

    def _save_suneung(self):
        if not getattr(self, "su_cells", None):
            return
        det = self.app.student.setdefault("suneung_detail", {})
        if hasattr(self, "exam_e"):
            try:
                if self.exam_e.winfo_exists():
                    det["회차"] = self.exam_e.get().strip()
            except Exception:
                pass
        for (name, f), w in list(self.su_cells.items()):
            d = det.setdefault(name, {})
            try:
                d[f] = (w.get() if isinstance(w, tk.StringVar)
                        else w.get().strip())
            except Exception:
                continue
        #  서랍으로 되돌려 준다 — 판정은 서랍 값으로 돈다
        for name in ("국어", "수학", "영어", "한국사"):
            g = (det.get(name) or {}).get("g", "")
            e = (getattr(self.app, "suneung_entries", {}) or {}).get(name)
            if e is not None and g:
                e.delete(0, "end")
                e.insert(0, g)
        for name in ("국어", "수학"):
            p = (det.get(name) or {}).get("pct", "")
            e = (getattr(self.app, "baekbunwi_entries", {}) or {}).get(name)
            if e is not None and p:
                e.delete(0, "end")
                e.insert(0, p)
        sel = (det.get("수학") or {}).get("sel", "")
        if sel and sel != "선택없음" and hasattr(self.app, "math_var"):
            try:
                self.app.math_var.set("공통(선택없음)" if sel == "공통" else sel)
            except Exception:
                pass
        tg = getattr(self.app, "tamgu", None)
        if isinstance(tg, list):
            for i, key in enumerate(("탐구1", "탐구2")):
                d = det.get(key) or {}
                while len(tg) <= i:
                    tg.append({"name": key, "g": "", "pct": ""})
                if d.get("sel"):
                    tg[i]["name"] = d["sel"]
                if d.get("g"):
                    tg[i]["g"] = d["g"]
                if d.get("pct"):
                    tg[i]["pct"] = d["pct"]

    #  ── 닫기 ────────────────────────────────────────────────────
    def _close(self):
        try:
            if self.view.get() == "학생부":
                self._save_rows()
            else:
                self._save_suneung()
        except Exception:
            pass
        app = self.app
        #  성적표가 5등급제라고 말하면 켜 준다. 학생이 체크를 잊으면
        #  5등급 1등급(상위 10%)을 9등급 1등급(상위 4%)으로 읽어
        #  실제보다 좋게 본다 — 못 갈 곳을 갈 수 있다고 읽는 쪽이다.
        try:
            five, why = self.engine.guess_five(getattr(app, "subjects", []))
            var = getattr(app, "five_var", None)
            if five and var is not None and not var.get():
                var.set(True)
                note = getattr(app, "five_note", None)
                if note is not None:
                    note.configure(
                        text="5등급제로 자동 전환했습니다 — " + why)
                f = getattr(app, "_on_five_scale", None)
                if callable(f):
                    f()
        except Exception:
            pass
        try:
            app._sheet_win = None
        except Exception:
            pass
        self.destroy()
        for fn in ("_rebuild_electives", "_rebuild_tamgu"):
            f = getattr(app, fn, None)
            if callable(f):
                try:
                    f()
                except Exception:
                    pass
        f = getattr(app, "_load_year_entries", None)
        if callable(f):
            try:
                f(getattr(app, "active_semester", None) or self.SEMESTERS[0])
            except Exception:
                pass
        f = getattr(app, "recompute", None)
        if callable(f):
            f()


def open_sheet(app, C, FONT, SEMESTERS, engine):
    """서랍에서 부른다. 이미 열려 있으면 그 창을 앞으로 가져온다."""
    w = getattr(app, "_sheet_win", None)
    if w is not None:
        try:
            if w.winfo_exists():
                w.lift()
                w.focus_force()
                return w
        except Exception:
            pass
    #  서랍에 적던 값을 먼저 과목에 저장해야 표에 보인다
    for fn in ("_save_year_entries", "_save_tamgu"):
        f = getattr(app, fn, None)
        if not callable(f):
            continue
        try:
            if fn == "_save_year_entries":
                f(getattr(app, "active_semester", None) or SEMESTERS[0])
            else:
                f()
        except Exception:
            pass
    app._sheet_win = GradeSheet(app, C, FONT, SEMESTERS, engine)
    return app._sheet_win
