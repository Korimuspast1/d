"""Диагностический скрипт: скачивает сырой XML профиля, сохраняет его и
показывает байты вокруг места, где падает парсинг (если падает)."""
import sys
import xml.etree.ElementTree as ET

import requests

import steam_api

PROFILE = sys.argv[1] if len(sys.argv) > 1 else "https://steamcommunity.com/profiles/76561198037462574/"

ident = steam_api._extract_steamid_from_input(PROFILE)
url = steam_api._build_xml_url(ident)
print("URL:", url)

resp = requests.get(url, headers={"User-Agent": steam_api.USER_AGENT}, timeout=20)
print("status:", resp.status_code)
print("encoding guessed by requests:", resp.encoding)
data = resp.content
print("bytes length:", len(data))

with open("release/debug_raw.xml", "wb") as f:
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
    ET.fromstring(data)
    print("RAW PARSE: OK")
except ET.ParseError as e:
    print("RAW PARSE: FAILED")
    show_error_context(data, e)

    cleaned = steam_api._sanitize_xml_bytes(data)
    with open("release/debug_cleaned.xml", "wb") as f:
        f.write(cleaned)
    try:
        ET.fromstring(cleaned)
        print("CLEANED PARSE: OK")
    except ET.ParseError as e2:
        print("CLEANED PARSE: FAILED")
        show_error_context(cleaned, e2)
