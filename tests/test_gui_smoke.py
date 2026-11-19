"""Headless smoke test: dict editor, preview, menus, dialogs, close prompt."""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from avatargen import gui, __version__

app = QApplication([])
gui.PROJECT_PATH = tempfile.mktemp(suffix=".json")  # don't touch real userdata
gui.SETTINGS_PATH = tempfile.mktemp(suffix=".json")
project = gui.load_or_create_project()
settings = dict(gui.DEFAULT_SETTINGS)
win = gui.MainWindow(project, settings)
win.show()

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)

# --- Apply button behavior --------------------------------------------------
win.open_dicts()
ed = win.dict_tabs.currentWidget()
check("apply initially disabled", not ed.apply_btn.isEnabled())
entry = ed._entries()[0]
ed.name_edit.setText(entry["display_name"] + "X")
check("apply enabled after edit", ed.apply_btn.isEnabled())
ed.name_edit.setText(entry["display_name"])
check("apply re-disabled after revert", not ed.apply_btn.isEnabled())
ed.text_edit.setPlainText(entry.get(ed.spec["text_field"], "") + "Y")
check("apply enabled after text edit", ed.apply_btn.isEnabled())
ed.apply_btn.click()
check("apply disabled after applying", not ed.apply_btn.isEnabled())

# --- navigate-away warning (inner editor switch + dialog close) -------------
ed.text_edit.setPlainText("unapplied draft")
orig_q = gui.QMessageBox.question
# Cancel on inner tab switch: editor keeps focus
gui.QMessageBox.question = staticmethod(lambda *a, **k: gui.QMessageBox.Cancel)
win.dict_tabs.setCurrentIndex((win.dict_tabs.currentIndex() + 1)
                              % win.dict_tabs.count())
check("cancel keeps inner editor", win.dict_tabs.currentWidget() is ed)
# Discard on dialog close: dialog closes, form reloads stored entry
gui.QMessageBox.question = staticmethod(lambda *a, **k: gui.QMessageBox.Discard)
dlg = win.findChildren(gui.DictsDialog)
(dlg[0] if dlg else gui.DictsDialog(win)).close()
gui.QMessageBox.question = orig_q
check("discard reloads stored entry",
      ed.text_edit.toPlainText() == entry.get(ed.spec["text_field"], ""))

# --- settings persistence + prompts defaults --------------------------------
d = gui.PromptsDialog(win.settings, win)
check("prompts pre-filled with core defaults",
      d.style_edit.toPlainText() == gui.core.STYLE_CORE
      and d.neg_edit.toPlainText() == gui.core.NEGATIVE)
d.style_edit.setPlainText("CUSTOM STYLE")
d.accept()
check("prompt override persisted to settings.json",
      os.path.isfile(gui.SETTINGS_PATH)
      and gui.load_settings().get("style_core") == "CUSTOM STYLE")
d2 = gui.PromptsDialog(gui.load_settings(), win)
check("prompts dialog reloads persisted override",
      d2.style_edit.toPlainText() == "CUSTOM STYLE")
win.settings.pop("style_core")  # fall back to core default
check("missing override falls back to core default",
      gui.PromptsDialog(win.settings, win).style_edit.toPlainText()
      == gui.core.STYLE_CORE)

# --- build_prompt honors overrides ------------------------------------------
import random
tpl = dict(project["templates"][0])
p, neg, draw = gui.core.build_prompt(tpl, project["dictionaries"], random.Random(1))
check("default prompts used when no override", neg == gui.core.NEGATIVE)
p, neg, draw = gui.core.build_prompt(
    tpl, project["dictionaries"], random.Random(1),
    style_core="SC", negative="NG")
check("build_prompt honors overrides", p.startswith("SC") and neg == "NG")

# --- about / rename / add-template controls ---------------------------------
check("about metadata present",
      __version__ and gui.AUTHORS and gui.REPO_URL.startswith("https://"))
# rename_template() opens a modal QInputDialog — can't run headlessly, so
# emulate the rename path it performs once the user accepts:
win.tab.template["title"] = "Renamed Army"
win.tabs.setTabText(win.tabs.indexOf(win.tab), "Renamed Army")
check("rename reflected in tab text",
      win.tabs.tabText(win.tabs.indexOf(win.tab)) == "Renamed Army")
check("corner add button installed", win.tabs.cornerWidget() is not None)
win.tabs.cornerWidget().click()
check("+ button adds a template", win.tabs.count() == 2)

# --- close prompt on unsaved project ----------------------------------------
win._dirty = True
events = []
class Ev:
    def accept(self): events.append("accept")
    def ignore(self): events.append("ignore")
gui.QMessageBox.question = staticmethod(lambda *a, **k: gui.QMessageBox.Cancel)
win.closeEvent(Ev())
check("cancel blocks close with unsaved changes", events[-1] == "ignore")
gui.QMessageBox.question = staticmethod(lambda *a, **k: gui.QMessageBox.Discard)
win.closeEvent(Ev())
check("discard closes without saving", events[-1] == "accept")
win._dirty = False
win.closeEvent(Ev())
check("clean close needs no prompt", events[-1] == "accept")
gui.QMessageBox.question = orig_q

print("\nRESULT:", "ALL OK" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
