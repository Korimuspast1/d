import os
import tempfile

import pytest

import steam_api


SAMPLE_XML_OK = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<response>
  <steamID64>76561197960287930</steamID64>
  <steamID><![CDATA[Example]]></steamID>
  <games>
    <game>
      <appID>730</appID>
      <name><![CDATA[Counter-Strike 2]]></name>
      <logo>http://example.com/730.jpg</logo>
      <hoursLast2Weeks>3.2</hoursLast2Weeks>
      <hoursOnRecord>1,234.5</hoursOnRecord>
    </game>
    <game>
      <appID>570</appID>
      <name><![CDATA[Dota 2]]></name>
      <logo>http://example.com/570.jpg</logo>
      <hoursOnRecord>87</hoursOnRecord>
    </game>
  </games>
</response>
"""

SAMPLE_XML_PRIVATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<response>
  <error>This profile is private.</error>
</response>
"""

SAMPLE_XML_NOTFOUND = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<response>
  <error>The specified profile could not be found.</error>
</response>
"""


def test_parse_games_xml_ok():
    games = steam_api._parse_games_xml(SAMPLE_XML_OK)
    assert len(games) == 2
    cs2 = next(g for g in games if g.appid == 730)
    assert cs2.name == "Counter-Strike 2"
    assert cs2.hours_official == 1234.5
    assert cs2.hours_last_2weeks == 3.2
    dota = next(g for g in games if g.appid == 570)
    assert dota.hours_official == 87.0


def test_parse_games_xml_private():
    with pytest.raises(steam_api.ProfilePrivateError):
        steam_api._parse_games_xml(SAMPLE_XML_PRIVATE)


def test_parse_games_xml_notfound():
    with pytest.raises(steam_api.ProfileNotFoundError):
        steam_api._parse_games_xml(SAMPLE_XML_NOTFOUND)


def test_extract_steamid_variants():
    assert steam_api._extract_steamid_from_input("https://steamcommunity.com/id/myname/") == "myname"
    assert steam_api._extract_steamid_from_input("https://steamcommunity.com/profiles/76561197960287930") == "76561197960287930"
    assert steam_api._extract_steamid_from_input("myname") == "myname"
    assert steam_api._extract_steamid_from_input("  76561197960287930 ") == "76561197960287930"


def test_build_xml_url():
    assert "profiles/76561197960287930" in steam_api._build_xml_url("76561197960287930")
    assert "id/myname" in steam_api._build_xml_url("myname")


def test_display_hours_and_override():
    g = steam_api.Game(appid=1, name="Test", hours_official=10.0)
    assert g.display_hours == 10.0
    assert g.is_overridden is False
    g.override_hours = 9999.0
    assert g.display_hours == 9999.0
    assert g.is_overridden is True


def test_overrides_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "overrides.json")
        assert steam_api.load_overrides(path) == {}
        data = {730: 5000.0, 570: 12.5}
        steam_api.save_overrides(path, data)
        loaded = steam_api.load_overrides(path)
        assert loaded == data


def test_apply_overrides():
    games = [steam_api.Game(appid=730, name="CS2", hours_official=100.0)]
    steam_api.apply_overrides(games, {730: 7777.0})
    assert games[0].display_hours == 7777.0


def test_parse_hours_string_variants():
    assert steam_api._parse_hours_string("1,234.5") == 1234.5
    assert steam_api._parse_hours_string("") == 0.0
    assert steam_api._parse_hours_string("abc") == 0.0
    assert steam_api._parse_hours_string("42") == 42.0
