import tempfile
import unittest
from pathlib import Path

try:
    import tkinter  # noqa: F401
except ImportError:  # Minimal headless test environment; Windows build includes Tk.
    import sys
    import types
    tkinter = types.ModuleType("tkinter")
    tkinter.filedialog = types.SimpleNamespace()
    tkinter.messagebox = types.SimpleNamespace()
    tkinter.ttk = types.SimpleNamespace()
    sys.modules["tkinter"] = tkinter

from steam_hours_safe import parse_games, replace_playtime, safe_write

SAMPLE = '''"apps"\n{\n    "10"\n    {\n        "name"        "Example"\n        "Playtime"    "90"\n        "Playtime2wks" "5"\n    }\n}\n'''

class Tests(unittest.TestCase):
    def test_parse_and_replace_only_playtime(self):
        games = parse_games(SAMPLE)
        self.assertEqual([(10, "Example", 90)], [(g.appid, g.name, g.minutes) for g in games])
        changed = replace_playtime(SAMPLE, 10, 120)
        self.assertIn('"Playtime"\t\t"120"', changed)
        self.assertIn('"Playtime2wks" "5"', changed)

    def test_missing_app_refused(self):
        with self.assertRaises(ValueError):
            replace_playtime(SAMPLE, 999, 1)

    def test_atomic_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "userdata" / "123" / "config" / "localconfig.vdf"
            path.parent.mkdir(parents=True)
            path.write_text(SAMPLE, encoding="utf-8")
            backup = safe_write(path, SAMPLE + "\n", "utf-8")
            self.assertTrue(backup.is_file())
            self.assertEqual(SAMPLE + "\n", path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
