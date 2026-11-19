"""AvatarGen GUI (PySide6) — prototype per D36-D45."""
from __future__ import annotations

import json
import os
import random

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QListView,
    QMainWindow, QMessageBox, QInputDialog,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from . import core
from . import __version__, AUTHORS, REPO_URL
from .logging_util import get_logger, setup_logging

log = get_logger("gui")

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DICTS = os.path.join(APP_DIR, "dictionaries.json")
DEFAULT_USER_DIR = os.path.join(APP_DIR, "userdata")
RENDER_DIR = os.path.join(DEFAULT_USER_DIR, "renders")
PROJECT_PATH = os.path.join(DEFAULT_USER_DIR, "project.json")
SETTINGS_PATH = os.path.join(DEFAULT_USER_DIR, "settings.json")


class RenderWorker(QThread):
    """Generates a batch in a worker thread; abortable (D5/D41)."""
    progress = Signal(int, int)          # done, total
    image_done = Signal(dict)            # draw record
    finished_batch = Signal(str)         # status message
    failed = Signal(str)

    def __init__(self, template, dicts, settings):
        super().__init__()
        self.template = template
        self.dicts = dicts
        self.settings = settings
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        n = self.settings["count"]
        timeout = self.settings.get("timeout", 600)
        retries = self.settings.get("retries", 2)
        log.info("batch start: template=%s count=%d seed=%d endpoint=%s timeout=%ss retries=%d",
                 self.template["id"], n, self.settings["seed"], self.settings["endpoint"],
                 timeout, retries)
        client = core.ComfyClient(self.settings["endpoint"], self.settings["checkpoint"])
        rng = random.Random(self.settings["seed"])
        outdir = os.path.join(RENDER_DIR, self.template["id"])
        os.makedirs(outdir, exist_ok=True)
        manifest_path = os.path.join(outdir, "manifest.jsonl")
        done = 0
        try:
            for i in range(n):
                if self._abort:
                    log.info("abort requested at %d/%d", done, n)
                    break
                prompt, negative, draw = core.build_prompt(
                    self.template, self.dicts, rng,
                    style_core=self.settings.get("style_core") or None,
                    negative=self.settings.get("negative_prompt") or None)
                prefix = f"{draw['template_id']}_{i:04d}_{draw['seed']:010d}"
                wf = core.workflow(prompt, negative, draw["seed"],
                                   self.settings["checkpoint"], prefix,
                                   self.settings["width"], self.settings["height"])
                outputs = None
                for attempt in range(1 + retries):
                    if self._abort:
                        break
                    try:
                        outputs = client.queue_and_wait(wf, timeout=timeout)
                        break
                    except Exception as e:  # noqa: BLE001
                        if attempt < retries:
                            # Perturb the seed: an identical workflow would be
                            # fully cached by ComfyUI (execution_cached on all
                            # nodes), replaying a dead prior run forever.
                            wf["2"]["inputs"]["seed"] = (
                                draw["seed"] + attempt + 1) % (2**31)
                            log.warning("image %s attempt %d failed (%s); "
                                        "retrying with seed %d",
                                        prefix, attempt + 1, e,
                                        wf["2"]["inputs"]["seed"])
                        else:
                            raise
                for out in outputs:
                    ext = out["filename"].rsplit(".", 1)[-1] if "." in out["filename"] else "png"
                    client.fetch_image(out, os.path.join(outdir, f"{prefix}.{ext}"))
                if outputs:
                    ext = outputs[0]["filename"].rsplit(".", 1)[-1] if "." in outputs[0]["filename"] else "png"
                    log.info("saved render %s", os.path.join(outdir, prefix + "." + ext))
                with open(manifest_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(draw) + "\n")
                done += 1
                self.progress.emit(done, n)
                self.image_done.emit(draw)
            log.info("batch finished: %d/%d (aborted=%s)", done, n, self._abort)
            self.finished_batch.emit(
                f"Aborted after {done}/{n}" if self._abort else f"Done: {done}/{n}")
        except Exception as e:  # noqa: BLE001 — surface to UI
            log.error("batch failed at %d/%d: %s", done + 1, n, e)
            self.failed.emit(f"Failed at {done + 1}/{n}: {e}")


