"""
steam_api.py
Логика получения данных об играх и часах из Steam.

Используются два способа получения данных (без необходимости в API-ключе):
1. Публичный XML-профиль Steam Community:
   https://steamcommunity.com/id/<vanity>/games?tab=all&xml=1
   https://steamcommunity.com/profiles/<steamid64>/games?tab=all&xml=1
   Работает, если у пользователя в настройках приватности профиля
   включено "Отображать информацию об играх" (My Profile -> Game details -> Public).

2. Официальный Steam Web API (если указан api_key) — используется как запасной
   вариант, либо для более точного резолва vanity-URL в SteamID64.

Модуль не зависит от tkinter и может быть протестирован отдельно.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

import requests

USER_AGENT = "SteamHoursViewer/1.0 (+https://store.steampowered.com)"
REQUEST_TIMEOUT = 12


class SteamApiError(Exception):
    """Базовая ошибка при обращении к Steam."""


class ProfileNotFoundError(SteamApiError):
    pass


class ProfilePrivateError(SteamApiError):
    pass


@dataclass
class Game:
    appid: int
    name: str
    hours_official: float            # реальное время из Steam (часы, с округлением до сотых)
    hours_last_2weeks: float = 0.0
    logo_url: str = ""
    override_hours: Optional[float] = None  # пользовательское (визуальное) значение

    @property
    def display_hours(self) -> float:
        """То значение, которое должно показываться в интерфейсе."""
        return self.override_hours if self.override_hours is not None else self.hours_official

    @property
    def is_overridden(self) -> bool:
        return self.override_hours is not None

    def to_dict(self) -> dict:
        return {
            "appid": self.appid,
            "name": self.name,
            "hours_official": self.hours_official,
            "hours_last_2weeks": self.hours_last_2weeks,
            "logo_url": self.logo_url,
        }


def _extract_steamid_from_input(raw: str) -> str:
    """Достаёт vanity-имя или steamid64 из произвольной ссылки/строки,
    которую мог вставить пользователь."""
    raw = raw.strip()
    if not raw:
        raise ValueError("Пустая строка профиля")

    # Полная ссылка вида https://steamcommunity.com/id/xxxx или /profiles/7656...
    m = re.search(r"steamcommunity\.com/(id|profiles)/([^/\s?]+)", raw)
    if m:
        return m.group(2)

    return raw


def _build_xml_url(ident: str) -> str:
    """ident может быть steamid64 (17 цифр) или vanity-именем."""
    if re.fullmatch(r"\d{17}", ident):
        return f"https://steamcommunity.com/profiles/{ident}/games?tab=all&xml=1"
    return f"https://steamcommunity.com/id/{ident}/games?tab=all&xml=1"


def _sanitize_xml_bytes(data: bytes) -> bytes:
    """Steam иногда отдаёт XML с мусором, который формально невалиден:
    - управляющие символы, недопустимые в XML 1.0 (например из названий
      игр с кириллицей/эмодзи/битой кодировкой);
    - "голые" амперсанды, не экранированные как &amp; (встречается в
      названиях некоторых игр/DLC).
    Эта функция чистит самые частые причины ошибки
    'not well-formed (invalid token)', не трогая валидный XML.
    """
    # Убираем запрещённые в XML 1.0 управляющие символы (кроме \t \n \r)
    data = re.sub(rb"[\x00-\x08\x0B\x0C\x0E-\x1F]", b"", data)

    # Экранируем "голые" амперсанды: & не являющийся началом сущности
    # (&amp; &lt; &gt; &quot; &apos; &#123; &#x1F;)
    data = re.sub(rb"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)", b"&amp;", data)

    return data


def _parse_games_xml(xml_data) -> List[Game]:
    if isinstance(xml_data, str):
        xml_data = xml_data.encode("utf-8", errors="replace")

    xml_data = xml_data.strip()
    if not xml_data:
        raise SteamApiError("Пустой ответ от Steam")

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        # Пробуем автоматически исправить типичный "битый" XML от Steam
        # и разобрать ещё раз, прежде чем сдаваться.
        try:
            root = ET.fromstring(_sanitize_xml_bytes(xml_data))
        except ET.ParseError as exc:
            raise SteamApiError(f"Не удалось разобрать XML ответа Steam: {exc}") from exc


    # Steam отдаёт <response><error>...</error></response> если профиль
    # не найден или приватен
    error_node = root.find("error")
    if error_node is not None and error_node.text:
        text = error_node.text.strip()
        if "private" in text.lower() or "приват" in text.lower():
            raise ProfilePrivateError(text)
        raise ProfileNotFoundError(text)

    games_node = root.find("games")
    if games_node is None:
        # Профиль существует, но детали игр скрыты
        raise ProfilePrivateError(
            "Steam не вернул список игр. Вероятно, в настройках приватности "
            "профиля отключено отображение информации об играх."
        )

    games: List[Game] = []
    for g in games_node.findall("game"):
        appid_text = (g.findtext("appID") or "0").strip()
        name = (g.findtext("name") or f"App {appid_text}").strip()
        hours_text = (g.findtext("hoursOnRecord") or "0").strip()
        hours_2w_text = (g.findtext("hoursLast2Weeks") or "0").strip()
        logo = (g.findtext("logo") or "").strip()

        try:
            appid = int(appid_text)
        except ValueError:
            continue

        hours = _parse_hours_string(hours_text)
        hours_2w = _parse_hours_string(hours_2w_text)

        games.append(
            Game(
                appid=appid,
                name=name,
                hours_official=hours,
                hours_last_2weeks=hours_2w,
                logo_url=logo,
            )
        )

    return games


def _parse_hours_string(value: str) -> float:
    """Steam отдаёт часы вида '1,234.5' (запятая как разделитель тысяч)."""
    if not value:
        return 0.0
    cleaned = value.replace(",", "")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return 0.0


def fetch_games_via_xml(profile: str, session: Optional[requests.Session] = None) -> List[Game]:
    """Получить список игр и часов через публичный XML Steam Community."""
    ident = _extract_steamid_from_input(profile)
    url = _build_xml_url(ident)

    sess = session or requests.Session()
    resp = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)

    if resp.status_code == 404:
        raise ProfileNotFoundError("Профиль не найден (404). Проверьте ссылку / SteamID.")
    resp.raise_for_status()

    # Используем "сырые" байты, а не resp.text — так ElementTree сам
    # разбирает декларацию кодировки из XML-пролога и не зависит от того,
    # правильно ли requests угадал кодировку ответа.
    return _parse_games_xml(resp.content)


@dataclass
class ProfileInfo:
    display_name: str = ""
    avatar_url: str = ""
    steamid64: str = ""


def fetch_profile_info(profile: str, session: Optional[requests.Session] = None) -> ProfileInfo:
    """Получает ник и аватар профиля через публичный XML Steam Community
    (отдельный от списка игр эндпоинт)."""
    ident = _extract_steamid_from_input(profile)
    if re.fullmatch(r"\d{17}", ident):
        url = f"https://steamcommunity.com/profiles/{ident}/?xml=1"
    else:
        url = f"https://steamcommunity.com/id/{ident}/?xml=1"

    sess = session or requests.Session()
    try:
        resp = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.content
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            root = ET.fromstring(_sanitize_xml_bytes(data))

        info = ProfileInfo()
        info.display_name = (root.findtext("steamID") or "").strip()
        info.avatar_url = (root.findtext("avatarFull") or root.findtext("avatarMedium") or "").strip()
        info.steamid64 = (root.findtext("steamID64") or "").strip()
        return info
    except Exception:  # noqa: BLE001
        return ProfileInfo()


def resolve_vanity_to_steamid64(vanity: str, api_key: str, session: Optional[requests.Session] = None) -> str:
    """Через официальный Steam Web API превращает vanity-имя в SteamID64."""
    sess = session or requests.Session()
    url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
    resp = sess.get(
        url,
        params={"key": api_key, "vanityurl": vanity},
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json().get("response", {})
    if data.get("success") != 1:
        raise ProfileNotFoundError("Не удалось определить SteamID по указанному имени профиля.")
    return data["steamid"]


def fetch_games_via_web_api(steamid64: str, api_key: str, session: Optional[requests.Session] = None) -> List[Game]:
    """Запасной способ — официальный Steam Web API (нужен ключ)."""
    sess = session or requests.Session()
    url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
    resp = sess.get(
        url,
        params={
            "key": api_key,
            "steamid": steamid64,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json().get("response", {})
    if "games" not in payload:
        raise ProfilePrivateError(
            "Steam API не вернул список игр. Профиль приватный, либо ключ API недействителен."
        )

    games: List[Game] = []
    for g in payload["games"]:
        appid = int(g.get("appid", 0))
        name = g.get("name", f"App {appid}")
        minutes = float(g.get("playtime_forever", 0))
        minutes_2w = float(g.get("playtime_2weeks", 0))
        icon_hash = g.get("img_icon_url", "")
        logo_url = (
            f"https://media.steampowered.com/steamcommunity/public/images/apps/{appid}/{icon_hash}.jpg"
            if icon_hash
            else ""
        )
        games.append(
            Game(
                appid=appid,
                name=name,
                hours_official=round(minutes / 60.0, 2),
                hours_last_2weeks=round(minutes_2w / 60.0, 2),
                logo_url=logo_url,
            )
        )
    return games


def fetch_games(profile: str, api_key: Optional[str] = None) -> List[Game]:
    """
    Главная точка входа.
    1. Пытается получить данные через открытый XML (без ключа).
    2. Если не получилось и есть api_key — пробует официальный Web API.
    """
    session = requests.Session()
    try:
        return fetch_games_via_xml(profile, session=session)
    except (ProfilePrivateError, ProfileNotFoundError, SteamApiError):
        if not api_key:
            raise
        ident = _extract_steamid_from_input(profile)
        if not re.fullmatch(r"\d{17}", ident):
            ident = resolve_vanity_to_steamid64(ident, api_key, session=session)
        return fetch_games_via_web_api(ident, api_key, session=session)


# ---------------------------------------------------------------------------
# Локальное хранение пользовательских ("визуальных") переопределений часов
# ---------------------------------------------------------------------------

def load_overrides(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


def save_overrides(path: str, overrides: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in overrides.items()}, f, ensure_ascii=False, indent=2)


def apply_overrides(games: List[Game], overrides: dict) -> None:
    for game in games:
        if game.appid in overrides:
            game.override_hours = overrides[game.appid]
