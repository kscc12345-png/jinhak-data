# -*- coding: utf-8 -*-
"""
lite.py — 진학 분석기 (라이트 뷰어)

관리자가 발행한 데이터(published/)를 불러와 성적 입력·결과만 가볍게 본다.
PDF 처리·OCR 없음. 원문은 미리 만들어진 이미지로 본다.
없는 대학은 이메일로 관리자에게 요청.
"""
import os, sys, json, webbrowser, threading, urllib.request, ssl
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

APP = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(APP)
PUBLISHED = os.environ.get("JINHAK_DATA") or os.path.join(BASE, "published")
PAGES = os.path.join(PUBLISHED, "pages")
sys.path.insert(0, APP)
import engine, features

C = {
    "bg": "#080c17", "card": "#111a2e", "card2": "#18233c", "muted": "#8a97b0",
    "text": "#eaf1ff", "line": "#233150", "accent": "#22d3ee", "blue": "#3b82f6",
    "purple": "#8b5cf6", "orange": "#fb923c", "green": "#34d399", "yellow": "#fbbf24",
    "red": "#f87171", "gray": "#64748b", "cyan": "#22d3ee",
}
BAND_COLOR = {"안정": C["green"], "적정": C["accent"], "소신": C["yellow"],
              "위험": C["orange"], "매우위험": C["red"],
              "지원불가": C["gray"], "판정보류": C["gray"]}
BAND_ORDER = ["안정", "적정", "소신", "위험", "매우위험", "판정보류", "지원불가"]
FIXED_SUBS = ["국어", "수학", "영어", "한국사"]
SUBS = ["국어", "수학", "영어", "사회", "과학", "한국사"]
FONT = "Malgun Gothic"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


PLAIN = os.path.join(PUBLISHED, "universities.json")
ENC = os.path.join(PUBLISHED, "universities.enc")
ACCESS = os.path.join(BASE, ".access")       # 검증된 접근코드 캐시(로컬)


def saved_code():
    if os.path.exists(ACCESS):
        try:
            return open(ACCESS, encoding="utf-8").read().strip()
        except Exception:
            return ""
    return ""


def save_code(code):
    try:
        with open(ACCESS, "w", encoding="utf-8") as f:
            f.write(code or "")
    except Exception:
        pass


# 자동 업데이트 대상 앱 모듈(publish.LITE_MODULES 와 동일해야 함)
LITE_MODULES = ["lite.py", "engine.py", "assemble.py", "suneung.py", "gyogwa.py",
                "model.py", "meta.py", "cryptobox.py", "features.py", "srcref.py", "version.json"]


def local_version_info():
    """로컬 app/version.json의 버전 정보 읽기."""
    p = os.path.join(APP, "version.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": "1.2.0", "version_code": 120, "min_version_code": 100}


def local_version_code():
    """로컬 앱의 정수 버전 코드(예: 120)."""
    return local_version_info().get("version_code", 120)


def local_app_version():
    """하위 호환용 버전 문자열."""
    return local_version_info().get("version", "1.2.0")


