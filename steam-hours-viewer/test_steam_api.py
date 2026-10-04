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


def test_parse_games_xml_with_bare_ampersand():
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<response>
  <games>
    <game>
      <appID>1</appID>
      <name><![CDATA[Tom & Jerry]]></name>
      <hoursOnRecord>10</hoursOnRecord>
    </game>
  </games>
</response>
"""
    games = steam_api._parse_games_xml(xml)
    assert games[0].name == "Tom & Jerry"


def test_parse_games_xml_with_invalid_control_char():
    # \x02 is an invalid XML 1.0 character and will break strict parsing
    xml_bytes = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
        b"<response><games><game><appID>2</appID>"
        b"<name><![CDATA[Broken\x02Name]]></name>"
        b"<hoursOnRecord>5</hoursOnRecord></game></games></response>"
    )
    games = steam_api._parse_games_xml(xml_bytes)
    assert len(games) == 1
    assert games[0].appid == 2


def test_parse_games_xml_with_raw_bad_ampersand_bytes():
    xml_bytes = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
        b"<response><games><game><appID>3</appID>"
        b"<name>Test & Co</name>"
        b"<hoursOnRecord>7</hoursOnRecord></game></games></response>"
    )
    games = steam_api._parse_games_xml(xml_bytes)
    assert len(games) == 1
    assert games[0].name == "Test & Co"


def test_parse_games_xml_html_instead_of_xml_raises_specific_error():
    html = b"""<!DOCTYPE html>
<html><head><script type="text/javascript">Object.seal && [1,2].map(function(x){});</script></head>
<body>Sign In</body></html>"""
    with pytest.raises(steam_api.SteamXmlUnavailableError):
        steam_api._parse_games_xml(html)


def test_looks_like_html_detection():
    assert steam_api._looks_like_html(b"<!DOCTYPE html><html></html>")
    assert steam_api._looks_like_html(b"<html><head></head></html>")
    assert not steam_api._looks_like_html(b'<?xml version="1.0"?><response></response>')


def test_sanitize_xml_bytes_escapes_bare_ampersand():
    data = b"<a>Tom & Jerry &amp; Friends</a>"
    cleaned = steam_api._sanitize_xml_bytes(data)
    assert cleaned == b"<a>Tom &amp; Jerry &amp; Friends</a>"


SAMPLE_BASE_PROFILE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><profile>
    <steamID64>76561198037462574</steamID64>
    <steamID><![CDATA[Jazz]]></steamID>
    <privacyState>public</privacyState>
    <visibilityState>3</visibilityState>
    <mostPlayedGames>
        <mostPlayedGame>
            <gameName><![CDATA[BeamNG.drive]]></gameName>
            <gameLink><![CDATA[https://steamcommunity.com/app/284160]]></gameLink>
            <gameLogo><![CDATA[http://example.com/284160.jpg]]></gameLogo>
            <hoursPlayed>8.6</hoursPlayed>
            <hoursOnRecord>272</hoursOnRecord>
            <statsName><![CDATA[284160]]></statsName>
        </mostPlayedGame>
        <mostPlayedGame>
            <gameName><![CDATA[Crusader Kings III]]></gameName>
            <gameLogo><![CDATA[http://example.com/1158310.jpg]]></gameLogo>
            <hoursPlayed>3.7</hoursPlayed>
            <hoursOnRecord>1,402</hoursOnRecord>
            <statsName><![CDATA[1158310]]></statsName>
        </mostPlayedGame>
    </mostPlayedGames>
</profile>
"""


def test_parse_most_played_games():
    games = steam_api.parse_most_played_games(SAMPLE_BASE_PROFILE_XML)
    assert len(games) == 2
    beamng = next(g for g in games if g.appid == 284160)
    assert beamng.name == "BeamNG.drive"
    assert beamng.hours_official == 272.0
    assert beamng.hours_last_2weeks == 8.6
    ck3 = next(g for g in games if g.appid == 1158310)
    assert ck3.hours_official == 1402.0


def test_parse_most_played_games_empty_when_missing():
    xml = '<?xml version="1.0"?><profile><steamID64>1</steamID64></profile>'
    assert steam_api.parse_most_played_games(xml) == []


def test_custom_games_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "custom_games.json")
        assert steam_api.load_custom_games(path) == []

        games = [
            steam_api.Game(appid=-1, name="My Fake Game", hours_official=1500.0),
            steam_api.Game(appid=-2, name="Another One", hours_official=42.5),
        ]
        steam_api.save_custom_games(path, games)
        loaded = steam_api.load_custom_games(path)
        assert len(loaded) == 2
        assert {g.name for g in loaded} == {"My Fake Game", "Another One"}
        assert all(g.appid < 0 for g in loaded)


def test_next_custom_appid():
    assert steam_api.next_custom_appid([]) == steam_api.CUSTOM_GAME_APPID_START
    existing = [steam_api.Game(appid=-1, name="A", hours_official=1), steam_api.Game(appid=-3, name="B", hours_official=2)]
    assert steam_api.next_custom_appid(existing) == -4


def test_parse_hours_string_variants():
    assert steam_api._parse_hours_string("1,234.5") == 1234.5
    assert steam_api._parse_hours_string("") == 0.0
    assert steam_api._parse_hours_string("abc") == 0.0
    assert steam_api._parse_hours_string("42") == 42.0
