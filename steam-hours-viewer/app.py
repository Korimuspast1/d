"""
Steam Hours Viewer
==================
Небольшое настольное приложение для Windows, которое показывает список игр
Steam-профиля вместе с количеством наигранных часов и позволяет визуально
(локально, только в самом приложении) изменить отображаемое значение часов
для любой игры.

ВАЖНО: приложение не меняет реальную статистику в Steam — это невозможно
и не является целью программы. "Изменение часов" — это только то, что
видно в окне этой программы (и может использоваться, например, для
скриншотов/оформления).

Запуск:  python app.py
Сборка в .exe: build.bat (см. README.md)
"""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional

import requests

import steam_api
from steam_api import Game

APP_NAME = "Steam Hours Viewer"
APP_VERSION = "1.0"


def get_app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "SteamHoursViewer")
    os.makedirs(path, exist_ok=True)
    return path


CONFIG_PATH = os.path.join(get_app_data_dir(), "config.json")
OVERRIDES_PATH = os.path.join(get_app_data_dir(), "overrides.json")
CACHE_PATH = os.path.join(get_app_data_dir(), "games_cache.json")
ICON_CACHE_DIR = os.path.join(get_app_data_dir(), "icon_cache")


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


# --------------------------------------------------------------------------- 
# Диалог первоначальной настройки / изменения профиля
# ---------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.title("Настройки профиля Steam")
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
        ttk.Label(self, text=hint, foreground="#555", justify="left").grid(
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
            foreground="#555",
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

        btns = ttk.Frame(self)
        btns.grid(row=6, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Сохранить", command=self._on_save).pack(side="left", padx=6)
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
        self.resizable(False, False)
        self.result: Optional[float] = None  # None -> отмена/сброс не трогаем
        self.reset_requested = False
        self.transient(parent)
        self.grab_set()

        pad = {"padx": 10, "pady": 6}
        ttk.Label(self, text=f"Игра: {game.name}").grid(row=0, column=0, columnspan=2, sticky="w", **pad)
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
        ttk.Button(btns, text="Сохранить", command=self._on_save).pack(side="left", padx=6)
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
    COLUMNS = ("name", "hours", "last2weeks", "status")

    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("760x560")
        self.minsize(620, 420)

        self.cfg = load_config()
        self.overrides: Dict[int, float] = steam_api.load_overrides(OVERRIDES_PATH)
        self.games: List[Game] = []
        self.icon_images: Dict[int, tk.PhotoImage] = {}

        self._build_ui()

        if not self.cfg.get("profile"):
            self.after(200, self._open_settings)
        else:
            self.after(200, self.refresh_data)

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        top = ttk.Frame(self, padding=8)
        top.pack(side="top", fill="x")

        ttk.Label(top, text="Профиль:").pack(side="left")
        self.profile_label_var = tk.StringVar(value=self.cfg.get("profile", "— не задан —"))
        ttk.Label(top, textvariable=self.profile_label_var, font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(4, 16)
        )

        ttk.Button(top, text="Обновить из Steam", command=self.refresh_data).pack(side="left", padx=4)
        ttk.Button(top, text="Настройки профиля", command=self._open_settings).pack(side="left", padx=4)

        search_frame = ttk.Frame(top)
        search_frame.pack(side="right")
        ttk.Label(search_frame, text="Поиск:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_tree())
        ttk.Entry(search_frame, textvariable=self.search_var, width=22).pack(side="left", padx=4)

        # Таблица
        table_frame = ttk.Frame(self, padding=(8, 0, 8, 0))
        table_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            table_frame,
            columns=self.COLUMNS,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("name", text="Игра", command=lambda: self._sort_by("name"))
        self.tree.heading("hours", text="Часы (отображается)", command=lambda: self._sort_by("hours"))
        self.tree.heading("last2weeks", text="За 2 недели", command=lambda: self._sort_by("last2weeks"))
        self.tree.heading("status", text="Статус")

        self.tree.column("name", width=330, anchor="w")
        self.tree.column("hours", width=160, anchor="center")
        self.tree.column("last2weeks", width=110, anchor="center")
        self.tree.column("status", width=110, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self._edit_selected())
        self.tree.tag_configure("overridden", foreground="#b8860b")

        # Нижняя панель
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(side="bottom", fill="x")

        ttk.Button(bottom, text="Изменить часы", command=self._edit_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="Сбросить к реальным", command=self._reset_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="Сбросить ВСЕ", command=self._reset_all).pack(side="left", padx=4)

        self.total_var = tk.StringVar(value="Всего часов: 0")
        ttk.Label(bottom, textvariable=self.total_var, font=("Segoe UI", 10, "bold")).pack(side="right")

        self.status_var = tk.StringVar(value="Готово")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=(6, 2))
        status_bar.pack(side="bottom", fill="x")

        self._sort_state = {"col": "hours", "reverse": True}

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
        self._set_controls_enabled(False)
        threading.Thread(target=self._fetch_worker, args=(profile, self.cfg.get("api_key") or None), daemon=True).start()

    def _fetch_worker(self, profile: str, api_key: Optional[str]):
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

        self.after(0, self._on_fetch_done, games, error)

    def _on_fetch_done(self, games: List[Game], error: Optional[str]):
        self._set_controls_enabled(True)
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

    def _set_controls_enabled(self, enabled: bool):
        # Зарезервировано под блокировку элементов управления во время
        # сетевого запроса. Дерево остаётся кликабельным в любом состоянии.
        return

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
            tags = ("overridden",) if g.is_overridden else ()
            self.tree.insert(
                "",
                "end",
                iid=str(g.appid),
                values=(g.name, f"{g.display_hours:.1f} ч.", f"{g.hours_last_2weeks:.1f} ч.", status),
                tags=tags,
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
