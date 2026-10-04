"""
Steam Hours Viewer
==================
Небольшое настольное приложение для Windows в тёмной теме "под Steam",
которое показывает список игр Steam-профиля вместе с количеством
наигранных часов и позволяет визуально (локально, только в самом
приложении) изменить отображаемое значение часов для любой игры.

ВАЖНО: приложение не меняет реальную статистику в Steam — это невозможно
и не является целью программы. "Изменение часов" — это только то, что
видно в окне этой программы (и может использоваться, например, для
скриншотов/оформления).

Запуск:  python app.py
Сборка в .exe: build.bat (см. README.md)
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional

import requests

import steam_api
from steam_api import Game, ProfileInfo

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
except ImportError:  # Pillow не установлен — приложение работает, но без иконок игр/аватара
    HAS_PIL = False

APP_NAME = "Steam Hours Viewer"
APP_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Палитра "под Steam" (тёмная тема клиента Steam)
# ---------------------------------------------------------------------------
BG_DARKEST = "#0e1217"
BG_DARK = "#1b2838"
BG_PANEL = "#16202d"
BG_PANEL_ALT = "#1e2b3a"
BG_HEADER = "#171a21"
ROW_SELECTED = "#316282"
ROW_OVERRIDDEN = "#3a3415"
ACCENT_BLUE = "#66c0f4"
ACCENT_BLUE_DARK = "#1a9fff"
BUTTON_BG = "#2a475e"
BUTTON_BG_HOVER = "#417a9b"
TEXT_PRIMARY = "#c7d5e0"
TEXT_SECONDARY = "#8f98a0"
TEXT_WHITE = "#ffffff"
FONT_FAMILY = "Segoe UI"


def resource_path(relative: str) -> str:
    """Путь к файлу ресурса, учитывающий сборку PyInstaller (--onefile)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def get_app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "SteamHoursViewer")
    os.makedirs(path, exist_ok=True)
    return path


CONFIG_PATH = os.path.join(get_app_data_dir(), "config.json")
OVERRIDES_PATH = os.path.join(get_app_data_dir(), "overrides.json")
CACHE_PATH = os.path.join(get_app_data_dir(), "games_cache.json")
ICON_CACHE_DIR = os.path.join(get_app_data_dir(), "icon_cache")
os.makedirs(ICON_CACHE_DIR, exist_ok=True)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_cache() -> List[dict]:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_cache(games: List[Game]) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump([g.to_dict() for g in games], f, ensure_ascii=False, indent=2)


def apply_windows_dark_titlebar(root: tk.Tk) -> None:
    """На Windows 10/11 красит системную рамку окна в тёмный цвет,
    чтобы она не контрастировала с тёмным интерфейсом (как в Steam).
    Безопасно ничего не делает на других ОС / старых сборках Windows."""
    if sys.platform != "win32":
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новый/старый id)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:  # noqa: BLE001
        pass