def http_get(url, timeout=20):
    """URL 다운로드. 회사/학교 프록시(자체서명 인증서)에서도 되도록 검증 실패 시 우회."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return urllib.request.urlopen(req, context=ssl.create_default_context(),
                                      timeout=timeout).read()
    except Exception:
        return urllib.request.urlopen(req, context=ssl._create_unverified_context(),
                                      timeout=timeout).read()


def read_univs(code=None):
    """반환 (dict|None, need_code:bool). 평문이면 그대로, 암호문이면 code 필요."""
    if os.path.exists(PLAIN):
        try:
            return json.load(open(PLAIN, encoding="utf-8")), False
        except Exception:
            return {}, False
    if os.path.exists(ENC):
        if not code:
            return None, True
        import cryptobox
        data = cryptobox.decrypt(open(ENC, "rb").read(), code)
        if data is None:
            return None, True           # 코드 틀림
        try:
            return json.loads(data.decode("utf-8")), False
        except Exception:
            return None, True
    return {}, False


def load_config():
    p = os.path.join(PUBLISHED, "config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"admin_email": "", "update_url": "", "generated": "-"}


class Lite(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("진학 분석기 (라이트)")
        self.geometry("1300x880")
        self.configure(fg_color=C["bg"])
        self.univs = {}
        self.cfg = load_config()
        self.student = {
            "gyeyeol": "자연",
            "weights": {"1": 2.0, "2": 4.0, "3": 4.0},
            "suneung": {"국어": 3, "수학": 3, "영어": 3, "한국사": 4, "수학선택": "미적분"},
        }
        def _d(): return {"1-1": "", "1-2": "", "2-1": "", "2-2": "", "3-1": "", "3-2": ""}
        self.subjects = [{"name": s, "fixed": True, "kind": None, "grade": _d(), "ach": _d(), "raw": _d(), "unit": _d()}
                         for s in FIXED_SUBS]
        self.subjects += [{"name": "사회", "fixed": False, "kind": "사회", "grade": _d(), "ach": _d(), "raw": _d(), "unit": _d()},
                          {"name": "과학", "fixed": False, "kind": "과학", "grade": _d(), "ach": _d(), "raw": _d(), "unit": _d()}]
        self.tamgu = [{"name": "탐구1", "g": "3", "pct": ""},
                      {"name": "탐구2", "g": "4", "pct": ""}]
        self.year_active = {"1": True, "2": True, "3": True}
        self.font_scale = 1.0
        self.active_semester = "1-1"
        self.grade_entries = {}; self.ach_entries = {}; self.raw_entries = {}; self.unit_entries = {}; self.suneung_entries = {}; self.weight_entries = {}
        self.baekbunwi_entries = {}
        self.results = []
        self.minsize(1100, 700)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._quit_app)   # 닫으면 완전 종료(재실행 대비)
        self.after(200, self._ensure_data)

    def _quit_app(self):
        """창 닫을 때 백그라운드 스레드/after까지 완전 종료(좀비 프로세스 방지)."""
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    def _ensure_data(self):
        univs, need = read_univs(saved_code())
        if need:
            self._ask_code()
            return
        self.univs = univs or {}
        self._refresh_filters()           # 데이터 로드 후 대학·학년도 목록 채우기
        if self.univs:
            self.recompute()
        else:
            self._toast("데이터가 없습니다. '최신 데이터 받기'를 누르거나 관리자에게 문의하세요.")
        if self.cfg.get("update_url"):
            self.after(400, lambda: self._fetch_data(silent=True))
            self.after(1500, self._check_app_update)   # 앱(코드) 새 버전 확인

    def _check_app_update(self):
        """GitHub의 manifest.json과 버전 코드를 비교하여, 서버 버전이 명시적으로 높을 때만 업데이트."""
        url = self.cfg.get("update_url", "").rstrip("/")
        if not url:
            return

        def work():
            try:
                import json as _json
                man = _json.loads(http_get(f"{url}/manifest.json").decode("utf-8"))
                remote_code = man.get("version_code", 0)
                remote_ver = man.get("version", "최신")
                min_code = man.get("min_version_code", 0)
                mods = man.get("app_modules") or LITE_MODULES
                
                local_code = local_version_code()
                
                # ★ 원격 버전 코드가 로컬 버전 코드보다 클 때만 업데이트 제안
                # (remote_code <= local_code 일 때는 절대로 업데이트 창이 뜨지 않음)
                if remote_code > local_code:
                    forced = local_code < min_code
                    self.after(0, lambda: self._ask_app_update(remote_ver, remote_code, mods, forced=forced))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _ask_app_update(self, remote_ver, remote_code, mods, forced=False):
        win = self._top(); win.title("프로그램 업데이트")
        win.geometry("440x220"); win.configure(fg_color=C["card"])
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.grab_set()
        ctk.CTkLabel(win, text=f"🔔 새 버전(v{remote_ver})이 있습니다", font=("Malgun Gothic", 17, "bold"),
                     text_color=C["text"]).pack(pady=(22, 6))
        ctk.CTkLabel(win, text="프로그램을 최신 버전으로 업데이트해야 합니다.\n"
                     "업데이트 후 자동으로 다시 시작됩니다.",
                     font=("Malgun Gothic", 12), text_color=C["muted"],
                     justify="center").pack(pady=(0, 6))
        row = ctk.CTkFrame(win, fg_color="transparent"); row.pack(pady=14)
        ctk.CTkButton(row, text="지금 업데이트", width=200, fg_color=C["blue"],
                      font=("Malgun Gothic", 14, "bold"),
                      command=lambda: (win.destroy(),
                                       self._do_app_update(mods))).pack(padx=8)

    def _do_app_update(self, mods):
        self._progress("프로그램 업데이트 중…")
        url = self.cfg.get("update_url", "").rstrip("/")

        def work():
            try:
                for m in mods:
                    data = http_get(f"{url}/app/{m}")
                    with open(os.path.join(APP, m), "wb") as f:
                        f.write(data)
                self.after(0, self._restart_app)
            except Exception as e:
                self.after(0, lambda: (self._progress_done(),
                    self._toast(f"업데이트 실패: {e}\n(기존 버전으로 계속 사용)")))
        threading.Thread(target=work, daemon=True).start()

    def _restart_app(self):
        """새 코드로 다시 시작."""
        self._progress_done()
        win = ctk.CTkToplevel(self)
        win.title("업데이트 완료")
        win.geometry("380x160")
        win.configure(fg_color=C["card"])
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text="✅ 업데이트 완료!\n다시 시작합니다.",
                     font=("Malgun Gothic", 16, "bold"), text_color=C["text"],
                     justify="center").pack(pady=(30, 10))
        ctk.CTkButton(win, text="확인", width=120, fg_color=C["blue"],
                      font=("Malgun Gothic", 13, "bold"),
                      command=lambda: self._do_restart()).pack(pady=10)

    def _do_restart(self):
        import subprocess
        try:
            subprocess.Popen([sys.executable, os.path.join(APP, "lite.py")], close_fds=True)
        except Exception:
            pass
        os._exit(0)

    def _progress(self, msg):
        try:
            w = getattr(self, "_progwin", None)
            if not (w and w.winfo_exists()):
                w = ctk.CTkToplevel(self); w.title("작업 중")
                w.geometry("400x120"); w.configure(fg_color=C["card"])
                w.resizable(False, False); w.attributes("-topmost", True)
                w.protocol("WM_DELETE_WINDOW", lambda: None)
                self._proglabel = ctk.CTkLabel(w, text="", font=("Malgun Gothic", 13),
                    text_color=C["text"], wraplength=360, justify="left")
                self._proglabel.pack(expand=True, padx=18, pady=18)
                self._progwin = w
            self._proglabel.configure(text=msg)
            self._progwin.lift(); self._progwin.update_idletasks()
        except Exception:
            pass

    def _progress_done(self):
        try:
            if getattr(self, "_progwin", None) and self._progwin.winfo_exists():
                self._progwin.destroy()
        except Exception:
            pass

    def _refresh_filters(self):
        """데이터 로드/갱신 후 대학 드롭다운·학년도 탭을 실제 목록으로 갱신."""
        try:
            names = ["전체 대학"] + sorted(u["name"] for u in self.univs.values())
            self.univ_menu.configure(values=names)
            years = sorted({u.get("year") for u in self.univs.values() if u.get("year")},
                           reverse=True)
            self.year_seg.configure(values=["전체"] + [f"{y}학년도" for y in years])
        except Exception:
            pass

    def _top(self):
        """항상 최상단에 뜨는 새 창 생성."""
        w = ctk.CTkToplevel(self)
        w.lift()
        w.attributes("-topmost", True)
        w.after(50, lambda: w.winfo_exists() and w.focus_force())
        w.after(600, lambda: w.winfo_exists() and w.attributes("-topmost", False))
        return w

    def _ask_code(self):
        win = self._top(); win.title("접근 코드"); win.geometry("400x230")
        win.configure(fg_color=C["card"]); win.transient(self)
        try: win.grab_set()
        except Exception: pass
        ctk.CTkLabel(win, text="🔒 접근 코드", font=("Malgun Gothic", 17, "bold"),
                     text_color=C["text"]).pack(pady=(22, 4))
        ctk.CTkLabel(win, text="관리자에게 받은 접근 코드를 입력하세요.",
                     font=("Malgun Gothic", 12), text_color=C["muted"]).pack()
        ent = ctk.CTkEntry(win, width=250, show="●", justify="center",
                           fg_color=C["card2"], border_color=C["line"],
                           font=("Malgun Gothic", 14)); ent.pack(pady=14)
        msg = ctk.CTkLabel(win, text="", text_color=C["red"], font=("Malgun Gothic", 11))
        msg.pack()

        def submit(*_):
            code = ent.get().strip()
            u, need = read_univs(code)
            if need or u is None:
                msg.configure(text="코드가 올바르지 않습니다. 다시 시도하세요."); return
            save_code(code); self.univs = u or {}
            try: win.grab_release()
            except Exception: pass
            win.destroy()
            self._refresh_filters()
            if self.univs:
                self.recompute()
            if self.cfg.get("update_url"):
                self.after(400, lambda: self._fetch_data(silent=True))
        ctk.CTkButton(win, text="확인", command=submit, fg_color=C["blue"],
                      width=120, font=("Malgun Gothic", 13)).pack(pady=8)
        ent.bind("<Return>", submit); ent.focus()

    def _toggle_drawer(self):
        if self.drawer_open:
            self.drawer.place_forget()
            self.drawer_open = False
        else:
            self.drawer.place(relx=0, rely=0, relheight=1)
            self.drawer.lift()
            self.drawer_open = True
            
    def _on_app_click(self, event):
        if hasattr(self, "drawer_open") and self.drawer_open:
            w = event.widget
            while w:
                if w == self.drawer or w == getattr(self, "toggle_btn", None):
                    return
                w = getattr(w, "master", None)
            self._toggle_drawer()

    def _card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=16,
                            border_width=1, border_color=C["line"], **kw)

    def _badge(self, parent, emoji, color):
        b = ctk.CTkFrame(parent, fg_color=color, corner_radius=10, width=34, height=34)
        b.pack_propagate(False)
        ctk.CTkLabel(b, text=emoji, font=(FONT, 15), text_color="#08111f").pack(expand=True)
        return b

    def _section(self, parent, emoji, title, color=None, sub=None):
        color = color or C["accent"]
        card = self._card(parent); card.pack(fill="x", pady=(0, 12))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 4))
        self._badge(head, emoji, color).pack(side="left")
        box = ctk.CTkFrame(head, fg_color="transparent"); box.pack(side="left", padx=10)
        ctk.CTkLabel(box, text=title, font=(FONT, 14, "bold"),
                     text_color=C["text"]).pack(anchor="w")
        if sub:
            ctk.CTkLabel(box, text=sub, font=(FONT, 11),
                         text_color=C["muted"]).pack(anchor="w")
        return card

    def _mini_entry(self, parent, w=64, ph=""):
        return ctk.CTkEntry(parent, width=w, justify="center", placeholder_text=ph,
                            fg_color=C["card2"], border_color=C["line"], font=(FONT, 13))

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 4))
        ctk.CTkLabel(head, text="🎓  진학 분석기", font=("Malgun Gothic", 24, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(head, text="라이트 뷰어", font=("Malgun Gothic", 13),
                     text_color=C["purple"]).pack(side="left", padx=10)
        fs = ctk.CTkFrame(head, fg_color="transparent"); fs.pack(side="left", padx=12)
        ctk.CTkButton(fs, text="가－", width=44, height=28, font=("Malgun Gothic", 12),
            fg_color=C["card2"], hover_color=C["line"],
            command=lambda: self._apply_font_scale(-0.1)).pack(side="left", padx=2)
        ctk.CTkButton(fs, text="+", width=44, height=28, font=("Malgun Gothic", 13, "bold"),
            fg_color=C["card2"], hover_color=C["line"],
            command=lambda: self._apply_font_scale(0.1)).pack(side="left", padx=2)
            
        self.toggle_btn = ctk.CTkButton(head, text="☰ 성적 입력 및 설정", width=140, font=("Malgun Gothic", 12, "bold"), fg_color=C["card2"], hover_color=C["line"], text_color=C["text"], command=self._toggle_drawer)
        self.toggle_btn.pack(side="left", padx=12)
        ctk.CTkButton(head, text="✉️ 없는 대학 요청", font=("Malgun Gothic", 12),
                      fg_color=C["card2"], hover_color=C["line"], width=140,
                      command=self._request).pack(side="right")
        ctk.CTkButton(head, text="🔄 최신 데이터 받기", font=("Malgun Gothic", 12),
                      fg_color=C["blue"], hover_color=C["blue"], width=150,
                      command=self._update).pack(side="right", padx=8)

        # main container
        self.right = ctk.CTkFrame(self, fg_color="transparent")
        self.right.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=18, pady=8)

        # drawer overlay
        self.drawer_open = False
        self.drawer = ctk.CTkFrame(self.right, fg_color=C["bg"], corner_radius=12, border_width=1, border_color=C["line"], width=460)
        self.drawer.pack_propagate(False)
        dh = ctk.CTkFrame(self.drawer, fg_color="transparent"); dh.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(dh, text="성적 입력 및 설정", font=("Malgun Gothic", 18, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkButton(dh, text="✕ 닫기", width=60, fg_color=C["card2"], hover_color=C["line"], text_color=C["text"], command=self._toggle_drawer).pack(side="right")
        self.left = ctk.CTkScrollableFrame(self.drawer, fg_color="transparent")
        self.left.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_inputs(self.left)
        self.right.grid_columnconfigure(0, weight=1)
        self.right.grid_rowconfigure(3, weight=1)
        self._build_stats(self.right)
        self._build_chart(self.right)
        self._build_filters(self.right)
        self._build_table(self.right)
        self.bind_all("<Button-1>", self._on_app_click, add="+")
        # 하단 배너
        self.banner = ctk.CTkFrame(self, fg_color=C["card2"], corner_radius=0, height=62)
        self.banner.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.banner.grid_propagate(False)
        self._load_banner()

    def _load_banner(self):
        for w in self.banner.winfo_children():
            w.destroy()
        bp = os.path.join(PUBLISHED, "banner.png")
        link = self.cfg.get("banner_link", "")
        placed = False
        if os.path.exists(bp):
            try:
                from PIL import Image
                im = Image.open(bp)
                h = 50; w = max(1, int(im.width * h / im.height))
                ci = ctk.CTkImage(light_image=im, dark_image=im, size=(w, h))
                lbl = ctk.CTkLabel(self.banner, image=ci, text=""); lbl.image = ci
                lbl.pack(pady=6)
                if link:
                    lbl.configure(cursor="hand2")
                    lbl.bind("<Button-1>", lambda e: webbrowser.open(link))
                placed = True
            except Exception:
                placed = False
        if not placed:
            t = self.cfg.get("banner_text") or "· 배너/공지 영역 (관리자가 banner.png로 교체) ·"
            lbl = ctk.CTkLabel(self.banner, text=t, font=("Malgun Gothic", 12),
                               text_color=C["muted"])
            lbl.pack(pady=19)
            if link:
                lbl.configure(cursor="hand2")
                lbl.bind("<Button-1>", lambda e: webbrowser.open(link))

    # ---------- 입력 ----------
    def _build_inputs(self, p):
        c = self._section(p, "🎯", "기본 설정", C["accent"])
        top_row = ctk.CTkFrame(c, fg_color="transparent"); top_row.pack(fill="x", padx=16, pady=(2, 16))
        ctk.CTkLabel(top_row, text="계열", font=(FONT, 12), text_color=C["text"]).pack(side="left")
        self.gye_var = ctk.StringVar(value="자연")
        ctk.CTkSegmentedButton(top_row, values=["자연", "인문"], variable=self.gye_var,
            command=lambda _=None: self.recompute(), selected_color=C["accent"],
            selected_hover_color=C["accent"], fg_color=C["card2"], font=(FONT, 13)
            ).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(top_row, text="교육과정", font=(FONT, 12), text_color=C["text"]).pack(side="left")
        self.curriculum_var = ctk.StringVar(value="현행(2015)")
        ctk.CTkSegmentedButton(top_row, values=["현행(2015)", "2022 개정"],
                               variable=self.curriculum_var, command=self._on_curriculum_change,
                               fg_color=C["card2"], selected_color=C["purple"], font=(FONT, 12)).pack(side="left", padx=(8, 0))

        # 학생 정보 관리
        c2 = self._section(p, "👤", "학생 성적 저장/불러오기", C["green"], "현재 PC에만 저장됩니다")
        r1 = ctk.CTkFrame(c2, fg_color="transparent"); r1.pack(fill="x", padx=16, pady=(4,2))
        ctk.CTkLabel(r1, text="반", font=(FONT, 12)).pack(side="left")
        self.class_var = ctk.StringVar()
        ctk.CTkEntry(r1, textvariable=self.class_var, width=40).pack(side="left", padx=4)
        ctk.CTkLabel(r1, text="번호", font=(FONT, 12)).pack(side="left")
        self.num_var = ctk.StringVar()
        ctk.CTkEntry(r1, textvariable=self.num_var, width=40).pack(side="left", padx=4)
        ctk.CTkLabel(r1, text="이름", font=(FONT, 12)).pack(side="left")
        self.name_var = ctk.StringVar()
        ctk.CTkEntry(r1, textvariable=self.name_var, width=80).pack(side="left", padx=4)
        ctk.CTkButton(r1, text="저장", width=50, command=self._save_student_data, fg_color=C["accent"]).pack(side="left", padx=10)

        r2 = ctk.CTkFrame(c2, fg_color="transparent"); r2.pack(fill="x", padx=16, pady=(2,8))
        self.student_list_var = ctk.StringVar(value="저장된 학생 선택")
        self.student_combo = ctk.CTkOptionMenu(r2, variable=self.student_list_var, values=["선택 안 됨"], command=self._load_student_data, width=200)
        self.student_combo.pack(side="left", padx=(0, 10))
        ctk.CTkButton(r2, text="삭제", width=50, command=self._delete_student_data, fg_color=C["orange"]).pack(side="left")
        self._refresh_student_list()

        c = self._section(p, "📘", "내신 교과 등급", C["blue"], "사회·과학 추가·이름변경 가능")
        yr_row = ctk.CTkFrame(c, fg_color="transparent"); yr_row.pack(fill="x", padx=16, pady=(2, 2))
        ctk.CTkLabel(yr_row, text="학년", font=(FONT, 12), text_color=C["muted"]).pack(side="left", padx=(0, 6))
        self.year_seg = ctk.CTkSegmentedButton(yr_row, values=["1학년", "2학년", "3학년"],
            command=self._switch_year, selected_color=C["purple"], fg_color=C["card2"],
            font=(FONT, 13)); self.year_seg.set("1학년")
        self.year_seg.pack(side="left")
        sm_row = ctk.CTkFrame(c, fg_color="transparent"); sm_row.pack(fill="x", padx=16, pady=(2, 4))
        ctk.CTkLabel(sm_row, text="학기", font=(FONT, 12), text_color=C["muted"]).pack(side="left", padx=(0, 6))
        self.sem_seg = ctk.CTkSegmentedButton(sm_row, values=["1학기", "2학기"],
            command=self._switch_semester, selected_color=C["blue"],
            selected_hover_color=C["blue"], fg_color=C["card2"], font=(FONT, 13))
        self.sem_seg.set("1학기"); self.sem_seg.pack(side="left")
        
        t_row = ctk.CTkFrame(c, fg_color="transparent"); t_row.pack(fill="x", padx=16, pady=4)
        self.semester_title = ctk.CTkLabel(t_row, text="▶ 현재 입력 중: 1학년 1학기", font=("Malgun Gothic", 14, "bold"), text_color=C["blue"])
        self.semester_title.pack(side="left")
        yrow = ctk.CTkFrame(c, fg_color="transparent"); yrow.pack(fill="x", padx=16, pady=(0, 2))
        ctk.CTkLabel(yrow, text="아직 안 배운 학년:", font=(FONT, 11),
                     text_color=C["muted"]).pack(side="left", padx=(0, 6))
        self.year_off_vars = {}
        for y in ["2", "3"]:
            v = ctk.BooleanVar(value=not self.year_active[y])
            self.year_off_vars[y] = v
            ctk.CTkCheckBox(yrow, text=f"{y}학년 미이수", variable=v, font=(FONT, 11),
                checkbox_width=18, checkbox_height=18, fg_color=C["orange"],
                command=self._on_year_active).pack(side="left", padx=6)
        frow = ctk.CTkFrame(c, fg_color="transparent"); frow.pack(fill="x", padx=16, pady=(2, 0))
        self.five_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frow, text="5등급제 성적 (9등급으로 자동 환산)", variable=self.five_var,
            font=(FONT, 11), checkbox_width=18, checkbox_height=18, fg_color=C["accent"],
            command=self._on_five_scale).pack(side="left")
        self.five_note = ctk.CTkLabel(c, text="", font=(FONT, 10), text_color=C["orange"],
                                      wraplength=300, justify="left")
        self.five_note.pack(anchor="w", padx=16, pady=(0, 0))
        grid = ctk.CTkFrame(c, fg_color="transparent"); grid.pack(fill="x", padx=16, pady=(8, 4))
        h_row = ctk.CTkFrame(grid, fg_color="transparent"); h_row.pack(fill="x", pady=(0,4))
        ctk.CTkLabel(h_row, text="과목", width=64, font=(FONT, 11), text_color=C["muted"]).pack(side="left")
        ctk.CTkLabel(h_row, text="등급", width=48, font=(FONT, 11), text_color=C["muted"]).pack(side="left", padx=3)
        ctk.CTkLabel(h_row, text="성취도", width=48, font=(FONT, 11), text_color=C["muted"]).pack(side="left", padx=3)
        ctk.CTkLabel(h_row, text="원점수", width=48, font=(FONT, 11), text_color=C["muted"]).pack(side="left", padx=3)
        ctk.CTkLabel(h_row, text="시수", width=48, font=(FONT, 11), text_color=C["muted"]).pack(side="left", padx=3)

        for subj in [s for s in self.subjects if s["fixed"]]:
            row = ctk.CTkFrame(grid, fg_color="transparent"); row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=subj["name"], width=64, font=(FONT, 12), text_color=C["text"]).pack(side="left")
            eg = self._mini_entry(row, 48, ph="등급"); eg.pack(side="left", padx=3); self.grade_entries[id(subj)] = eg
            ea = self._mini_entry(row, 48, ph="A/B"); ea.pack(side="left", padx=3); self.ach_entries[id(subj)] = ea
            er = self._mini_entry(row, 48, ph="점수"); er.pack(side="left", padx=3); self.raw_entries[id(subj)] = er
            eu = self._mini_entry(row, 48, ph="시수"); eu.pack(side="left", padx=3); self.unit_entries[id(subj)] = eu
            for ex in [eg, ea, er, eu]: ex.bind("<KeyRelease>", lambda _=None: self._queue_recompute())
        self.elec_frame = ctk.CTkFrame(c, fg_color="transparent")
        self.elec_frame.pack(fill="x", padx=16, pady=(2, 4))
        self._rebuild_electives()
        ctk.CTkLabel(c, text="기본 학년 비중 (대학 자체 기준이 우선 적용됨)", font=(FONT, 11),
                     text_color=C["muted"]).pack(anchor="w", padx=16, pady=(6, 2))
        wrow = ctk.CTkFrame(c, fg_color="transparent"); wrow.pack(fill="x", padx=16, pady=(0, 10))
        for y in ["1", "2", "3"]:
            ctk.CTkLabel(wrow, text=f"{y}학년", font=(FONT, 11),
                         text_color=C["muted"]).pack(side="left", padx=(0, 2))
            e = self._mini_entry(wrow, 40); e.insert(0, str(int(self.student["weights"][y])))
            e.pack(side="left", padx=(0, 10)); e.bind("<KeyRelease>", lambda _=None: self._on_weight())
            self.weight_entries[y] = e
        self.weight_note = ctk.CTkLabel(c, text="", font=(FONT, 11), text_color=C["green"])
        self.weight_note.pack(anchor="w", padx=16, pady=(0, 12))
        self._load_year_entries("1-1")


        c = self._section(p, "📝", "수능(모의) 등급", C["purple"], "탐구는 선택과목별로 추가")
        self.tamgu_note = ctk.CTkLabel(c, text="", font=(FONT, 11), text_color=C["orange"])
        self.tamgu_note.pack(anchor="w", padx=16, pady=(0, 2))

        grid = ctk.CTkFrame(c, fg_color="transparent"); grid.pack(fill="x", padx=16, pady=(2, 4))
        su = self.student["suneung"]
        for i, a in enumerate(["국어", "수학", "영어", "한국사"]):
            r, col = divmod(i, 2)
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=r, column=col, sticky="ew", padx=4, pady=4)
            grid.grid_columnconfigure(col, weight=1)
            ctk.CTkLabel(cell, text=a, width=48, font=(FONT, 12),
                         text_color=C["text"]).pack(side="left")
            e = self._mini_entry(cell, 64); e.insert(0, str(su[a])); e.pack(side="left", padx=6)
            e.bind("<KeyRelease>", lambda _=None: self._queue_recompute()); self.suneung_entries[a] = e
        mrow = ctk.CTkFrame(c, fg_color="transparent"); mrow.pack(fill="x", padx=16, pady=(2, 6))
        ctk.CTkLabel(mrow, text="수학 선택", font=(FONT, 12), text_color=C["text"]).pack(side="left")
        self.math_var = ctk.StringVar(value="미적분")
        self.math_menu = ctk.CTkOptionMenu(mrow, values=["미적분", "기하", "확률과통계"], variable=self.math_var,
            command=lambda _=None: self.recompute(), width=130, fg_color=C["card2"],
            button_color=C["accent"], font=(FONT, 12))
        self.math_menu.pack(side="right")
        ctk.CTkLabel(c, text="탐구 (선택과목 · 이름/등급/백분위)", font=(FONT, 11),
                     text_color=C["muted"]).pack(anchor="w", padx=16, pady=(4, 2))
        self.tamgu_frame = ctk.CTkFrame(c, fg_color="transparent")
        self.tamgu_frame.pack(fill="x", padx=16, pady=(0, 12))
        self._rebuild_tamgu()

        c = self._section(p, "🎓", "정시 백분위 (선택)", C["green"], "탐구 백분위는 위 탐구칸에 입력")
        bgrid = ctk.CTkFrame(c, fg_color="transparent"); bgrid.pack(fill="x", padx=16, pady=(2, 14))
        for a in ["국어", "수학"]:
            cell = ctk.CTkFrame(bgrid, fg_color="transparent"); cell.pack(side="left", padx=8)
            ctk.CTkLabel(cell, text=a, width=36, font=(FONT, 12),
                         text_color=C["text"]).pack(side="left")
            e = self._mini_entry(cell, 66, "0~100"); e.pack(side="left", padx=4)
            e.bind("<KeyRelease>", lambda _=None: self._queue_recompute())
            self.baekbunwi_entries[a] = e


    def _get_students_file(self):
        import os
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "students.json")

    def _refresh_student_list(self):
        import json, os
        f = self._get_students_file()
        if os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as file:
                    data = json.load(file)
                keys = list(data.keys())
                if keys:
                    self.student_combo.configure(values=keys)
                    return
            except Exception:
                pass
        self.student_combo.configure(values=["저장된 학생 없음"])
        self.student_list_var.set("저장된 학생 선택")

    def _save_student_data(self):
        import json, os
        c, n, nm = self.class_var.get().strip(), self.num_var.get().strip(), self.name_var.get().strip()
        if not c or not n or not nm:
            return
        key = f"{c}반 {n}번 {nm}"
        self._save_year_entries(self.active_semester)
        self._save_tamgu()
        f = self._get_students_file()
        data = {}
        if os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as file: data = json.load(file)
            except: pass
        
        # We must serialize self.subjects, suneung, weights
        def _clean_dict(d):
            return {k: v for k, v in d.items() if not k.startswith("_")}
        
        st_data = {
            "gye": self.gye_var.get(),
            "curr": self.curriculum_var.get(),
            "five": self.five_var.get(),
            "year_active": getattr(self, "year_active", {}),
            "weights": getattr(self.student, "weights", {}),
            "subjects": self.subjects,
            "suneung": getattr(self.student, "suneung", {})
        }
        data[key] = st_data
        with open(f, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        self._refresh_student_list()
        self.student_list_var.set(key)

    def _load_student_data(self, key):
        import json, os
        if "선택" in key or "없음" in key: return
        f = self._get_students_file()
        if not os.path.exists(f): return
        try:
            with open(f, "r", encoding="utf-8") as file: data = json.load(file)
            st = data.get(key)
            if not st: return
            self.gye_var.set(st.get("gye", "자연"))
            self.curriculum_var.set(st.get("curr", "현행(2015)"))
            self._on_curriculum_change(self.curriculum_var.get())
            self.five_var.set(st.get("five", False))
            if hasattr(self, "year_active"):
                for y, active in st.get("year_active", {}).items():
                    self.year_active[y] = active
                    if y in self.year_off_vars: self.year_off_vars[y].set(not active)
            for y, w in st.get("weights", {}).items():
                if y in getattr(self, "weight_entries", {}):
                    self.weight_entries[y].delete(0, "end")
                    self.weight_entries[y].insert(0, str(w))
            self.subjects = st.get("subjects", [])
            for k, v in st.get("suneung", {}).items():
                if k in getattr(self, "suneung_entries", {}):
                    self.suneung_entries[k].delete(0, "end")
                    self.suneung_entries[k].insert(0, str(v))
            
            # extract class/num/name from key
            import re
            m = re.match(r"(\d+)반\s+(\d+)번\s+(.+)", key)
            if m:
                self.class_var.set(m.group(1))
                self.num_var.set(m.group(2))
                self.name_var.set(m.group(3))
                
            self._rebuild_electives()
            self._load_year_entries(self.active_semester)
            self.recompute()
        except Exception as e:
            print("Load error:", e)

    def _delete_student_data(self):
        import json, os
        key = self.student_list_var.get()
        if "선택" in key or "없음" in key: return
        f = self._get_students_file()
        if os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as file: data = json.load(file)
                if key in data:
                    del data[key]
                    with open(f, "w", encoding="utf-8") as file: json.dump(data, file, ensure_ascii=False)
            except: pass
        self._refresh_student_list()
        self.class_var.set(""); self.num_var.set(""); self.name_var.set("")

    def _on_curriculum_change(self, val):
        if val == "2022 개정":
            self.math_menu.configure(values=["공통(선택없음)"])
            self.math_var.set("공통(선택없음)")
            self.tamgu_note.configure(text="* 2022 개정: 통합사회/통합과학 공통")
            self.tamgu = [{"name": "통합사회", "g": "3", "pct": ""}, {"name": "통합과학", "g": "3", "pct": ""}]
        else:
            self.math_menu.configure(values=["미적분", "기하", "확률과통계"])
            if self.math_var.get() not in ["미적분", "기하", "확률과통계"]:
                self.math_var.set("미적분")
            self.tamgu_note.configure(text="")
        self._rebuild_tamgu()
        self.recompute()

    def _rebuild_electives(self):
        for w in self.elec_frame.winfo_children(): w.destroy()
        yr = self.active_semester if hasattr(self, 'active_semester') else (self.active_year if hasattr(self, 'active_year') else '1')
        for subj in [s for s in self.subjects if not s["fixed"]]:
            row = ctk.CTkFrame(self.elec_frame, fg_color=C["card2"], corner_radius=8); row.pack(fill="x", pady=2)
            ne = ctk.CTkEntry(row, width=54, fg_color=C["card"], border_color=C["line"], font=(FONT, 12))
            ne.insert(0, subj["name"]); ne.pack(side="left", padx=(8,0), pady=4)
            ne.bind("<KeyRelease>", lambda _=None, s=subj, w=ne: (s.update(name=w.get()), self._queue_recompute()))
            
            eg = self._mini_entry(row, 44, ph="등급"); eg.pack(side="left", padx=3); self.grade_entries[id(subj)] = eg
            ea = self._mini_entry(row, 44, ph="A/B"); ea.pack(side="left", padx=3); self.ach_entries[id(subj)] = ea
            er = self._mini_entry(row, 44, ph="점수"); er.pack(side="left", padx=3); self.raw_entries[id(subj)] = er
            eu = self._mini_entry(row, 44, ph="시수"); eu.pack(side="left", padx=3); self.unit_entries[id(subj)] = eu
            for ex in [eg, ea, er, eu]: ex.bind("<KeyRelease>", lambda _=None: self._queue_recompute())
            
            ctk.CTkButton(row, text="✕", width=24, height=24, fg_color=C["card"], hover_color=C["red"], font=(FONT, 11), text_color=C["muted"], command=lambda s=subj: self._remove_subject(s)).pack(side="right", padx=6)
        
        add = ctk.CTkFrame(self.elec_frame, fg_color="transparent"); add.pack(fill="x", pady=(4, 2))
        ctk.CTkButton(add, text="＋ 일반", width=90, height=26, font=(FONT, 11), fg_color=C["card2"], hover_color=C["blue"], command=lambda: self._add_subject("일반")).pack(side="left", padx=(0, 6))
        
        self._load_year_entries(yr)
        
    def _add_subject(self, kind):
        self._save_year_entries(self.active_semester)
        n = sum(1 for s in self.subjects if s.get("kind") == kind)
        self.subjects.append({"name": f"{kind}{n+1}", "fixed": False, "kind": kind,
                              "year": {"1-1": 3.0, "1-2": 3.0, "2-1": 3.0, "2-2": 3.0, "3-1": 3.0, "3-2": 3.0},
                              "units": {"1-1": 3, "1-2": 3, "2-1": 3, "2-2": 3, "3-1": 3, "3-2": 3}})
        self._rebuild_electives(); self.recompute()

    def _remove_subject(self, subj):
        self._save_year_entries(self.active_semester)
        self.subjects = [s for s in self.subjects if s is not subj]
        self.year_entries.pop(id(subj), None)
        self._rebuild_electives(); self.recompute()

    def _rebuild_tamgu(self):
        for w in self.tamgu_frame.winfo_children():
            w.destroy()
        self.tamgu_widgets = []
        is_2022 = (getattr(self, "curriculum_var", None) and self.curriculum_var.get() == "2022 개정")
        for t in self.tamgu:
            row = ctk.CTkFrame(self.tamgu_frame, fg_color=C["card2"], corner_radius=8)
            row.pack(fill="x", pady=2)
            ne = ctk.CTkEntry(row, width=100, fg_color=C["card"], border_color=C["line"],
                              font=(FONT, 12)); ne.insert(0, t["name"])
            if is_2022: ne.configure(state="disabled")
            ne.pack(side="left", padx=(8, 4), pady=5)
            ne.bind("<KeyRelease>", lambda _=None, tt=t, w=ne: (tt.update(name=w.get()),
                                                                self._queue_recompute()))
            ctk.CTkLabel(row, text="등급", font=(FONT, 10), text_color=C["muted"]).pack(side="left")
            ge = self._mini_entry(row, 40); ge.insert(0, t["g"]); ge.pack(side="left", padx=3)
            ge.bind("<KeyRelease>", lambda _=None: self._queue_recompute())
            ctk.CTkLabel(row, text="백분위", font=(FONT, 10), text_color=C["muted"]).pack(side="left")
            pe = self._mini_entry(row, 48, "0~100"); pe.insert(0, t.get("pct", ""))
            pe.pack(side="left", padx=3); pe.bind("<KeyRelease>", lambda _=None: self._queue_recompute())
            self.tamgu_widgets.append((t, ne, ge, pe))
            if not is_2022:
                ctk.CTkButton(row, text="✕", width=24, height=24, fg_color=C["card"],
                    hover_color=C["red"], font=(FONT, 11), text_color=C["muted"],
                    command=lambda tt=t: self._remove_tamgu(tt)).pack(side="right", padx=6)
        if not is_2022:
            ctk.CTkButton(self.tamgu_frame, text="＋ 탐구 과목 추가", height=26, font=(FONT, 11),
                fg_color=C["card2"], hover_color=C["purple"],
                command=self._add_tamgu).pack(fill="x", pady=(4, 0))

    def _save_tamgu(self):
        for t, ne, ge, pe in getattr(self, "tamgu_widgets", []):
            t["name"] = ne.get(); t["g"] = ge.get(); t["pct"] = pe.get()

    def _add_tamgu(self):
        self._save_tamgu()
        self.tamgu.append({"name": f"탐구{len(self.tamgu)+1}", "g": "", "pct": ""})
        self._rebuild_tamgu(); self.recompute()

    def _remove_tamgu(self, t):
        self._save_tamgu()
        self.tamgu = [x for x in self.tamgu if x is not t]
        self._rebuild_tamgu(); self.recompute()

    def _load_year_entries(self, yr):
        for subj in self.subjects:
            sid = id(subj)
            if sid in self.grade_entries: self.grade_entries[sid].delete(0, "end"); self.grade_entries[sid].insert(0, str(subj["grade"].get(yr, "")))
            if sid in self.ach_entries: self.ach_entries[sid].delete(0, "end"); self.ach_entries[sid].insert(0, str(subj["ach"].get(yr, "")))
            if sid in self.raw_entries: self.raw_entries[sid].delete(0, "end"); self.raw_entries[sid].insert(0, str(subj["raw"].get(yr, "")))
            if sid in self.unit_entries: self.unit_entries[sid].delete(0, "end"); self.unit_entries[sid].insert(0, str(subj["unit"].get(yr, "")))

    def _save_year_entries(self, yr):
        for subj in self.subjects:
            sid = id(subj)
            if sid in self.grade_entries: subj["grade"][yr] = self.grade_entries[sid].get().strip()
            if sid in self.ach_entries: subj["ach"][yr] = self.ach_entries[sid].get().strip().upper()
            if sid in self.raw_entries: subj["raw"][yr] = self.raw_entries[sid].get().strip()
            if sid in self.unit_entries: subj["unit"][yr] = self.unit_entries[sid].get().strip()

    def _switch_year(self, val):
        self._save_year_entries(self.active_semester)
        y = {"1학년": "1", "2학년": "2", "3학년": "3"}[val]
        s = self.sem_seg.get().replace("학기", "")
        self.active_semester = f"{y}-{s}"
        self._load_year_entries(self.active_semester)
        if hasattr(self, "semester_title"):
            ys, ss = self.active_semester.split("-")
            self.semester_title.configure(text=f"▶ 현재 입력 중: {ys}학년 {ss}학기")
        self._rebuild_electives()

    def _switch_semester(self, val):
        self._save_year_entries(self.active_semester)
        y = {"1학년": "1", "2학년": "2", "3학년": "3"}[self.year_seg.get()]
        s = val.replace("학기", "")
        self.active_semester = f"{y}-{s}"
        self._load_year_entries(self.active_semester)
        if hasattr(self, "semester_title"):
            ys, ss = self.active_semester.split("-")
            self.semester_title.configure(text=f"▶ 현재 입력 중: {ys}학년 {ss}학기")
        self._rebuild_electives()

    def _on_year_active(self):
        for y, v in self.year_off_vars.items():
            self.year_active[y] = not v.get()
        self.recompute()

    def _on_five_scale(self):
        on = self.five_var.get()
        self.five_note.configure(
            text=("⚠ 위 수치는 근사값입니다. 참고용으로만 활용하시고, 정확한 값을 "
                  "원하면 다른 프로그램을 이용하세요.") if on else "")
        self.recompute()

    def _apply_font_scale(self, delta):
        """실리 위주의 즉각적 폰트 조절 (렉 유발하는 set_widget_scaling 대신 초경량 Style 업데이트)."""
        self.font_scale = max(0.8, min(1.6, round(self.font_scale + delta, 1)))
        self._do_font_scale()

    def _do_font_scale(self):
        try:
            f_size = max(9, int(11 * self.font_scale))
            h_size = max(10, int(11 * self.font_scale))
            r_height = max(24, int(30 * self.font_scale))
            style = ttk.Style()
            style.configure("J.Treeview", font=("Malgun Gothic", f_size), rowheight=r_height)
            style.configure("J.Treeview.Heading", font=("Malgun Gothic", h_size, "bold"))
        except Exception:
            pass

    def _queue_recompute(self, ms=150):
        """키 입력 시 연속 재계산 렉 방지 디바운싱."""
        if hasattr(self, "_recompute_timer") and self._recompute_timer:
            self.after_cancel(self._recompute_timer)
        self._recompute_timer = self.after(ms, self.recompute)

    def _on_weight(self):
        for y, e in self.weight_entries.items():
            try: self.student["weights"][y] = max(0.0, float(e.get()))
            except ValueError: pass
        self._queue_recompute(100)

    def _on_univ_change(self, *_):
        uv = self.univ_var.get()
        if uv != "전체 대학":
            u = next((d for d in self.univs.values() if d["name"] == uv), None)
            gw = (u or {}).get("grade_weights")
            if gw and gw.get("weights"):
                w = gw["weights"]
                for y in ["1", "2", "3"]:
                    self.student["weights"][y] = float(w.get(y, 1))
                    self.weight_entries[y].delete(0, "end")
                    self.weight_entries[y].insert(0, str(int(float(w.get(y, 1)))))
                w_str = " ".join(f"{y}학년:{int(float(w.get(y, 1)))}%" for y in ["1", "2", "3"])
                self.weight_note.configure(
                    text=f"✓ '{uv}' 반영비율 자동적용: {w_str}", text_color=C["green"])
            else:
                self.weight_note.configure(text="학년비중 정보 미검출 — 수동 입력",
                                           text_color=C["muted"])
        else:
            self.weight_note.configure(text="")
        self.recompute()

    # ---------- 스탯/차트/필터/표 ----------
    def _build_stats(self, p):
        self.stats = ctk.CTkFrame(p, fg_color="transparent")
        self.stats.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for i in range(3):
            self.stats.grid_columnconfigure(i, weight=1)
        self.stat_labels = {}
        for i, (k, col) in enumerate([("대학", C["blue"]), ("모집단위", C["purple"]),
                                      ("지원가능", C["green"])]):
            card = self._card(self.stats); card.grid(row=0, column=i, sticky="ew", padx=6)
            ctk.CTkLabel(card, text=k, font=("Malgun Gothic", 12), text_color=C["muted"]
                         ).pack(anchor="w", padx=16, pady=(12, 0))
            v = ctk.CTkLabel(card, text="-", font=("Malgun Gothic", 24, "bold"), text_color=col)
            v.pack(anchor="w", padx=16, pady=(0, 12)); self.stat_labels[k] = v

    def _build_chart(self, p):
        card = self._card(p); card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(card, text="합격 가능성 밴드 분포", font=("Malgun Gothic", 13, "bold"),
                     text_color=C["muted"]).pack(anchor="w", padx=18, pady=(12, 2))
        self.canvas = tk.Canvas(card, height=150, bg=C["card"], highlightthickness=0)
        self.canvas.pack(fill="x", padx=16, pady=(0, 12))

    def _draw_chart(self):
        cv = self.canvas; cv.delete("all")
        W = cv.winfo_width()
        if W < 100:
            W = 800
        cnt = {}
        for r in self.results:
            cnt[r["band"]] = cnt.get(r["band"], 0) + 1
        order = [b for b in BAND_ORDER if b in cnt]
        if not order:
            return
        mx = max(cnt[b] for b in order)
        y, bh, gap = 6, 20, 8
        for b in order:
            w = int((W - 120) * cnt[b] / mx) if mx else 0
            cv.create_text(56, y + bh / 2, text=b, fill=C["muted"], anchor="e",
                           font=("Malgun Gothic", 10))
            cv.create_rectangle(64, y, 64 + w, y + bh, fill=BAND_COLOR.get(b, C["gray"]),
                                outline="")
            cv.create_text(64 + w + 8, y + bh / 2, text=str(cnt[b]), fill=C["text"],
                           anchor="w", font=("Malgun Gothic", 10))
            y += bh + gap
        cv.configure(height=y + 4)

    def _build_filters(self, p):
        bar = self._card(p); bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        top = ctk.CTkFrame(bar, fg_color="transparent"); top.pack(fill="x", padx=14, pady=(12, 0))
        years = sorted({u.get("year") for u in self.univs.values() if u.get("year")}, reverse=True)
        yv = ["전체"] + [f"{y}학년도" for y in years]
        self.year_var = ctk.StringVar(value=(yv[1] if len(yv) > 1 else "전체"))
        ctk.CTkLabel(top, text="학년도", font=("Malgun Gothic", 12),
                     text_color=C["muted"]).pack(side="left", padx=(0, 6))
        self.year_filter_seg = ctk.CTkSegmentedButton(top, values=yv, variable=self.year_var,
            command=lambda _=None: self.recompute(), selected_color=C["purple"],
            fg_color=C["card2"], font=("Malgun Gothic", 12))
        self.year_filter_seg.pack(side="left")
        self.adm_var = ctk.StringVar(value="전체")
        ctk.CTkLabel(top, text="구분", font=("Malgun Gothic", 12),
                     text_color=C["muted"]).pack(side="left", padx=(16, 6))
        ctk.CTkSegmentedButton(top, values=["전체", "수시", "정시"], variable=self.adm_var,
            command=lambda _=None: self.recompute(), selected_color=C["green"],
            fg_color=C["card2"], font=("Malgun Gothic", 12)).pack(side="left")
        inner = ctk.CTkFrame(bar, fg_color="transparent"); inner.pack(fill="x", padx=14, pady=12)
        names = ["전체 대학"] + sorted(u["name"] for u in self.univs.values())
        self.univ_var = ctk.StringVar(value="전체 대학")
        self.univ_menu = ctk.CTkOptionMenu(inner, values=names, variable=self.univ_var,
            command=self._on_univ_change, width=190, fg_color=C["card2"],
            button_color=C["blue"], font=("Malgun Gothic", 13))
        self.univ_menu.pack(side="left")
        self.cat_var = ctk.StringVar(value="전체")
        ctk.CTkSegmentedButton(inner, values=["전체", "교과", "종합", "논술", "실기"],
            variable=self.cat_var, command=lambda _=None: self.recompute(),
            selected_color=C["blue"], fg_color=C["card2"],
            font=("Malgun Gothic", 12)).pack(side="left", padx=10)
        self.search = ctk.CTkEntry(inner, placeholder_text="학과 검색", width=160,
            fg_color=C["card2"], border_color=C["line"], font=("Malgun Gothic", 13))
        self.search.pack(side="left"); self.search.bind("<KeyRelease>", lambda _=None: self._queue_recompute(120))
        self.only_ok = ctk.CTkCheckBox(inner, text="가능만", font=("Malgun Gothic", 12),
            command=self.recompute, fg_color=C["blue"]); self.only_ok.pack(side="right")

    def _build_table(self, p):
        card = self._card(p); card.grid(row=3, column=0, sticky="nsew")
        card.grid_rowconfigure(0, weight=1); card.grid_columnconfigure(0, weight=1)
        style = ttk.Style(); style.theme_use("clam")
        style.configure("J.Treeview", background=C["card"], fieldbackground=C["card"],
                        foreground=C["text"], rowheight=30, borderwidth=0, font=("Malgun Gothic", 11))
        style.configure("J.Treeview.Heading", background=C["card2"], foreground=C["muted"],
                        borderwidth=0, font=("Malgun Gothic", 11, "bold"))
        style.map("J.Treeview", background=[("selected", C["blue"])], foreground=[("selected", "#fff")])
        cols = ("대학", "학과", "유형", "밴드", "판정", "정원", "출처")
        self.tree = ttk.Treeview(card, columns=cols, show="headings", style="J.Treeview")
        widths = {"대학": 110, "학과": 220, "유형": 60, "밴드": 70, "판정": 100, "정원": 55, "출처": 70}
        for cn in cols:
            self.tree.heading(cn, text=cn)
            self.tree.column(cn, width=widths[cn], anchor=("center" if cn in
                             ("유형", "밴드", "판정", "정원", "출처") else "w"))
        for b, col in BAND_COLOR.items():
            self.tree.tag_configure(b, foreground=col)
        vs = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        vs.grid(row=0, column=1, sticky="ns", pady=10)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-1>", self._on_click_cell)

        # 학과 특수기호 범례 안내 바
        legend = ctk.CTkFrame(card, fg_color="transparent")
        legend.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 6))
        ctk.CTkLabel(legend, text="💡 학과명 기호(*, ★, † 등): 각 대학 모집요강 표의 세부 각주(Footnote) 표시입니다. [출처 열 클릭] 시 요강 원문 각주를 바로 확인할 수 있습니다.",
                     font=("Malgun Gothic", 11), text_color=C["muted"]).pack(side="left")

    # ---------- 로직 ----------
    def _collect_student(self):
        self._save_year_entries(self.active_semester)
        self._save_tamgu()
        st = {"gyeyeol": self.gye_var.get()}
        w = self.student["weights"]
        yrs = [y for y in ["1", "2", "3"] if self.year_active.get(y, True)]
        tw = sum(w[y] for y in yrs) or 1
        conv = engine.convert_5to9 if self.five_var.get() else (lambda g: g)
        
        naesin = {}
        for subj in self.subjects:
            nm = (subj["name"] or "").strip()
            if not nm:
                continue
            weighted_sum = 0
            total_units = 0
            valid_semesters = 0
            yearly_grades = {}
            for y in yrs:
                s1, s2 = f"{y}-1", f"{y}-2"
                
                def get_sem(sem):
                    g = subj["grade"].get(sem, "")
                    a = subj["ach"].get(sem, "")
                    r = subj["raw"].get(sem, "")
                    u = subj["unit"].get(sem, "")
                    score = None
                    if g:
                        try: score = conv(float(g))
                        except ValueError: pass
                    if score is None and a in ["A", "B", "C"]:
                        score = engine.convert_achievement(a)
                    u_val = 1
                    if u:
                        try: u_val = int(u)
                        except ValueError: pass
                    return score, u_val

                score1, u1 = get_sem(s1)
                score2, u2 = get_sem(s2)
                
                sem_sum = 0; sem_count = 0; sem_u = 0
                if score1 is not None: sem_sum += score1; sem_count += 1; sem_u += u1
                if score2 is not None: sem_sum += score2; sem_count += 1; sem_u += u2
                
                if sem_count > 0:
                    year_avg = sem_sum / sem_count
                    yearly_grades[y] = year_avg
                    weighted_sum += year_avg * w[y]
                    total_units += sem_u
                    valid_semesters += 1
                    
            if valid_semesters > 0:
                weighted_avg = round(weighted_sum / tw, 2)
                naesin[nm] = {"grade": weighted_avg, "units": total_units, "yearly_grades": yearly_grades, "raw_data": subj["raw"], "ach_data": subj["ach"]}
            
        st["naesin"] = naesin
        su = dict(self.student["suneung"])
        for a, e in self.suneung_entries.items():
            try: su[a] = int(float(e.get()))
            except ValueError: pass
        tg = []
        for t in self.tamgu:
            try: tg.append(int(float(t["g"])))
            except (ValueError, TypeError): pass
        tg.sort()
        su["탐구1"] = tg[0] if tg else 3
        su["탐구2"] = tg[1] if len(tg) > 1 else (tg[0] if tg else 3)
        su["수학선택"] = self.math_var.get()
        st["suneung"] = su
        def _f(v):
            try: return float(v) if str(v).strip() else None
            except ValueError: return None
        bb = {a: _f(e.get()) for a, e in self.baekbunwi_entries.items()}
        tp = [x for x in (_f(t.get("pct")) for t in self.tamgu) if x is not None]
        bb["탐구"] = round(sum(tp) / len(tp), 1) if tp else None
        st["baekbunwi"] = bb
        cat = self.cat_var.get()
        st["categories"] = [] if cat == "전체" else [cat]
        return st

    def recompute(self):
        if not self.univs:
            return
        st = self._collect_student()
        uv = self.univ_var.get()
        code = [c for c, u in self.univs.items() if u["name"] == uv] if uv != "전체 대학" else None
        res = engine.run(st, univs=self.univs, codes=code)
        yr = self.year_var.get()
        if yr != "전체":
            y = int("".join(ch for ch in yr if ch.isdigit()) or 0)
            res = [r for r in res if r.get("year") == y]
        adm = self.adm_var.get()
        if adm != "전체":
            res = [r for r in res if (r.get("admission_type") or "수시") == adm]
        cat = self.cat_var.get()
        if cat != "전체":
            res = [r for r in res if cat in (r.get("category") or "")]
        kw = self.search.get().strip()
        if kw:
            res = [r for r in res if kw.lower() in (r["unit"] or "").lower()]
        vlist = []
        for r in res:
            v = engine.summarize(r)
            if self.only_ok.get() and v != "지원가능":
                continue
            r["_verdict"] = v; vlist.append(r)
        bo = {b: i for i, b in enumerate(BAND_ORDER)}
        vlist.sort(key=lambda r: (bo.get(r["band"], 9), r["univ"], r["unit"]))
        self.results = vlist
        self._fill_tree(); self._update_stats(); self._draw_chart()

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.results):
            src = f"p.{r.get('unit_page') or r.get('rule_page') or r.get('ipgyeol_page') or '-'}"
            self.tree.insert("", "end", iid=str(i), tags=(r["band"],),
                values=(r["univ"], r["unit"], r["category"], r["band"], r["_verdict"],
                        r.get("count") or "-", src))

    def _update_stats(self):
        self.stat_labels["대학"].configure(text=str(len(self.univs)))
        self.stat_labels["모집단위"].configure(text=str(len(self.results)))
        self.stat_labels["지원가능"].configure(
            text=str(sum(1 for r in self.results if r["_verdict"] == "지원가능")))

    def _on_click_cell(self, event):
        col = self.tree.identify_column(event.x); rowid = self.tree.identify_row(event.y)
        if rowid and col == "#7":
            self.open_source(self.results[int(rowid)])

    def _on_double(self, event):
        col = self.tree.identify_column(event.x); rowid = self.tree.identify_row(event.y)
        if rowid and col != "#7":
            self.show_detail(self.results[int(rowid)])

    # ---------- 상세 ----------
    def show_detail(self, r):
        same = [x for x in self.results if x["univ"] == r["univ"] and x["unit"] == r["unit"]] or [r]
        win = self._top(); win.title(f"{r['univ']} · {r['unit']}")
        win.geometry("760x680"); win.configure(fg_color=C["bg"]); win.resizable(True, True)
        head = ctk.CTkFrame(win, fg_color=C["card"], corner_radius=0); head.pack(fill="x")
        ctk.CTkLabel(head, text=r["univ"], font=("Malgun Gothic", 14), text_color=C["muted"]
                     ).pack(anchor="w", padx=20, pady=(14, 0))
        ctk.CTkLabel(head, text=r["unit"], font=("Malgun Gothic", 22, "bold"), text_color=C["text"]
                     ).pack(anchor="w", padx=20, pady=(0, 4))
        info = f"{r.get('gyeyeol') or '-'}계열"
        if r.get("count"): info += f"  ·  정원 {r['count']}명"
        if r.get("college"): info += f"  ·  {r['college']}"
        u_name = r.get("unit", "")
        sym_badges = []
        if "*" in u_name or "†" in u_name:
            sym_badges.append("🎓 교직과정 설치학과")
        if "★" in u_name or "◆" in u_name:
            sym_badges.append("🚀 첨단·신설학과")
        if "**" in u_name or "***" in u_name:
            sym_badges.append("⚡ 별도 수능최저/특수선발")

        if sym_badges:
            badge_row = ctk.CTkFrame(head, fg_color="transparent")
            badge_row.pack(anchor="w", padx=20, pady=(0, 8))
            for b_txt in sym_badges:
                b_frame = ctk.CTkFrame(badge_row, fg_color=C["card2"], corner_radius=6)
                b_frame.pack(side="left", padx=(0, 6))
                ctk.CTkLabel(b_frame, text=b_txt, font=("Malgun Gothic", 11, "bold"),
                             text_color=C["blue"]).pack(padx=8, pady=2)

        ctk.CTkLabel(head, text=info, font=("Malgun Gothic", 12), text_color=C["muted"]
                     ).pack(anchor="w", padx=20, pady=(0, 12))
        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(body, text="진학 방법 (전형별)", font=("Malgun Gothic", 14, "bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(0, 8))
        for x in same:
            card = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=14,
                                border_width=1, border_color=C["line"]); card.pack(fill="x", pady=6)
            top = ctk.CTkFrame(card, fg_color="transparent"); top.pack(fill="x", padx=16, pady=(12, 2))
            ctk.CTkLabel(top, text=f"{x['category']}전형", font=("Malgun Gothic", 15, "bold"),
                         text_color=C["blue"]).pack(side="left")
            ctk.CTkLabel(top, text=f"  {x['band']}", font=("Malgun Gothic", 13, "bold"),
                         text_color=BAND_COLOR.get(x["band"], C["gray"])).pack(side="left", padx=6)
            ctk.CTkLabel(top, text=x["_verdict"], font=("Malgun Gothic", 12),
                         text_color=C["muted"]).pack(side="right")
            req = x.get("rule_sentence") or x.get("rule_label") or x["suneung"].get("label") \
                or "수능최저 미적용(또는 정보 없음)"
            ctk.CTkLabel(card, text="수능최저: " + req, font=("Malgun Gothic", 12), text_color=C["text"],
                         wraplength=630, justify="left").pack(anchor="w", padx=16, pady=(2, 2))
            ctk.CTkLabel(card, text="충족 여부: " + x["suneung"].get("detail", "-"),
                         font=("Malgun Gothic", 12), text_color=C["muted"], wraplength=630,
                         justify="left").pack(anchor="w", padx=16, pady=(0, 2))
            if features.IPGYEOL_ENABLED and x.get("ipgyeol_naesin"):
                if x.get("ipgyeol_low") is not None:
                    ip_txt = (f"📊 합격 내신컷: {x['ipgyeol_naesin']}등급  "
                              f"(합격 최저 {x['ipgyeol_low']}등급, {x.get('ipgyeol_type','')})")
                else:
                    ip_txt = f"📊 합격 내신컷: {x['ipgyeol_naesin']}등급  ({x.get('ipgyeol_type','')})"
                ctk.CTkLabel(card, text=ip_txt,
                             font=("Malgun Gothic", 12, "bold"), text_color=C["green"]
                             ).pack(anchor="w", padx=16, pady=(2, 0))
            # 어디가(대입정보포털) 전년도 결과공개
            ed = x.get("eodiga") or []
            if ed:
                yr = x.get("eodiga_year") or ""
                box = ctk.CTkFrame(card, fg_color=C["card2"], corner_radius=10)
                box.pack(fill="x", padx=16, pady=(4, 4))
                ctk.CTkLabel(box, text=f"🔎 어디가 전년도({yr}) 결과공개 · 공식 발표",
                             font=("Malgun Gothic", 12, "bold"), text_color=C["blue"]
                             ).pack(anchor="w", padx=12, pady=(8, 2))
                for e in ed[:8]:
                    lab = (e.get("label") or "").replace("학생부교과", "").replace("학생부종합", "종합")
                    parts = [lab.strip("()") or "전형"]
                    if e.get("competition") is not None:
                        parts.append(f"경쟁률 {e['competition']}:1")
                    if e.get("chungwon") is not None:
                        parts.append(f"충원 {int(e['chungwon'])}명")
                    if e.get("grade70") is not None:
                        cut = f"70%컷 {e['grade70']}등급"
                        if e.get("score70") is not None:
                            cut += f"(환산 {e['score70']})"
                        if e.get("grade50") is not None:
                            cut += f" · 50%컷 {e['grade50']}등급"
                        parts.append(cut)
                    else:
                        parts.append("입시결과 미제출")
                    ctk.CTkLabel(box, text="• " + "  ·  ".join(parts),
                                 font=("Malgun Gothic", 11), text_color=C["text"],
                                 wraplength=620, justify="left").pack(anchor="w", padx=14, pady=(0, 1))
                ctk.CTkLabel(box, text="※ 70%컷=합격자 70% 지점 성적(낮을수록 우수). 전년도 기준·참고용.",
                             font=("Malgun Gothic", 10), text_color=C["muted"]
                             ).pack(anchor="w", padx=14, pady=(2, 8))
            # 정시(수능 백분위) 결과
            js = x.get("js") or {}
            if js:
                yr = x.get("eodiga_year") or js.get("year") or ""
                box = ctk.CTkFrame(card, fg_color=C["card2"], corner_radius=10)
                box.pack(fill="x", padx=16, pady=(4, 4))
                ctk.CTkLabel(box, text=f"🎯 어디가 전년도({yr}) 정시 결과 · 수능 백분위 기준",
                             font=("Malgun Gothic", 12, "bold"), text_color=C["blue"]
                             ).pack(anchor="w", padx=12, pady=(8, 2))
                if js.get("pct_avg70") is not None:
                    ctk.CTkLabel(box, text=f"• 평균백분위 70%컷: {js['pct_avg70']}  "
                                 f"(50%컷 {js.get('pct_avg50','-')})  ·  환산 {js.get('score70','-')}",
                                 font=("Malgun Gothic", 12, "bold"), text_color=C["green"]
                                 ).pack(anchor="w", padx=14, pady=(0, 1))
                    sub = []
                    if js.get("pct_kor70") is not None: sub.append(f"국어 {js['pct_kor70']}")
                    if js.get("pct_math70") is not None: sub.append(f"수학 {js['pct_math70']}")
                    if js.get("pct_tam70") is not None: sub.append(f"탐구 {js['pct_tam70']}")
                    if js.get("eng70") is not None: sub.append(f"영어 {int(js['eng70'])}등급")
                    if js.get("hist70") is not None: sub.append(f"한국사 {int(js['hist70'])}등급")
                    if sub:
                        ctk.CTkLabel(box, text="• 영역별 70%컷 백분위: " + "  ·  ".join(sub),
                                     font=("Malgun Gothic", 11), text_color=C["text"]
                                     ).pack(anchor="w", padx=14, pady=(0, 1))
                meta_p = []
                if js.get("competition") is not None: meta_p.append(f"경쟁률 {js['competition']}:1")
                if js.get("chungwon") is not None: meta_p.append(f"충원 {int(js['chungwon'])}명")
                if js.get("recruit") is not None: meta_p.append(f"모집 {int(js['recruit'])}명")
                if meta_p:
                    ctk.CTkLabel(box, text="• " + "  ·  ".join(meta_p),
                                 font=("Malgun Gothic", 11), text_color=C["muted"]
                                 ).pack(anchor="w", padx=14, pady=(0, 1))
                ctk.CTkLabel(box, text="※ 백분위=높을수록 우수. 왼쪽에 수능 백분위를 넣으면 자동 비교됩니다.",
                             font=("Malgun Gothic", 10), text_color=C["muted"]
                             ).pack(anchor="w", padx=14, pady=(2, 8))
            ctk.CTkLabel(card, text=f"밴드 근거: {x.get('band_basis','-')}  ·  매칭 {x.get('match','-')}",
                         font=("Malgun Gothic", 11), text_color=C["muted"]).pack(anchor="w", padx=16, pady=(0, 4))
            if x.get("sources"):
                n = len(x["sources"])
                ctk.CTkButton(card, text=f"📄 출처 원문 보기 (모집요강·어디가 {n}개, 해당 학과 강조)",
                              font=("Malgun Gothic", 11), height=28, fg_color=C["card2"],
                              hover_color=C["line"], command=lambda xx=x: self.open_source(xx)
                              ).pack(anchor="w", padx=16, pady=(0, 12))

    def open_source(self, r):
        srcs = r.get("sources") or []
        if not srcs:
            self._toast("이 항목의 원문 이미지가 없습니다.\n(아직 발행 전이거나 원문 없음)")
            return
        os.makedirs(PAGES, exist_ok=True)
        url = self.cfg.get("update_url", "").rstrip("/")
        from PIL import Image, ImageDraw
        base_imgs = []                # (라벨, 박스 그린 이미지)
        for s in srcs:
            img = s.get("img")
            if not img:
                continue
            path = os.path.join(PAGES, img)
            if not os.path.exists(path) and url:      # 로컬에 없으면 온라인에서 받아옴
                try:
                    with open(path, "wb") as f:
                        f.write(http_get(f"{url}/pages/{img}"))
                except Exception:
                    pass
            if not os.path.exists(path):
                continue
            try:
                im = Image.open(path).convert("RGB")
            except Exception:
                continue
            boxes = s.get("boxes") or []
            if boxes:                 # 해당 학과 행·셀을 빨간 박스로
                d = ImageDraw.Draw(im); W, H = im.width, im.height
                for b in boxes:
                    x0, y0, x1, y1 = b[0]*W, b[1]*H, b[2]*W, b[3]*H
                    d.rectangle([3, y0-3, W-3, y1+3], outline=(231, 42, 42), width=3)
                    d.rectangle([x0-2, y0-2, x1+2, y1+2], outline=(231, 42, 42), width=2)
            base_imgs.append((s.get("label", "원문"), im))
        if not base_imgs:
            self._toast("원문 이미지를 불러오지 못했습니다.\n(오프라인이거나 발행 전)")
            return
        win = self._top(); win.title(f"원문: {r['univ']} {r['unit']}")
        win.geometry("1040x1000"); win.configure(fg_color=C["bg"])
        win.resizable(True, True)
        state = {"zoom": 1.0, "imgs": []}
        bar = ctk.CTkFrame(win, fg_color=C["card"], corner_radius=0); bar.pack(fill="x")
        ctk.CTkLabel(bar, text="🔍 확대/축소", font=("Malgun Gothic", 12),
                     text_color=C["muted"]).pack(side="left", padx=(14, 8), pady=8)
        ctk.CTkLabel(bar, text="🟥 빨간 박스 = 해당 학과", font=("Malgun Gothic", 11),
                     text_color=C["red"]).pack(side="right", padx=14)
        zlabel = ctk.CTkLabel(bar, text="100%", font=("Malgun Gothic", 12, "bold"),
                              text_color=C["blue"], width=56)
        sf = ctk.CTkScrollableFrame(win, fg_color="transparent")

        def draw():
            for w in sf.winfo_children():
                w.destroy()
            state["imgs"].clear()
            for l, im in base_imgs:
                ctk.CTkLabel(sf, text=l, font=("Malgun Gothic", 14, "bold"),
                             text_color=C["blue"]).pack(anchor="w", padx=10, pady=(12, 4))
                w0 = int(im.width * state["zoom"]); h0 = int(im.height * state["zoom"])
                ci = ctk.CTkImage(light_image=im, dark_image=im, size=(w0, h0))
                state["imgs"].append(ci)
                ctk.CTkLabel(sf, image=ci, text="").pack(padx=10, pady=4)
            zlabel.configure(text=f"{int(state['zoom']*100)}%")

        def zoom(d):
            state["zoom"] = max(0.4, min(3.0, round(state["zoom"] + d, 2))); draw()
        ctk.CTkButton(bar, text="－", width=40, height=28, font=("Malgun Gothic", 16, "bold"),
                      fg_color=C["card2"], hover_color=C["line"], command=lambda: zoom(-0.25)
                      ).pack(side="left", padx=2, pady=8)
        zlabel.pack(side="left", padx=4)
        ctk.CTkButton(bar, text="＋", width=40, height=28, font=("Malgun Gothic", 16, "bold"),
                      fg_color=C["blue"], hover_color=C["blue"], command=lambda: zoom(0.25)
                      ).pack(side="left", padx=2, pady=8)
        sf.pack(fill="both", expand=True)
        win.bind("<Control-MouseWheel>", lambda e: zoom(0.25 if e.delta > 0 else -0.25))
        draw()

    # ---------- 요청/업데이트 ----------
    def _request(self):
        """없는 대학 요청 — 앱 안에서 바로 전송(이메일 불필요)."""
        topic = self.cfg.get("request_topic", "")
        win = self._top(); win.title("대학/데이터 요청")
        win.geometry("440x300"); win.configure(fg_color=C["card"])
        ctk.CTkLabel(win, text="✉️ 없는 대학 요청", font=(FONT, 17, "bold"),
                     text_color=C["text"]).pack(pady=(20, 4))
        ctk.CTkLabel(win, text="추가를 원하는 대학·학과·전형을 적어주세요.\n관리자에게 바로 전달됩니다.",
                     font=(FONT, 12), text_color=C["muted"], justify="center").pack()
        box = ctk.CTkTextbox(win, height=110, fg_color=C["card2"], border_color=C["line"],
                             font=(FONT, 13)); box.pack(fill="x", padx=20, pady=12)
        box.insert("1.0", "대학명: \n학과(선택): \n내용: ")
        msg = ctk.CTkLabel(win, text="", font=(FONT, 11), text_color=C["green"]); msg.pack()

        def send():
            text = box.get("1.0", "end").strip()
            if not text:
                msg.configure(text="내용을 입력하세요.", text_color=C["red"]); return
            if not topic:
                # 폴백: 이메일
                em = self.cfg.get("admin_email", "")
                if em:
                    import urllib.parse
                    webbrowser.open(f"mailto:{em}?subject=진학분석기 요청&body="
                                    + urllib.parse.quote(text))
                    win.destroy()
                else:
                    msg.configure(text="요청 채널이 설정되지 않았습니다.", text_color=C["red"])
                return

            def work():
                try:
                    req = urllib.request.Request(
                        f"https://ntfy.sh/{topic}",
                        data=text.encode("utf-8"),
                        headers={"Title": "jinhak request", "User-Agent": "Mozilla/5.0"})
                    urllib.request.urlopen(req, context=ssl._create_unverified_context(),
                                           timeout=15).read()
                    self.after(0, lambda: (msg.configure(text="✅ 전송 완료! 감사합니다.",
                                           text_color=C["green"]),
                                           win.after(1200, win.destroy)))
                except Exception:
                    self.after(0, lambda: msg.configure(text="전송 실패(인터넷 확인).",
                               text_color=C["red"]))
            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(win, text="전송", command=send, fg_color=C["blue"], width=140,
                      font=(FONT, 13, "bold")).pack(pady=10)

    def _update(self):
        if not self.cfg.get("update_url", "").rstrip("/"):
            self._toast("업데이트 주소(update_url)가 설정되지 않았습니다.\n"
                        "관리자가 config.json에 Git raw 주소를 넣어야 합니다.")
            return
        self._fetch_data(silent=False)

    def _fetch_data(self, silent=True):
        """온라인에서 최신 데이터 확인·다운로드. silent=True면 조용히(자동)."""
        url = self.cfg.get("update_url", "").rstrip("/")
        if not url:
            return
        os.makedirs(PUBLISHED, exist_ok=True)

        def work():
            try:
                def get(name):
                    return http_get(f"{url}/{name}")
                # 원격 manifest의 생성일이 로컬과 다를 때만 갱신(불필요 다운로드 방지)
                remote = get("manifest.json")
                import json as _json
                rgen = _json.loads(remote.decode("utf-8")).get("generated")
                lp = os.path.join(PUBLISHED, "manifest.json")
                lgen = None
                if os.path.exists(lp):
                    lgen = _json.load(open(lp, encoding="utf-8")).get("generated")
                if silent and rgen == lgen:
                    return  # 이미 최신 → 조용히 종료
                for name in ("config.json", "manifest.json"):
                    with open(os.path.join(PUBLISHED, name), "wb") as f:
                        f.write(get(name))
                # 데이터: 암호문/평문 + 배너 중 있는 것을 받음
                for name in ("universities.enc", "universities.json", "banner.png"):
                    try:
                        data = get(name)
                        with open(os.path.join(PUBLISHED, name), "wb") as f:
                            f.write(data)
                    except Exception:
                        pass
                self.cfg = load_config()
                self.after(0, self._load_banner)
                u, need = read_univs(saved_code())
                if need:
                    self.after(0, self._ask_code)
                    return
                self.univs = u or {}
                self.after(0, self._refresh_filters)
                self.after(0, self.recompute)
                self.after(0, lambda: self._toast(f"최신 데이터로 갱신했습니다.\n(발행 {rgen})"))
            except Exception as e:
                if not silent:
                    self.after(0, lambda: self._toast(f"업데이트 실패: {e}\n(오프라인이면 기존 데이터 사용)"))
        threading.Thread(target=work, daemon=True).start()

    def _toast(self, msg, ms=4500):
        try:
            if getattr(self, "_toastwin", None) and self._toastwin.winfo_exists():
                self._toastwin.destroy()
        except Exception:
            pass
        t = self._top(); t.geometry("380x120"); t.configure(fg_color=C["card"])
        t.transient(self); t.title(""); t.resizable(False, False)
        ctk.CTkLabel(t, text=msg, font=("Malgun Gothic", 13), text_color=C["text"],
                     wraplength=340, justify="left").pack(expand=True, padx=16, pady=16)
        self._toastwin = t
        t.after(ms, lambda: (t.winfo_exists() and t.destroy()))


if __name__ == "__main__":
    Lite().mainloop()
