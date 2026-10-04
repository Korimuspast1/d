"""Safer, offline Steam local playtime editor for Windows.

This program never asks for administrator rights, never disables networking and
never kills processes. Close Steam yourself before applying a change.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "SteamHoursSafe"
MAX_HOURS = 1_000_000.0
APP_BLOCK_RE = re.compile(r'(?ms)^\s*"(?P<appid>\d+)"\s*\{(?P<body>.*?)^\s*\}')
PLAYTIME_RE = re.compile(r'(?m)^(?P<i>\s*)"Playtime"\s+"(?P<minutes>\d+)"\s*$')
NAME_RE = re.compile(r'(?m)^\s*"name"\s+"(?P<name>[^"]*)"')


@dataclass(frozen=True)
class Game:
    appid: int
    name: str
    minutes: int


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_steam() -> Path | None:
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / "Steam")
    candidates += [Path("C:/Steam"), Path("D:/Steam")]
    try:
        import winreg
        for root, key_name in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(root, key_name) as key:
                    value = winreg.QueryValueEx(key, "SteamPath" if root == winreg.HKEY_CURRENT_USER else "InstallPath")[0]
                    candidates.insert(0, Path(value))
            except OSError:
                pass
    except ImportError:
        pass
    return next((p.resolve() for p in candidates if (p / "steam.exe").is_file()), None)


def is_steam_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
        capture_output=True, text=True, timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
    )
    return "steam.exe" in result.stdout.lower()


def user_configs(steam: Path) -> list[Path]:
    root = steam / "userdata"
    if not root.is_dir():
        return []
    return sorted(
        (p / "config" / "localconfig.vdf" for p in root.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: p.parent.parent.name,
    )


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Файл конфигурации неожиданно большой")
    for encoding in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось определить кодировку localconfig.vdf")


def parse_games(text: str) -> list[Game]:
    games: dict[int, Game] = {}
    for match in APP_BLOCK_RE.finditer(text):
        body = match.group("body")
        playtime = PLAYTIME_RE.search(body)
        if not playtime:
            continue
        appid = int(match.group("appid"))
        name_match = NAME_RE.search(body)
        name = name_match.group("name") if name_match else f"App {appid}"
        games[appid] = Game(appid, name, int(playtime.group("minutes")))
    return sorted(games.values(), key=lambda game: (game.name.casefold(), game.appid))


def replace_playtime(text: str, appid: int, minutes: int) -> str:
    if minutes < 0 or minutes > int(MAX_HOURS * 60):
        raise ValueError("Недопустимое количество минут")
    target = None
    for match in APP_BLOCK_RE.finditer(text):
        if int(match.group("appid")) == appid and PLAYTIME_RE.search(match.group("body")):
            if target is not None:
                raise ValueError("AppID встречается несколько раз; изменение отменено")
            target = match
    if target is None:
        raise ValueError("Игра или поле Playtime не найдены")
    block = target.group(0)
    changed, count = PLAYTIME_RE.subn(
        lambda m: f'{m.group("i")}"Playtime"\t\t"{minutes}"', block, count=1
    )
    if count != 1:
        raise ValueError("Не удалось однозначно изменить Playtime")
    return text[:target.start()] + changed + text[target.end():]


def safe_write(path: Path, new_text: str, encoding: str) -> Path:
    path = path.resolve(strict=True)
    if path.name.lower() != "localconfig.vdf" or path.parent.name.lower() != "config":
        raise ValueError("Разрешено изменять только userdata/<id>/config/localconfig.vdf")
    if not path.parent.parent.name.isdigit() or path.parent.parent.parent.name.lower() != "userdata":
        raise ValueError("Выбранный файл находится вне ожидаемой структуры Steam")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = app_data_dir() / "backups" / path.parent.parent.name
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"localconfig-{stamp}.vdf"
    shutil.copy2(path, backup)

    encoded = new_text.encode(encoding)
    fd, temporary = tempfile.mkstemp(prefix=".localconfig-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
        if path.read_bytes() != encoded:
            raise OSError("Проверка записанного файла не пройдена")
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        shutil.copy2(backup, path)
        raise
    return backup


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Steam Hours Safe")
        self.root.geometry("820x620")
        self.config_path: Path | None = None
        self.games: list[Game] = []

        top = ttk.Frame(root, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Steam:").pack(side="left")
        self.steam_var = tk.StringVar(value=str(find_steam() or ""))
        ttk.Entry(top, textvariable=self.steam_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(top, text="Обзор…", command=self.browse).pack(side="left")
        ttk.Button(top, text="Найти аккаунты", command=self.scan).pack(side="left", padx=(8, 0))

        account = ttk.Frame(root, padding=(12, 0, 12, 8))
        account.pack(fill="x")
        ttk.Label(account, text="Локальный Steam ID:").pack(side="left")
        self.account_box = ttk.Combobox(account, state="readonly", width=24)
        self.account_box.pack(side="left", padx=8)
        self.account_box.bind("<<ComboboxSelected>>", lambda _e: self.load())
        ttk.Button(account, text="Обновить список", command=self.load).pack(side="left")

        columns = ("name", "hours", "appid")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Игра")
        self.tree.heading("hours", text="Локальное время, ч")
        self.tree.heading("appid", text="AppID")
        self.tree.column("name", width=470)
        self.tree.column("hours", width=150, anchor="e")
        self.tree.column("appid", width=120, anchor="e")
        self.tree.pack(fill="both", expand=True, padx=12)

        controls = ttk.Frame(root, padding=12)
        controls.pack(fill="x")
        ttk.Label(controls, text="Новое время (0–1 000 000 часов):").pack(side="left")
        self.hours_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.hours_var, width=16).pack(side="left", padx=8)
        ttk.Button(controls, text="Проверить и применить", command=self.apply).pack(side="left")
        ttk.Button(controls, text="Открыть резервные копии", command=self.open_backups).pack(side="right")

        self.status = tk.StringVar(value="Программа работает офлайн и не требует прав администратора.")
        ttk.Label(root, textvariable=self.status, padding=(12, 0, 12, 12)).pack(fill="x")
        if self.steam_var.get():
            self.scan()

    def browse(self):
        value = filedialog.askdirectory(title="Выберите папку Steam")
        if value:
            self.steam_var.set(value)
            self.scan()

    def scan(self):
        steam = Path(self.steam_var.get()).expanduser()
        if not (steam / "steam.exe").is_file():
            messagebox.showerror("Ошибка", "В папке не найден steam.exe")
            return
        configs = user_configs(steam)
        self._configs = {p.parent.parent.name: p for p in configs}
        self.account_box["values"] = list(self._configs)
        if configs:
            self.account_box.current(0)
            self.load()
        else:
            messagebox.showwarning("Не найдено", "Локальные аккаунты Steam не найдены")

    def load(self):
        account = self.account_box.get()
        if not account or account not in getattr(self, "_configs", {}):
            return
        try:
            self.config_path = self._configs[account]
            text, _ = read_text(self.config_path)
            self.games = parse_games(text)
            self.tree.delete(*self.tree.get_children())
            for game in self.games:
                self.tree.insert("", "end", values=(game.name, f"{game.minutes / 60:.2f}", game.appid))
            self.status.set(f"Найдено игр: {len(self.games)}. Перед изменением полностью закройте Steam.")
        except Exception as exc:
            messagebox.showerror("Ошибка чтения", str(exc))

    def apply(self):
        selected = self.tree.selection()
        if not selected or not self.config_path:
            messagebox.showwarning("Выбор", "Выберите игру")
            return
        try:
            hours = float(self.hours_var.get().strip().replace(",", "."))
            if not 0 <= hours <= MAX_HOURS:
                raise ValueError
        except ValueError:
            messagebox.showerror("Значение", "Введите число от 0 до 1 000 000")
            return
        if is_steam_running():
            messagebox.showerror("Steam запущен", "Полностью закройте Steam и повторите. Программа не завершает процессы автоматически.")
            return
        appid = int(self.tree.item(selected[0], "values")[2])
        minutes = round(hours * 60)
        if not messagebox.askyesno("Подтверждение", f"Изменить локальный Playtime для AppID {appid} на {minutes / 60:.2f} ч?\n\nБудет создана резервная копия."):
            return
        try:
            text, encoding = read_text(self.config_path)
            changed = replace_playtime(text, appid, minutes)
            backup = safe_write(self.config_path, changed, encoding)
            self.load()
            messagebox.showinfo("Готово", f"Файл изменён атомарно.\nРезервная копия:\n{backup}")
        except Exception as exc:
            messagebox.showerror("Изменение отменено", f"Файл не должен быть повреждён.\n\n{exc}")

    def open_backups(self):
        folder = app_data_dir() / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            self.status.set(str(folder))


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
