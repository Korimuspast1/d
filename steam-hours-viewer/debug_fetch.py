"""Диагностический скрипт: скачивает сырой XML профиля (той же логикой, что
и само приложение — с "прогревом" cookies через обычную страницу профиля),
сохраняет его и показывает байты вокруг места, где падает парсинг (если
падает)."""
import sys
import xml.etree.ElementTree as ET

import requests

import steam_api

PROFILE = sys.argv[1] if len(sys.argv) > 1 else "https://steamcommunity.com/profiles/76561198037462574/"

ident = steam_api._extract_steamid_from_input(PROFILE)
base_url = steam_api._base_profile_url(ident)
url = steam_api._build_xml_url(ident)
print("Base URL:", base_url)
print("XML URL:", url)

session = requests.Session()
headers = steam_api._browser_like_headers(base_url)

warm = session.get(base_url, headers=headers, timeout=20)
print("warm-up status:", warm.status_code, "cookies:", dict(session.cookies))

resp = session.get(url, headers=headers, timeout=20)
print("status:", resp.status_code)
print("encoding guessed by requests:", resp.encoding)
data = resp.content
print("bytes length:", len(data))

with open("ci_debug/debug_raw.xml", "wb") as f:
    f.write(data)


def show_error_context(data: bytes, exc: ET.ParseError):
    lines = data.split(b"\n")
    line_no = exc.position[0]
    col_no = exc.position[1]
    print(f"ParseError at line {line_no}, column {col_no}: {exc}")
    if 1 <= line_no <= len(lines):
        bad_line = lines[line_no - 1]
        start = max(0, col_no - 60)
        end = min(len(bad_line), col_no + 60)
        print("Context bytes:", bad_line[start:end])
        print("Context repr :", repr(bad_line[start:end]))
        if col_no < len(bad_line):
            print("Byte at column:", hex(bad_line[col_no]))


try:
    games = steam_api._parse_games_xml(data)
    print(f"PARSE: OK — {len(games)} games")
except steam_api.SteamXmlUnavailableError as e:
    print("PARSE: STILL BLOCKED (html-looking response):", e)
except steam_api.SteamApiError as e:
    print("PARSE: FAILED:", e)
    try:
        ET.fromstring(data)
    except ET.ParseError as exc:
        show_error_context(data, exc)