def make_dark_style(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=BG_DARK)

    style.configure("TFrame", background=BG_DARK)
    style.configure("Header.TFrame", background=BG_HEADER)
    style.configure("Panel.TFrame", background=BG_PANEL)

    style.configure("TLabel", background=BG_DARK, foreground=TEXT_PRIMARY, font=(FONT_FAMILY, 10))
    style.configure("Header.TLabel", background=BG_HEADER, foreground=TEXT_PRIMARY, font=(FONT_FAMILY, 10))
    style.configure("Name.TLabel", background=BG_HEADER, foreground=TEXT_WHITE, font=(FONT_FAMILY, 15, "bold"))
    style.configure("Sub.TLabel", background=BG_HEADER, foreground=ACCENT_BLUE, font=(FONT_FAMILY, 9))
    style.configure("Total.TLabel", background=BG_DARK, foreground=TEXT_WHITE, font=(FONT_FAMILY, 11, "bold"))
    style.configure("Status.TLabel", background=BG_DARKEST, foreground=TEXT_SECONDARY, font=(FONT_FAMILY, 9))

    style.configure(
        "TButton",
        background=BUTTON_BG,
        foreground=TEXT_WHITE,
        borderwidth=0,
        focusthickness=0,
        focuscolor=BUTTON_BG,
        padding=(12, 7),
        font=(FONT_FAMILY, 9, "bold"),
    )
    style.map(
        "TButton",
        background=[("active", ACCENT_BLUE), ("disabled", BG_PANEL_ALT)],
        foreground=[("active", "#0b1822"), ("disabled", TEXT_SECONDARY)],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT_BLUE_DARK,
        foreground="#07131b",
        borderwidth=0,
        padding=(12, 7),
        font=(FONT_FAMILY, 9, "bold"),
    )
    style.map("Accent.TButton", background=[("active", ACCENT_BLUE)])

    style.configure(
        "TEntry",
        fieldbackground=BG_PANEL,
        foreground=TEXT_WHITE,
        insertcolor=TEXT_WHITE,
        borderwidth=1,
        padding=6,
    )

    style.configure(
        "Treeview",
        background=BG_PANEL,
        fieldbackground=BG_PANEL,
        foreground=TEXT_PRIMARY,
        rowheight=40,
        borderwidth=0,
        font=(FONT_FAMILY, 10),
    )
    style.map(
        "Treeview",
        background=[("selected", ROW_SELECTED)],
        foreground=[("selected", TEXT_WHITE)],
    )
    style.configure(
        "Treeview.Heading",
        background=BG_HEADER,
        foreground=TEXT_SECONDARY,
        relief="flat",
        font=(FONT_FAMILY, 9, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", BG_HEADER)])

    style.configure(
        "Vertical.TScrollbar",
        background=BG_PANEL_ALT,
        troughcolor=BG_DARK,
        bordercolor=BG_DARK,
        arrowcolor=TEXT_SECONDARY,
        relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", ACCENT_BLUE)])

    return style


def load_round_photo(data: bytes, size: int):
    """Из байтов картинки делает PhotoImage нужного размера (квадрат,
    обрезка по центру). Возвращает None, если Pillow недоступен."""
    if not HAS_PIL:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = img.size
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        img = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Диалог первоначальной настройки / изменения профиля
# ---------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.title("Настройки профиля Steam")
        self.configure(bg=BG_DARK)
        self.resizable(False, False)
        self.result: Optional[dict] = None
        self.transient(parent)
        self.grab_set()

        pad = {"padx": 10, "pady": 6}

        ttk.Label(self, text="Ссылка на профиль Steam или SteamID64:").grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        self.profile_var = tk.StringVar(value=cfg.get("profile", ""))
        entry = ttk.Entry(self, textvariable=self.profile_var, width=48)
        entry.grid(row=1, column=0, columnspan=2, sticky="we", padx=10)

        hint = (
            "Примеры: https://steamcommunity.com/id/myname\n"
            "          76561197960287930\n\n"
            "Для работы без API-ключа в настройках приватности Steam должно\n"
            "быть включено: Профиль -> Приватность -> Сведения об игре = Открыто"
        )
        ttk.Label(self, text=hint, foreground=TEXT_SECONDARY, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", **pad
        )

        ttk.Label(self, text="Steam Web API ключ (необязательно):").grid(
            row=3, column=0, columnspan=2, sticky="w", **pad
        )
        self.api_key_var = tk.StringVar(value=cfg.get("api_key", ""))
        ttk.Entry(self, textvariable=self.api_key_var, width=48, show="*").grid(
            row=4, column=0, columnspan=2, sticky="we", padx=10
        )
        ttk.Label(
            self,
            text="Нужен только если профиль приватный.\nПолучить: https://steamcommunity.com/dev/apikey",
            foreground=TEXT_SECONDARY,
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

        btns = ttk.Frame(self)
        btns.grid(row=6, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=self._on_save).pack(side="left", padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left", padx=6)

        entry.focus_set()
        self.bind("<Return>", lambda e: self._on_save())

    def _on_save(self):
        profile = self.profile_var.get().strip()
        if not profile:
            messagebox.showwarning(APP_NAME, "Укажите ссылку на профиль или SteamID64.")
            return
        self.result = {"profile": profile, "api_key": self.api_key_var.get().strip()}
        self.destroy()


# ---------------------------------------------------------------------------
# Диалог редактирования часов (визуальное переопределение)
# ---------------------------------------------------------------------------
class EditHoursDialog(tk.Toplevel):
    def __init__(self, parent, game: Game):
        super().__init__(parent)
        self.title(f"Изменить часы — {game.name}")
        self.configure(bg=BG_DARK)
        self.resizable(False, False)
        self.result: Optional[float] = None
        self.reset_requested = False
        self.transient(parent)
        self.grab_set()

        pad = {"padx": 10, "pady": 6}
        ttk.Label(self, text=f"Игра: {game.name}", style="Total.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        ttk.Label(self, text=f"Реальное время в Steam: {game.hours_official:.1f} ч.").grid(
            row=1, column=0, columnspan=2, sticky="w", **pad
        )

        ttk.Label(self, text="Отображаемое количество часов:").grid(row=2, column=0, sticky="w", **pad)
        self.value_var = tk.StringVar(value=f"{game.display_hours:.1f}")
        entry = ttk.Entry(self, textvariable=self.value_var, width=15)
        entry.grid(row=2, column=1, sticky="w", **pad)
        entry.focus_set()
        entry.selection_range(0, "end")

        btns = ttk.Frame(self)
        btns.grid(row=3, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=self._on_save).pack(side="left", padx=6)
        if game.is_overridden:
            ttk.Button(btns, text="Сбросить к реальным", command=self._on_reset).pack(side="left", padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left", padx=6)

        self.bind("<Return>", lambda e: self._on_save())

    def _on_save(self):
        raw = self.value_var.get().strip().replace(",", ".")
        try:
            value = float(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_NAME, "Введите положительное число (например 123.5)")
            return
        self.result = round(value, 1)
        self.destroy()

    def _on_reset(self):
        self.reset_requested = True
        self.destroy()


# ---------------------------------------------------------------------------
# Главное окно
# ---------------------------------------------------------------------------
class MainApp(tk.Tk):
    COLUMNS = ("hours", "last2weeks", "status")

    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}")
        self.geometry("860x600")
        self.minsize(680, 440)

        icon_path = resource_path(os.path.join("assets", "app.ico"))
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except tk.TclError:
                pass

        apply_windows_dark_titlebar(self)
        self.style = make_dark_style(self)

        self.cfg = load_config()
        self.overrides: Dict[int, float] = steam_api.load_overrides(OVERRIDES_PATH)
        self.games: List[Game] = []
        self.icon_images: Dict[int, "ImageTk.PhotoImage"] = {}
        self.avatar_image = None

        self._build_ui()

        if not self.cfg.get("profile"):
            self.after(200, self._open_settings)
        else:
            self.after(200, self.refresh_data)

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        # ------------------------------------------------------------------
        # Шапка в стиле профиля Steam: аватар + ник + ссылка на профиль
        # ------------------------------------------------------------------
        header = tk.Frame(self, bg=BG_HEADER)
        header.pack(side="top", fill="x")

        inner = tk.Frame(header, bg=BG_HEADER, padx=14, pady=12)
        inner.pack(fill="x")

        avatar_box = tk.Frame(inner, bg=BG_HEADER, width=64, height=64)
        avatar_box.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        avatar_box.pack_propagate(False)
        self.avatar_canvas = tk.Label(avatar_box, bg=BUTTON_BG)
        self.avatar_canvas.pack(fill="both", expand=True)
        self._set_default_avatar()

        self.name_var = tk.StringVar(value="Steam Hours Viewer")
        ttk.Label(inner, textvariable=self.name_var, style="Name.TLabel").grid(row=0, column=1, sticky="w")

        self.profile_label_var = tk.StringVar(value=self.cfg.get("profile", "— профиль не задан —"))
        ttk.Label(inner, textvariable=self.profile_label_var, style="Sub.TLabel").grid(
            row=1, column=1, sticky="w"
        )

        btn_frame = tk.Frame(inner, bg=BG_HEADER)
        btn_frame.grid(row=0, column=2, rowspan=2, sticky="e", padx=(20, 0))
        inner.columnconfigure(1, weight=1)

        ttk.Button(btn_frame, text="Обновить из Steam", style="Accent.TButton", command=self.refresh_data).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="Настройки профиля", command=self._open_settings).pack(side="left", padx=4)

        # ------------------------------------------------------------------
        # Панель поиска
        # ------------------------------------------------------------------
        search_bar = tk.Frame(self, bg=BG_DARK)
        search_bar.pack(side="top", fill="x", padx=14, pady=(10, 4))
        ttk.Label(search_bar, text="Поиск по играм:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_tree())
        ttk.Entry(search_bar, textvariable=self.search_var, width=28).pack(side="left", padx=8)

        # ------------------------------------------------------------------
        # Таблица игр (с иконками в стиле библиотеки Steam)
        # ------------------------------------------------------------------
        table_frame = tk.Frame(self, bg=BG_DARK, padx=14)
        table_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            table_frame,
            columns=self.COLUMNS,
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Игра", command=lambda: self._sort_by("name"))
        self.tree.heading("hours", text="Часы (отображается)", command=lambda: self._sort_by("hours"))
        self.tree.heading("last2weeks", text="За 2 недели", command=lambda: self._sort_by("last2weeks"))
        self.tree.heading("status", text="Статус")

        self.tree.column("#0", width=380, anchor="w")
        self.tree.column("hours", width=170, anchor="center")
        self.tree.column("last2weeks", width=110, anchor="center")
        self.tree.column("status", width=110, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(0, 8))
        vsb.pack(side="right", fill="y", pady=(0, 8))

        self.tree.bind("<Double-1>", lambda e: self._edit_selected())
        self.tree.tag_configure("overridden", background=ROW_OVERRIDDEN, foreground="#f0d264")
        self.tree.tag_configure("normal", background=BG_PANEL)

        # ------------------------------------------------------------------
        # Нижняя панель
        # ------------------------------------------------------------------
        bottom = tk.Frame(self, bg=BG_DARK, padx=14, pady=8)
        bottom.pack(side="bottom", fill="x")

        ttk.Button(bottom, text="Изменить часы", style="Accent.TButton", command=self._edit_selected).pack(
            side="left", padx=4
        )
        ttk.Button(bottom, text="Сбросить к реальным", command=self._reset_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="Сбросить ВСЕ", command=self._reset_all).pack(side="left", padx=4)

        self.total_var = tk.StringVar(value="Всего часов: 0")
        ttk.Label(bottom, textvariable=self.total_var, style="Total.TLabel").pack(side="right")

        self.status_var = tk.StringVar(value="Готово")
        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG_DARKEST,
            fg=TEXT_SECONDARY,
            anchor="w",
            padx=10,
            pady=3,
            font=(FONT_FAMILY, 9),
        )
        status_bar.pack(side="bottom", fill="x")

        self._sort_state = {"col": "hours", "reverse": True}

    def _set_default_avatar(self):
        # Простая заглушка-силуэт, пока не загрузился реальный аватар
        self.avatar_canvas.configure(text="👤", font=(FONT_FAMILY, 22), fg=TEXT_SECONDARY, bg=BUTTON_BG)

    # ----------------------------------------------------------- Settings --
    def _open_settings(self):
        dlg = SettingsDialog(self, self.cfg)
        self.wait_window(dlg)
        if dlg.result:
            self.cfg.update(dlg.result)
            save_config(self.cfg)
            self.profile_label_var.set(self.cfg["profile"])
            self.refresh_data()

    # ------------------------------------------------------------- Data ---
    def refresh_data(self):
        profile = self.cfg.get("profile")
        if not profile:
            return
        self.status_var.set("Загрузка данных из Steam...")
        threading.Thread(target=self._fetch_worker, args=(profile, self.cfg.get("api_key") or None), daemon=True).start()

    def _fetch_worker(self, profile: str, api_key: Optional[str]):
        profile_info = None
        try:
            profile_info = steam_api.fetch_profile_info(profile)
        except Exception:  # noqa: BLE001
            pass

        try:
            games = steam_api.fetch_games(profile, api_key)
            error = None
        except steam_api.ProfilePrivateError as e:
            games, error = [], (
                "Профиль приватный: Steam не отдаёт список игр.\n"
                "Откройте в Steam: Профиль -> Правка профиля -> Приватность -> "
                "'Сведения об игре' = Открыто, либо укажите API-ключ в настройках.\n\n"
                f"({e})"
            )
        except steam_api.ProfileNotFoundError as e:
            games, error = [], f"Профиль не найден: {e}"
        except requests.RequestException as e:
            games, error = [], f"Ошибка сети при обращении к Steam: {e}"
        except Exception as e:  # noqa: BLE001
            games, error = [], f"Непредвиденная ошибка: {e}"

        self.after(0, self._on_fetch_done, games, error, profile_info)

    def _on_fetch_done(self, games: List[Game], error: Optional[str], profile_info: Optional[ProfileInfo]):
        if profile_info and profile_info.display_name:
            self.name_var.set(profile_info.display_name)
        if profile_info and profile_info.avatar_url:
            threading.Thread(target=self._load_avatar_worker, args=(profile_info.avatar_url,), daemon=True).start()

        if error:
            self.status_var.set("Ошибка загрузки — показаны сохранённые данные (если есть)")
            cached = load_cache()
            if cached:
                games = [Game(**{**c}) for c in cached]
            else:
                messagebox.showerror(APP_NAME, error)
                return
            messagebox.showwarning(APP_NAME, error)
        else:
            self.status_var.set(f"Загружено игр: {len(games)}")
            save_cache(games)

        steam_api.apply_overrides(games, self.overrides)
        self.games = games
        self._populate_tree()

        if HAS_PIL:
            threading.Thread(target=self._load_icons_worker, args=(list(games),), daemon=True).start()

    def _load_avatar_worker(self, url: str):
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            photo = load_round_photo(resp.content, 64)
            if photo:
                self.after(0, self._set_avatar_photo, photo)
        except Exception:  # noqa: BLE001
            pass

    def _set_avatar_photo(self, photo):
        self.avatar_image = photo  # хранить ссылку, иначе картинка пропадёт
        self.avatar_canvas.configure(image=photo, text="")

    def _load_icons_worker(self, games: List[Game], limit: int = 400):
        session = requests.Session()
        for g in games[:limit]:
            if not g.logo_url or g.appid in self.icon_images:
                continue
            cache_file = os.path.join(ICON_CACHE_DIR, f"{g.appid}.png")
            data = None
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "rb") as f:
                        data = f.read()
                except OSError:
                    data = None
            if data is None:
                try:
                    resp = session.get(g.logo_url, timeout=6)
                    resp.raise_for_status()
                    data = resp.content
                    try:
                        with open(cache_file, "wb") as f:
                            f.write(data)
                    except OSError:
                        pass
                except Exception:  # noqa: BLE001
                    continue
            photo = load_round_photo(data, 28)
            if photo:
                self.after(0, self._apply_game_icon, g.appid, photo)

    def _apply_game_icon(self, appid: int, photo):
        self.icon_images[appid] = photo
        if self.tree.exists(str(appid)):
            self.tree.item(str(appid), image=photo)

    # --------------------------------------------------------------- UI ---
    def _filtered_sorted_games(self) -> List[Game]:
        query = self.search_var.get().strip().lower()
        games = [g for g in self.games if query in g.name.lower()] if query else list(self.games)

        col = self._sort_state["col"]
        reverse = self._sort_state["reverse"]
        key_fn = {
            "name": lambda g: g.name.lower(),
            "hours": lambda g: g.display_hours,
            "last2weeks": lambda g: g.hours_last_2weeks,
        }.get(col, lambda g: g.display_hours)
        games.sort(key=key_fn, reverse=reverse)
        return games

    def _populate_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        games = self._filtered_sorted_games()
        for g in games:
            status = "изменено" if g.is_overridden else "реальное"
            tag = "overridden" if g.is_overridden else "normal"
            icon = self.icon_images.get(g.appid)
            self.tree.insert(
                "",
                "end",
                iid=str(g.appid),
                text=f"  {g.name}",
                image=icon if icon else "",
                values=(f"{g.display_hours:.1f} ч.", f"{g.hours_last_2weeks:.1f} ч.", status),
                tags=(tag,),
            )

        total = sum(g.display_hours for g in self.games)
        self.total_var.set(f"Всего часов (с учётом изменений): {total:.1f}")

    def _sort_by(self, col: str):
        if self._sort_state["col"] == col:
            self._sort_state["reverse"] = not self._sort_state["reverse"]
        else:
            self._sort_state = {"col": col, "reverse": True}
        self._populate_tree()

    def _get_selected_game(self) -> Optional[Game]:
        sel = self.tree.selection()
        if not sel:
            return None
        appid = int(sel[0])
        return next((g for g in self.games if g.appid == appid), None)

    # ------------------------------------------------------------ Actions -
    def _edit_selected(self):
        game = self._get_selected_game()
        if not game:
            messagebox.showinfo(APP_NAME, "Сначала выберите игру в списке.")
            return
        dlg = EditHoursDialog(self, game)
        self.wait_window(dlg)
        if dlg.reset_requested:
            self.overrides.pop(game.appid, None)
            game.override_hours = None
            steam_api.save_overrides(OVERRIDES_PATH, self.overrides)
            self._populate_tree()
        elif dlg.result is not None:
            self.overrides[game.appid] = dlg.result
            game.override_hours = dlg.result
            steam_api.save_overrides(OVERRIDES_PATH, self.overrides)
            self._populate_tree()

    def _reset_selected(self):
        game = self._get_selected_game()
        if not game:
            messagebox.showinfo(APP_NAME, "Сначала выберите игру в списке.")
            return
        if game.appid in self.overrides:
            self.overrides.pop(game.appid, None)
            game.override_hours = None
            steam_api.save_overrides(OVERRIDES_PATH, self.overrides)
            self._populate_tree()

    def _reset_all(self):
        if not self.overrides:
            return
        if messagebox.askyesno(APP_NAME, "Сбросить ВСЕ изменённые значения часов к реальным?"):
            self.overrides.clear()
            for g in self.games:
                g.override_hours = None
            steam_api.save_overrides(OVERRIDES_PATH, self.overrides)
            self._populate_tree()


def main():
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
