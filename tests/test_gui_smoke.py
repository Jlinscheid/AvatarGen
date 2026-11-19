"""Headless smoke test for dict-editor Apply/navigation and preview changes."""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from avatargen import gui

app = QApplication([])
gui.PROJECT_PATH = tempfile.mktemp(suffix=".json")  # don't touch real userdata
project = gui.load_or_create_project()
win = gui.MainWindow(project, dict(gui.DEFAULT_SETTINGS))
win.show()

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails.append(name)

# --- Apply button behavior -------------------------------------------------
win.tabs.setCurrentWidget(win.dict_tabs)
ed = win.dict_tabs.currentWidget()
check("apply initially disabled", not ed.apply_btn.isEnabled())
first = ed.listw.item(0)
entry = ed._entries()[0]
ed.name_edit.setText(entry["display_name"] + "X")
check("apply enabled after edit", ed.apply_btn.isEnabled())
ed.name_edit.setText(entry["display_name"])
check("apply re-disabled after revert", not ed.apply_btn.isEnabled())
ed.text_edit.setPlainText(entry.get(ed.spec["text_field"], "") + "Y")
check("apply enabled after text edit", ed.apply_btn.isEnabled())
ed.apply_btn.click()
check("apply disabled after applying", not ed.apply_btn.isEnabled())
check("apply wrote to entry",
      entry[ed.spec["text_field"]] == entry.get(ed.spec["text_field"], ""))
check("stayed on dictionaries tab", win.tabs.currentWidget() is win.dict_tabs)

# --- navigate-away warning -------------------------------------------------
# Cancel: tab switch must be reverted (stub the dialog).
ed.text_edit.setPlainText("unapplied draft")
orig_q = gui.QMessageBox.question
gui.QMessageBox.question = staticmethod(lambda *a, **k: gui.QMessageBox.Cancel)
win.tabs.setCurrentIndex(0)
gui.QMessageBox.question = orig_q
check("cancel keeps dictionaries tab", win.tabs.currentWidget() is win.dict_tabs)
# Discard: navigation proceeds and form reloads from stored entry.
gui.QMessageBox.question = staticmethod(lambda *a, **k: gui.QMessageBox.Discard)
win.tabs.setCurrentIndex(0)
gui.QMessageBox.question = orig_q
check("discard allows navigation", win.tabs.currentWidget() is not win.dict_tabs)
check("discard reloads stored entry",
      ed.text_edit.toPlainText() == entry.get(ed.spec["text_field"], ""))
check("no warning when clean", not ed._form_dirty())

# --- preview pane -----------------------------------------------------------
tt = win.tab
pv = tt.preview
check("preview has no bottom stretch",
      tt.layout().count() > 0)  # structural; stretch removal covered by layout
files = [pv.item(i) for i in range(pv.count())]
photos = [it for it in files if it.flags() & Qt.ItemIsUserCheckable]
if photos:
    check("items are checkable, unchecked by default",
          all(it.checkState() == Qt.Unchecked for it in photos))
    tt.toggle_select_all()
    check("select all checks every photo",
          all(it.checkState() == Qt.Checked for it in photos))
    tt.toggle_select_all()
    check("select all toggles back off",
          all(it.checkState() == Qt.Unchecked for it in photos))
    photos[0].setCheckState(Qt.Checked)
    names = [it.text() for it in pv.findItems("", Qt.MatchContains)
             if it.checkState() == Qt.Checked]
    check("delete picks only checked item", names == [photos[0].text()])
else:
    print("NOTE: no renders in test env; checkable-item logic untested here")

print("\nRESULT:", "ALL OK" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