class SettingsDialog(QDialog):
    """Global settings (D42): seed, endpoint, model, threshold, output, size/quality."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings
        form = QFormLayout(self)

        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        self.seed.setValue(settings["seed"])
        form.addRow("App seed", self.seed)

        self.logging = QCheckBox("Enable logging (userdata/logs/avatargen.log)")
        self.logging.setChecked(settings.get("logging", False))
        form.addRow("", self.logging)

        h = QHBoxLayout()
        self.endpoint = QLineEdit(settings["endpoint"])
        test = QPushButton("Test")
        test.clicked.connect(self.test)
        h.addWidget(self.endpoint)
        h.addWidget(test)
        form.addRow("ComfyUI endpoint", h)

        self.model = QComboBox()
        self.refresh = QPushButton("Refresh list")
        self.refresh.clicked.connect(self.refresh_models)
        mh = QHBoxLayout()
        mh.addWidget(self.model)
        mh.addWidget(self.refresh)
        form.addRow("Checkpoint", mh)

        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100000)
        self.threshold.setValue(settings["threshold"])
        form.addRow("Batch warning threshold", self.threshold)

        self.count_default = QSpinBox()
        self.count_default.setRange(1, 100000)
        self.count_default.setValue(settings["count_default"])
        form.addRow("Default image count", self.count_default)

        self.outdir = QLineEdit(settings["output_dir"])
        form.addRow("Output directory", self.outdir)

        self.width = QSpinBox(); self.width.setRange(256, 2048); self.width.setValue(settings["width"])
        self.height = QSpinBox(); self.height.setRange(256, 2048); self.height.setValue(settings["height"])
        form.addRow("Image size", self.width)
        form.addRow("", self.height)

        self.quality = QSpinBox(); self.quality.setRange(1, 100); self.quality.setValue(settings["quality"])
        form.addRow("JPEG quality", self.quality)

        self.timeout = QSpinBox(); self.timeout.setRange(60, 7200); self.timeout.setValue(settings.get("timeout", 600))
        self.timeout.setSuffix(" s")
        form.addRow("Per-image timeout", self.timeout)

        self.retries = QSpinBox(); self.retries.setRange(0, 10); self.retries.setValue(settings.get("retries", 2))
        form.addRow("Per-image retries", self.retries)

        pp = QLineEdit()
        pp.setPlaceholderText("reserved — post-processing pipeline (future)")
        pp.setEnabled(False)
        form.addRow("Post-processing", pp)

        self.refresh_models()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def test(self):
        try:
            version = core.ComfyClient(self.endpoint.text().strip(),
                                       self.settings["checkpoint"]).test_connection()
            QMessageBox.information(self, "Connection OK", version)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Connection failed", str(e))

    def refresh_models(self):
        self.model.clear()
        try:
            self.model.addItems(core.ComfyClient(
                self.endpoint.text().strip(), "").list_checkpoints())
        except Exception:  # noqa: BLE001 — offline is fine
            self.model.addItem(self.settings["checkpoint"])
        idx = self.model.findText(self.settings["checkpoint"])
        self.model.setCurrentIndex(max(idx, 0))

    def accept(self):
        self.settings.update({
            "seed": self.seed.value(),
            "logging": self.logging.isChecked(),
            "endpoint": self.endpoint.text().strip(),
            "checkpoint": self.model.currentText(),
            "threshold": self.threshold.value(),
            "count_default": self.count_default.value(),
            "output_dir": self.outdir.text().strip(),
            "width": self.width.value(), "height": self.height.value(),
            "quality": self.quality.value(),
            "timeout": self.timeout.value(), "retries": self.retries.value(),
        })
        super().accept()


class PromptsDialog(QDialog):
    """Global default prompt / negative prompt (Options menu). These are
    prepended to every generated prompt / base of every negative; per-template
    injections are added on top by core.build_prompt."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Default prompts")
        self.settings = settings
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Style core (prepended to every prompt):"))
        self.style_edit = QPlainTextEdit()
        self.style_edit.setPlainText(
            settings.get("style_core") or core.STYLE_CORE)
        self.style_edit.setFixedHeight(110)
        lay.addWidget(self.style_edit)
        lay.addWidget(QLabel(
            "Default negative (base of every negative prompt):"))
        self.neg_edit = QPlainTextEdit()
        self.neg_edit.setPlainText(
            settings.get("negative_prompt") or core.NEGATIVE)
        self.neg_edit.setFixedHeight(110)
        lay.addWidget(self.neg_edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        self.settings["style_core"] = self.style_edit.toPlainText().strip()
        self.settings["negative_prompt"] = self.neg_edit.toPlainText().strip()
        save_settings(self.settings)
        log.info("prompt defaults updated (style %d chars, negative %d chars)",
                 len(self.settings["style_core"]),
                 len(self.settings["negative_prompt"]))
        super().accept()


DICT_SPECS = {
    "subject_types": {"label": "Subject Type", "text_field": "prompt_word",
                      "text_label": "Prompt word (male / neutral)",
                      "extra_text_fields": [("prompt_word_female",
                                             "Prompt word (female, optional)")],
                      "bool_fields": [("military",
                                       "Military (officer insignia & branch word)")]},
    "sides": {"label": "Side / Nation", "text_field": "flavor",
              "text_label": "Flavor (prompt vocabulary)"},
    "uniforms": {"label": "Uniform", "text_field": "prompt_text",
                 "text_label": "Uniform prompt text", "applies_to": True},
    "compositions": {"label": "Composition", "text_field": "prompt_text",
                     "text_label": "Composition prompt text", "applies_to": True},
    "ethnicities": {"label": "Ethnicity", "text_field": "prompt",
                    "text_label": "Prompt descriptor"},
}


class DictEditor(QWidget):
    """Add/delete/edit entries of one dictionary (D47); edits propagate to
    template dropdowns via the on_change callback."""

    def __init__(self, key: str, dicts: dict, on_change, parent=None):
        super().__init__(parent)
        self.key = key
        self.spec = DICT_SPECS[key]
        self.dicts = dicts
        self.on_change = on_change

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.listw = QListWidget()
        self.listw.currentItemChanged.connect(self.on_select)
        left.addWidget(self.listw)
        btns = QHBoxLayout()
        add = QPushButton("Add"); add.clicked.connect(self.add)
        rm = QPushButton("Delete"); rm.clicked.connect(self.delete)
        btns.addWidget(add); btns.addWidget(rm)
        left.addLayout(btns)
        left.addStretch(1)  # pin entry list to top-left on resize (D50)
        root.addLayout(left, 1)

        form = QVBoxLayout()
        form.addWidget(QLabel("Display name"))
        self.name_edit = QLineEdit()
        form.addWidget(self.name_edit)
        form.addWidget(QLabel(self.spec["text_label"]))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(90)
        form.addWidget(self.text_edit)
        self.extra_edits = {}
        for key, label in self.spec.get("extra_text_fields", []):
            form.addWidget(QLabel(label))
            w = QLineEdit()
            form.addWidget(w)
            self.extra_edits[key] = w
        self.bool_checks = {}
        for key, label in self.spec.get("bool_fields", []):
            cb = QCheckBox(label)
            form.addWidget(cb)
            self.bool_checks[key] = cb
        if self.spec.get("applies_to"):
            self.applies = {}
            self.applies_box = QGroupBox("Applies to subject types")
            ag = QGridLayout()
            for i, st in enumerate(dicts["subject_types"]):
                cb = QCheckBox(st["display_name"])
                ag.addWidget(cb, i // 3, i % 3)
                self.applies[st["id"]] = cb
            self.applies_box.setLayout(ag)
            form.addWidget(self.applies_box)
        self.apply_btn = QPushButton("Apply changes")
        self.apply_btn.clicked.connect(self.apply)
        self.apply_btn.setEnabled(False)
        form.addWidget(self.apply_btn)
        form.addStretch(1)
        root.addLayout(form, 2)
        # Dirty tracking: Apply is enabled only when the form differs from
        # the stored entry (or when there is no entry to compare against).
        self.name_edit.textChanged.connect(self._update_apply_btn)
        self.text_edit.textChanged.connect(self._update_apply_btn)
        for w in self.extra_edits.values():
            w.textChanged.connect(self._update_apply_btn)
        for cb in self.bool_checks.values():
            cb.toggled.connect(self._update_apply_btn)
        if self.spec.get("applies_to"):
            for cb in self.applies.values():
                cb.toggled.connect(self._update_apply_btn)
        self.populate()

    def _entries(self):
        return self.dicts[self.key]

    def populate(self, select_id=None):
        self.listw.blockSignals(True)
        self.listw.clear()
        for e in self._entries():
            self.listw.addItem(e["display_name"])
            self.listw.item(self.listw.count() - 1).setData(Qt.UserRole, e["id"])
        self.listw.blockSignals(False)
        if select_id:
            for i in range(self.listw.count()):
                if self.listw.item(i).data(Qt.UserRole) == select_id:
                    self.listw.setCurrentRow(i)
                    return
        if self.listw.count():
            self.listw.setCurrentRow(0)
        else:
            self._clear_fields()

    def _current(self):
        item = self.listw.currentItem()
        if not item:
            return None
        eid = item.data(Qt.UserRole)
        return next((e for e in self._entries() if e["id"] == eid), None)

    def _form_dirty(self) -> bool:
        """True when the on-screen form differs from the stored entry."""
        e = self._current()
        if not e:
            return False
        if self.name_edit.text().strip() != e["display_name"]:
            return True
        if self.text_edit.toPlainText() != e.get(self.spec["text_field"], ""):
            return True
        for key, w in self.extra_edits.items():
            if w.text().strip() != e.get(key, ""):
                return True
        for key, cb in self.bool_checks.items():
            if cb.isChecked() != bool(e.get(key)):
                return True
        if self.spec.get("applies_to"):
            stored = set(e.get("applies_to", []))
            checked = {sid for sid, cb in self.applies.items() if cb.isChecked()}
            if checked != stored:
                return True
        return False

    def _update_apply_btn(self, *_):
        self.apply_btn.setEnabled(self._form_dirty())

    def on_select(self, *_):
        e = self._current()
        if not e:
            return self._clear_fields()
        self.name_edit.setText(e["display_name"])
        self.text_edit.setPlainText(e.get(self.spec["text_field"], ""))
        for key, w in self.extra_edits.items():
            w.setText(e.get(key, ""))
        for key, cb in self.bool_checks.items():
            cb.setChecked(bool(e.get(key)))
        if self.spec.get("applies_to"):
            for sid, cb in self.applies.items():
                cb.setChecked(sid in e.get("applies_to", []))
        self._update_apply_btn()

    def _clear_fields(self):
        self.name_edit.clear()
        self.text_edit.clear()
        for w in self.extra_edits.values():
            w.clear()
        for cb in self.bool_checks.values():
            cb.setChecked(False)
        if self.spec.get("applies_to"):
            for cb in self.applies.values():
                cb.setChecked(False)
        self._update_apply_btn()

    def add(self):
        entries = self._entries()
        n = 1
        while f"new-{n}" in {e["id"] for e in entries}:
            n += 1
        entry = {"id": f"new-{n}", "display_name": f"New {self.spec['label']} {n}"}
        if "applies_to" in self.spec:
            entry["applies_to"] = [s["id"] for s in self.dicts["subject_types"]]
        entry[self.spec["text_field"]] = ""
        for key, _ in self.spec.get("extra_text_fields", []):
            entry[key] = ""
        for key, _ in self.spec.get("bool_fields", []):
            entry[key] = False
        entries.append(entry)
        log.info("dictionary %s: added entry %s", self.key, entry["id"])
        self.populate(select_id=entry["id"])
        self.on_change(self)

    def delete(self):
        e = self._current()
        if not e:
            return
        if QMessageBox.question(
                self, "Delete entry",
                f"Delete '{e['display_name']}' from {self.spec['label']}?") \
                != QMessageBox.Yes:
            return
        self.dicts[self.key][:] = [x for x in self._entries() if x["id"] != e["id"]]
        log.info("dictionary %s: deleted entry %s", self.key, e["id"])
        self.populate()
        self.on_change(self)

    def apply(self):
        e = self._current()
        if not e:
            return
        e["display_name"] = self.name_edit.text().strip() or e["display_name"]
        e[self.spec["text_field"]] = self.text_edit.toPlainText()
        for key, w in self.extra_edits.items():
            e[key] = w.text().strip()
        for key, cb in self.bool_checks.items():
            e[key] = cb.isChecked()
        if self.spec.get("applies_to"):
            e["applies_to"] = [sid for sid, cb in self.applies.items() if cb.isChecked()]
        log.info("dictionary %s: updated entry %s", self.key, e["id"])
        self.populate(select_id=e["id"])
        self.on_change(self)
        self._update_apply_btn()


class TemplateTab(QWidget):
    """One template: description + options (D36/D37 fields)."""

    def __init__(self, template, dicts, settings, parent=None):
        super().__init__(parent)
        self.template = template
        self.dicts = dicts
        self.settings = settings
        self.worker = None

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        root.addLayout(left, 1)

        # Description
        left.addWidget(QLabel("Template description"))
        self.desc = QPlainTextEdit(template.get("description", ""))
        self.desc.setFixedHeight(80)
        self.desc.textChanged.connect(self.sync)
        left.addWidget(self.desc)

        # Options
        opts = QGridLayout()
        self.subject = QComboBox()
        for s in dicts["subject_types"]:
            self.subject.addItem(s["display_name"], s["id"])
        self.subject.setCurrentIndex(max(0, self.subject.findData(template["subject_type"])))
        self.subject.currentIndexChanged.connect(self.on_subject_change)
        opts.addWidget(QLabel("Subject type"), 0, 0); opts.addWidget(self.subject, 0, 1)

        self.side = QComboBox()
        for s in dicts["sides"]:
            self.side.addItem(s["display_name"], s["id"])
        self.side.setCurrentIndex(max(0, self.side.findData(template["side"])))
        opts.addWidget(QLabel("Side / nation"), 1, 0); opts.addWidget(self.side, 1, 1)

        self.sex = {}
        sx = QHBoxLayout()
        for s in ("male", "female"):
            cb = QCheckBox(s.capitalize())
            cb.setChecked(s in template["sex"])
            cb.stateChanged.connect(self.sync)
            sx.addWidget(cb)
            self.sex[s] = cb
        opts.addWidget(QLabel("Sex"), 2, 0); opts.addLayout(sx, 2, 1)

        self.age_low = QSpinBox(); self.age_low.setRange(20, 79); self.age_low.setValue(template["age_low"])
        self.age_high = QSpinBox(); self.age_high.setRange(21, 80); self.age_high.setValue(template["age_high"])
        ah = QHBoxLayout()
        ah.addWidget(self.age_low); ah.addWidget(QLabel("to")); ah.addWidget(self.age_high)
        opts.addWidget(QLabel("Age range"), 3, 0); opts.addLayout(ah, 3, 1)

        self.ethnicity = QGroupBox("Ethnicity (all = mixed)")
        eg = QGridLayout()
        self.eth_checks = {}
        for i, e in enumerate(dicts["ethnicities"]):
            cb = QCheckBox(e["display_name"])
            cb.setChecked(e["id"] in template["ethnicity"])
            cb.stateChanged.connect(self.sync)
            eg.addWidget(cb, i // 3, i % 3)
            self.eth_checks[e["id"]] = cb
        self.ethnicity.setLayout(eg)
        opts.addWidget(self.ethnicity, 4, 0, 1, 2)

        self.composition = QGroupBox("Compositions (multiselect)")
        cg = QGridLayout()
        self.comp_checks = {}
        for i, c in enumerate(dicts["compositions"]):
            cb = QCheckBox(c["display_name"])
            cb.setChecked(c["id"] in template["composition"])
            cb.stateChanged.connect(self.sync)
            cg.addWidget(cb, i // 2, i % 2)
            self.comp_checks[c["id"]] = cb
        self.composition.setLayout(cg)
        opts.addWidget(self.composition, 5, 0, 1, 2)

        self.uniforms = QGroupBox("Uniforms (multiselect)")
        ug = QGridLayout()
        self.uni_checks = {}
        for i, u in enumerate(dicts["uniforms"]):
            cb = QCheckBox(u["display_name"])
            cb.setChecked(u["id"] in template["uniforms"])
            cb.stateChanged.connect(self.sync)
            ug.addWidget(cb, i // 2, i % 2)
            self.uni_checks[u["id"]] = cb
        self.uniforms.setLayout(ug)
        opts.addWidget(self.uniforms, 6, 0, 1, 2)

        left.addLayout(opts)

        # Run controls (D39/D41)
        run_row = QHBoxLayout()
        self.count = QSpinBox()
        self.count.setRange(1, 100000)
        self.count.setValue(settings["count_default"])
        self.count.valueChanged.connect(self.check_count)
        self.run_btn = QPushButton("RUN")
        self.run_btn.clicked.connect(self.toggle_run)
        self.progress = QLabel("")
        run_row.addWidget(QLabel("Number of images"))
        run_row.addWidget(self.count)
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.progress)
        left.addLayout(run_row)
        self.check_count()
        left.addStretch(1)  # pin contents to top-left on resize (D50)

        # Preview pane: saved renders (D39 #4), checkbox multi-select delete (D48)
        pv = QVBoxLayout()
        self.preview = QListWidget()
        self.preview.setViewMode(QListWidget.IconMode)
        self.preview.setResizeMode(QListView.Adjust)
        self.preview.setSpacing(6)
        self.preview.setIconSize(QPixmap(128, 128).size())
        self.preview.setFixedWidth(300)
        pv.addWidget(self.preview, 1)
        sel_row = QHBoxLayout()
        sel_all = QPushButton("Select all")
        sel_all.clicked.connect(self.toggle_select_all)
        self.del_btn = QPushButton("Delete selected")
        self.del_btn.clicked.connect(self.delete_selected)
        sel_row.addWidget(sel_all)
        sel_row.addWidget(self.del_btn)
        pv.addLayout(sel_row)
        root.addLayout(pv, 1)  # preview column fills window height
        self.refresh_preview()

        self.on_subject_change()

    # --- sync helpers -------------------------------------------------
    def sync(self):
        t = self.template
        t["description"] = self.desc.toPlainText()
        t["subject_type"] = self.subject.currentData()
        t["side"] = self.side.currentData()
        t["sex"] = [s for s, cb in self.sex.items() if cb.isChecked()] or ["male"]
        t["age_low"] = min(self.age_low.value(), self.age_high.value() - 1)
        t["age_high"] = max(self.age_high.value(), self.age_low.value() + 1)
        t["ethnicity"] = [e for e, cb in self.eth_checks.items() if cb.isChecked()] or ["white"]
        t["composition"] = [c for c, cb in self.comp_checks.items() if cb.isChecked()] \
            or list(self.comp_checks)[:1]
        t["uniforms"] = [u for u, cb in self.uni_checks.items() if cb.isChecked()]

    def on_subject_change(self):
        """Strict uniform gating (D43 resolution): only fitting uniforms shown."""
        self.sync()
        subject = self.template["subject_type"]
        unis = _by_id(self.dicts["uniforms"])
        for uid, cb in self.uni_checks.items():
            cb.setVisible(subject in unis[uid]["applies_to"])
            if not cb.isVisible():
                cb.setChecked(False)
        if not any(cb.isChecked() for cb in self.uni_checks.values() if cb.isVisible()):
            first = next((uid for uid, u in unis.items()
                          if subject in u["applies_to"]), None)
            if first is None and unis:
                # New subject types may have no fitting uniform yet — fall
                # back to the first entry rather than leaving none selected.
                first = next(iter(unis))
            if first:
                self.uni_checks[first].setChecked(True)

    def check_count(self):
        if self.count.value() > self.settings["threshold"]:
            self.progress.setText(
                f"⚠ above warning threshold ({self.settings['threshold']})")
        else:
            self.progress.setText("")

    def toggle_run(self):
        if self.worker is not None:
            self.worker.abort()
            return
        self.sync()
        self.settings["count"] = self.count.value()
        self.run_btn.setText("ABORT")
        self.count.setEnabled(False)
        self.worker = RenderWorker(self.template, self.dicts, self.settings)
        self.worker.progress.connect(self.on_progress)
        self.worker.image_done.connect(lambda d: self.refresh_preview())
        self.worker.finished_batch.connect(self.on_done)
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def on_progress(self, done, total):
        self.progress.setText(f"{done} / {total}")

    def on_done(self, msg):
        self._finish(msg)

    def on_fail(self, msg):
        self._finish(msg)
        QMessageBox.warning(self, "Batch failed", msg)

    def _finish(self, msg):
        if self.worker is not None:
            self.worker.wait()
            self.worker = None
        self.run_btn.setText("RUN")
        self.count.setEnabled(True)
        self.progress.setText(msg)

    def refresh_preview(self):
        self.preview.clear()
        outdir = os.path.join(RENDER_DIR, self.template["id"])
        if not os.path.isdir(outdir):
            self.preview.addItem("(no saved renders yet)")
            return
        files = [name for name in sorted(os.listdir(outdir))
                 if name.lower().endswith((".png", ".jpg", ".jpeg"))]
        if not files:
            self.preview.addItem("(no saved renders yet)")
            return
        for name in files:
            item = QListWidgetItem(name)
            icon = QPixmap(os.path.join(outdir, name))
            if not icon.isNull():
                item.setIcon(icon)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.preview.addItem(item)

    def toggle_select_all(self):
        """Check every photo, or clear all if all are already checked."""
        items = [self.preview.item(i) for i in range(self.preview.count())]
        photos = [it for it in items if it.flags() & Qt.ItemIsUserCheckable]
        target = Qt.Unchecked if photos and all(
            it.checkState() == Qt.Checked for it in photos) else Qt.Checked
        for it in photos:
            it.setCheckState(target)

    def delete_selected(self):
        """Delete the checked render(s); manifest rows kept but marked (D48)."""
        names = [it.text() for it in self.preview.findItems("", Qt.MatchContains)
                 if it.checkState() == Qt.Checked]
        if not names:
            return
        if QMessageBox.question(
                self, "Delete photos",
                f"Delete {len(names)} photo(s)?") != QMessageBox.Yes:
            return
        outdir = os.path.join(RENDER_DIR, self.template["id"])
        for name in names:
            path = os.path.join(outdir, name)
            if os.path.isfile(path):
                os.remove(path)
                core.mark_deleted(outdir, name)
                log.info("deleted render %s (manifest row marked)", path)
        self.refresh_preview()


def _by_id(items):
    return {i["id"]: i for i in items}


class DictsDialog(QDialog):
    """Modeless dialog hosting the dictionary editor sub-tabs (moved out of
    the main tab widget). Guards against closing with unapplied edits."""

    def __init__(self, main):
        super().__init__(main, Qt.Window)
        self.main = main
        self.setWindowTitle("Dictionaries")
        lay = QVBoxLayout(self)
        lay.addWidget(main.dict_tabs)
        self.resize(820, 560)

    def reject(self):
        ed = self.main.dict_tabs.currentWidget()
        if isinstance(ed, DictEditor) and ed._form_dirty():
            if not self.main._warn_unapplied(ed):
                return  # Cancel: keep the dialog open
        super().reject()


class MainWindow(QMainWindow):
    """Main window (D39 + D46/D47/D48): project file, template tab,
    dictionary editor tabs, preview with delete, RUN/ABORT."""

    def __init__(self, project: dict, settings: dict):
        super().__init__()
        self.setWindowTitle("AvatarGen — Simple Empire Character Generator")
        self.project = project
        self.settings = settings
        self.project_path = PROJECT_PATH

        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        for label, slot in (
                ("New project", self.new_project),
                ("Open project…", self.open_project),
                ("Save project", self.save_project),
                ("Save project as…", self.save_project_as)):
            act = QAction(label, self)
            act.triggered.connect(slot)
            file_menu.addAction(act)
        file_menu.addSeparator()
        act_new_tpl = QAction("New template", self)
        act_new_tpl.triggered.connect(self.new_template)
        file_menu.addAction(act_new_tpl)
        act_rename_tpl = QAction("Rename template…", self)
        act_rename_tpl.triggered.connect(self.rename_template)
        file_menu.addAction(act_rename_tpl)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)
        opt_menu = menu.addMenu("&Options")
        act_settings = QAction("&Settings…", self)
        act_settings.triggered.connect(self.open_settings)
        opt_menu.addAction(act_settings)
        act_prompts = QAction("&Prompts…", self)
        act_prompts.triggered.connect(self.open_prompts)
        opt_menu.addAction(act_prompts)
        act_dicts = QAction("&Dictionaries…", self)
        act_dicts.triggered.connect(self.open_dicts)
        opt_menu.addAction(act_dicts)
        help_menu = menu.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

        self.tabs = QTabWidget()
        self.tab = TemplateTab(self._current_template(), self.dicts, self.settings)
        self.tabs.addTab(self.tab, self.tab.template.get("title", "Template"))
        self.dict_tabs = QTabWidget()
        for key, spec in DICT_SPECS.items():
            self.dict_tabs.addTab(DictEditor(key, self.dicts, self.on_dicts_changed),
                                  spec["label"])
        add_btn = QPushButton("+")
        add_btn.setToolTip("Add template")
        add_btn.setFixedSize(26, 22)
        add_btn.clicked.connect(self.new_template)
        self.tabs.setCornerWidget(add_btn, Qt.TopRightCorner)
        self.setCentralWidget(self.tabs)
        self._update_title()
        # Navigation guard: warn when switching dictionary editors with
        # unapplied changes.
        self._tab_guard = False
        self._cur_inner = self.dict_tabs.currentWidget()
        self.dict_tabs.currentChanged.connect(self.on_dict_tab_changed)

    # --- properties / helpers -----------------------------------------
    @property
    def dicts(self):
        return self.project["dictionaries"]

    def _current_template(self):
        if self.project["templates"]:
            return self.project["templates"][0]
        tpl = default_template(self.dicts)
        self.project["templates"].append(tpl)
        return tpl

    _dirty = False

    def _update_title(self):
        name = os.path.basename(self.project_path)
        star = " *" if self._dirty else ""
        self.setWindowTitle(
            f"AvatarGen — Simple Empire Character Generator ({name}{star})")

    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    # --- unapplied-changes navigation guard -----------------------------
    def _warn_unapplied(self, editor) -> bool:
        """Ask what to do with unapplied edits; True = safe to navigate."""
        r = QMessageBox.question(
            self, "Unapplied changes",
            f"The {editor.spec['label']} editor has unapplied changes.",
            QMessageBox.Apply | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Apply:
            editor.apply()
            return True
        if r == QMessageBox.Discard:
            editor.on_select()  # reload fields from the stored entry
            return True
        return False

    def on_dict_tab_changed(self, idx, *_):
        if self._tab_guard:
            return
        old = self._cur_inner
        self._cur_inner = self.dict_tabs.widget(idx)
        if isinstance(old, DictEditor) and old is not self._cur_inner:
            if old._form_dirty():
                if not self._warn_unapplied(old):
                    self._tab_guard = True
                    self.dict_tabs.setCurrentWidget(old)
                    self._tab_guard = False
                    self._cur_inner = old

    def sync_current_template(self):
        self.tab.sync()

    def _sanitize_template(self, t: dict):
        """Fix dangling dictionary references after edits/deletes (D47)."""
        d = self.dicts
        subject_ids = [s["id"] for s in d["subject_types"]]
        side_ids = [s["id"] for s in d["sides"]]
        comp_ids = [c["id"] for c in d["compositions"]]
        eth_ids = [e["id"] for e in d["ethnicities"]]
        unis = {u["id"]: u for u in d["uniforms"]}
        if t.get("subject_type") not in subject_ids and subject_ids:
            t["subject_type"] = subject_ids[0]
        if t.get("side") not in side_ids and side_ids:
            t["side"] = side_ids[0]
        comp = t.get("composition")
        if isinstance(comp, str):  # legacy single-select
            comp = [comp]
        t["composition"] = [c for c in comp if c in comp_ids] or comp_ids[:1]
        t["ethnicity"] = [e for e in t.get("ethnicity", []) if e in eth_ids] \
            or eth_ids[:1]
        t["uniforms"] = [u for u in t.get("uniforms", []) if u in unis]
        if not t["uniforms"]:
            fitting = [uid for uid, u in unis.items()
                       if t.get("subject_type") in u.get("applies_to", [])]
            t["uniforms"] = (fitting or list(unis))[:1]

    def on_dicts_changed(self, source_editor=None):
        """Dictionary edits (D47). Sanitize templates and rebuild the template
        tab. The editing editor is NOT rebuilt, so the user stays in it. Other
        dictionary editors are rebuilt only when subject types changed (their
        applies_to checkbox lists depend on it)."""
        log.info("dictionaries changed (%s); rebuilding",
                 source_editor.key if source_editor else "external")
        self.tab.sync()
        for t in self.project["templates"]:
            self._sanitize_template(t)
        self._sanitize_template(self.tab.template)
        old = self.tab.template
        self.tab.deleteLater()
        self.tab = TemplateTab(old, self.dicts, self.settings)
        idx = self.tabs.indexOf(self.tab)
        self.tabs.removeTab(max(idx, 0))
        self.tabs.insertTab(max(idx, 0), self.tab, old.get("title", "Template"))
        self.tabs.setCurrentIndex(max(idx, 0))
        if source_editor is None or source_editor.key == "subject_types":
            while self.dict_tabs.count():
                self.dict_tabs.removeTab(0)
            for key, spec in DICT_SPECS.items():
                if source_editor is not None and key == source_editor.key:
                    w = source_editor  # keep the editor the user is working in
                else:
                    w = DictEditor(key, self.dicts, self.on_dicts_changed)
                self.dict_tabs.addTab(w, spec["label"])
            self._cur_inner = self.dict_tabs.currentWidget()
        self._mark_dirty()

    # --- project file operations (D46) ---------------------------------
    def new_project(self):
        if QMessageBox.question(
                self, "New project",
                "Discard current project and start fresh?") != QMessageBox.Yes:
            return
        dicts = core.load_dictionary(DEFAULT_DICTS)
        self.project = core.default_project(dicts)
        self.project["templates"].append(default_template(dicts))
        self.project_path = PROJECT_PATH
        self._rebuild_all()
        self._mark_dirty()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", os.path.dirname(self.project_path),
            "AvatarGen project (*.json)")
        if not path:
            return
        try:
            project = core.load_project(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Open failed", str(e))
            return
        self.project = project
        self.project_path = path
        self._rebuild_all()
        self._dirty = False
        self._update_title()

    def save_project(self):
        self.save_project_to(self.project_path)

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project as", self.project_path,
            "AvatarGen project (*.json)")
        if not path:
            return
        self.project_path = path
        self.save_project_to(path)

    def save_project_to(self, path: str):
        self.sync_current_template()
        tpl = self.tab.template
        if not tpl.get("id"):
            tpl["id"] = core.slugify(tpl.get("title", "template"))
        self.project["templates"] = [
            t for t in self.project["templates"] if t.get("id") != tpl["id"]]
        self.project["templates"].insert(0, tpl)
        core.save_project(path, self.project)
        self.project_path = path
        self._dirty = False
        self._update_title()
        self.tabs.setTabText(self.tabs.indexOf(self.tab),
                             tpl.get("title", "Template"))
        log.info("project saved: %d templates, %d sides -> %s",
                 len(self.project["templates"]), len(self.dicts["sides"]), path)

    def new_template(self):
        self.sync_current_template()
        dicts = self.dicts
        tpl = {
            "schema_version": 1,
            "id": "",
            "title": "New template",
            "description": "",
            "subject_type": dicts["subject_types"][0]["id"],
            "side": dicts["sides"][0]["id"],
            "sex": ["male", "female"],
            "age_low": 30, "age_high": 60,
            "ethnicity": [e["id"] for e in dicts["ethnicities"]],
            "composition": [dicts["compositions"][0]["id"]],
            "uniforms": [u["id"] for u in dicts["uniforms"][:1]],
            "style_core_injection": "",
            "negative_injection": "",
        }
        self.project["templates"].append(tpl)
        self.tab = TemplateTab(tpl, dicts, self.settings)
        self.tabs.addTab(self.tab, tpl["title"])
        self.tabs.setCurrentWidget(self.tab)
        self._mark_dirty()

    def _rebuild_all(self):
        self.tab = TemplateTab(self._current_template(), self.dicts, self.settings)
        self.tabs.clear()  # drop all template tabs; self.tab is re-added first
        self.tabs.addTab(self.tab, self.tab.template.get("title", "Template"))
        while self.dict_tabs.count():
            self.dict_tabs.removeTab(0)
        for key, spec in DICT_SPECS.items():
            self.dict_tabs.addTab(DictEditor(key, self.dicts, self.on_dicts_changed),
                                  spec["label"])
        self._cur_inner = self.dict_tabs.currentWidget()
        self.tabs.setCurrentIndex(0)

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            save_settings(self.settings)
            setup_logging(self.settings.get("logging", False))
            log.info("settings updated: endpoint=%s checkpoint=%s seed=%d threshold=%d logging=%s",
                     self.settings["endpoint"], self.settings["checkpoint"],
                     self.settings["seed"], self.settings["threshold"],
                     self.settings.get("logging", False))
            self.tab.settings = self.settings
            self.tab.check_count()
            QMessageBox.information(
                self, "Settings",
                f"Endpoint: {self.settings['endpoint']}\n"
                f"Checkpoint: {self.settings['checkpoint']}\n"
                f"Seed: {self.settings['seed']}")

    def open_prompts(self):
        PromptsDialog(self.settings, self).exec()

    def open_dicts(self):
        DictsDialog(self).show()

    def show_about(self):
        QMessageBox.about(
            self, "About AvatarGen",
            f"<b>AvatarGen</b> — Simple Empire Character Generator<br>"
            f"Version {__version__} (prototype)<br><br>"
            f"License: MIT (see LICENSE)<br>"
            f"Author: {AUTHORS}<br>"
            f'Repository: <a href="{REPO_URL}">{REPO_URL}</a>')

    def rename_template(self):
        tpl = self.tab.template
        name, ok = QInputDialog.getText(
            self, "Rename template", "Template name:",
            text=tpl.get("title", "Template"))
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Rename template",
                                "Template name cannot be empty.")
            return
        tpl["title"] = name
        self.tabs.setTabText(self.tabs.indexOf(self.tab), name)
        self._mark_dirty()
        log.info("template renamed to %r", name)

    def closeEvent(self, event):
        """Prompt before exiting with an unsaved project."""
        if self._dirty:
            r = QMessageBox.question(
                self, "Unsaved project",
                "The project has unsaved changes. Save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Save:
                self.save_project()
                event.accept()
            elif r == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


DEFAULT_SETTINGS = {
    "seed": 1234,
    "logging": False,
    "endpoint": "http://127.0.0.1:8188",
    "checkpoint": "flux1-schnell-fp8.safetensors",
    "threshold": 100,
    "count_default": 10,
    "output_dir": RENDER_DIR,
    "width": 1024, "height": 1024, "quality": 85,
    "timeout": 600, "retries": 2,
}


def default_template(dicts):
    return {
        "schema_version": 1,
        "id": "veldmark-army-brass",
        "title": "Veldmark Army — Brass",
        "description": "Formal portraits of Veldmark senior officers.",
        "subject_type": "army_officer",
        "side": "veldmark",
        "sex": ["male", "female"],
        "age_low": 30, "age_high": 60,
        "ethnicity": [e["id"] for e in dicts["ethnicities"]],
        "composition": ["formal_portrait"],
        "uniforms": ["service_dress", "field_uniform"],
        "style_core_injection": "",
        "negative_injection": "",
    }


def load_settings() -> dict:
    """Merge DEFAULT_SETTINGS with the user's persisted settings.json."""
    s = dict(DEFAULT_SETTINGS)
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                s.update(json.load(f))
            log.info("settings loaded: %s", SETTINGS_PATH)
        except Exception as e:  # noqa: BLE001 — corrupt file: use defaults
            log.warning("settings load failed (%s); using defaults", e)
    return s


def save_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    log.info("settings saved: %s", SETTINGS_PATH)


def load_or_create_project() -> dict:
    """D46: single project file; created from repo defaults on first run."""
    if os.path.isfile(PROJECT_PATH):
        try:
            project = core.load_project(PROJECT_PATH)
            project = core.migrate_project(project)
            log.info("project loaded: %s (%d templates)", PROJECT_PATH,
                     len(project["templates"]))
            return project
        except Exception as e:  # noqa: BLE001 — corrupt file: keep it, start fresh
            log.error("project load failed (%s); starting from defaults", e)
    dicts = core.load_dictionary(DEFAULT_DICTS)
    project = core.default_project(dicts)
    project["templates"].append(default_template(dicts))
    core.save_project(PROJECT_PATH, project)
    log.info("created default project: %s", PROJECT_PATH)
    return project


def main():
    log.info("app start")
    app = QApplication([])
    settings = load_settings()
    setup_logging(settings.get("logging", False))
    project = load_or_create_project()
    log.info("loaded %d sides / %d uniforms / %d compositions",
             len(project["dictionaries"]["sides"]),
             len(project["dictionaries"]["uniforms"]),
             len(project["dictionaries"]["compositions"]))
    win = MainWindow(project, settings)
    win.resize(1000, 700)
    win.show()
    raise SystemExit(app.exec())
