"""AvatarGen GUI (PySide6) — prototype per D36-D45."""
from __future__ import annotations

import json
import os
import random

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from . import core
from .logging_util import get_logger, setup_logging

log = get_logger("gui")

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DICTS = os.path.join(APP_DIR, "dictionaries.json")
DEFAULT_USER_DIR = os.path.join(APP_DIR, "userdata")
RENDER_DIR = os.path.join(DEFAULT_USER_DIR, "renders")


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
        log.info("batch start: template=%s count=%d seed=%d endpoint=%s",
                 self.template["id"], n, self.settings["seed"], self.settings["endpoint"])
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
                    self.template, self.dicts, rng)
                prefix = f"{draw['template_id']}_{i:04d}_{draw['seed']:010d}"
                wf = core.workflow(prompt, negative, draw["seed"],
                                   self.settings["checkpoint"], prefix,
                                   self.settings["width"], self.settings["height"])
                outputs = client.queue_and_wait(wf)
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
        })
        super().accept()


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

        self.composition = QComboBox()
        for c in dicts["compositions"]:
            self.composition.addItem(c["display_name"], c["id"])
        self.composition.setCurrentIndex(max(0, self.composition.findData(template["composition"])))
        opts.addWidget(QLabel("Composition"), 5, 0); opts.addWidget(self.composition, 5, 1)

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

        # Preview pane: saved renders for this template (D39 #4)
        self.preview = QListWidget()
        self.preview.setViewMode(QListWidget.IconMode)
        self.preview.setIconSize(QPixmap(96, 96).size())
        self.preview.setFixedWidth(260)
        root.addWidget(self.preview)
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
        t["composition"] = self.composition.currentData()
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
            return
        for name in sorted(os.listdir(outdir)):
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                self.preview.addItem(name)
                icon = QPixmap(os.path.join(outdir, name))
                if not icon.isNull():
                    self.preview.item(self.preview.count() - 1).setIcon(icon)


def _by_id(items):
    return {i["id"]: i for i in items}


class MainWindow(QMainWindow):
    """Main window (D39): menu bar, template tabs, preview, RUN/ABORT."""

    def __init__(self, dicts, settings, template):
        super().__init__()
        self.setWindowTitle("AvatarGen — Simple Empire Character Generator")
        self.dicts = dicts
        self.settings = settings

        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        act_save = QAction("Save template", self)
        act_save.triggered.connect(self.save_template)
        act_load = QAction("Open template…", self)
        act_load.triggered.connect(self.open_template)
        act_new = QAction("New template", self)
        act_new.triggered.connect(self.new_template)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        for a in (act_save, act_load, act_new):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)
        opt_menu = menu.addMenu("&Options")
        act_settings = QAction("&Settings…", self)
        act_settings.triggered.connect(self.open_settings)
        opt_menu.addAction(act_settings)

        self.tabs = QTabWidget()
        self.tab = TemplateTab(template, dicts, settings)
        self.tabs.addTab(self.tab, template.get("title", "Template"))
        self.setCentralWidget(self.tabs)

    def current_template(self):
        return self.tab.template

    def save_template(self):
        self.tab.sync()
        tpl = self.tab.template
        if not tpl.get("id"):
            tpl["id"] = core.slugify(tpl.get("title", "template"))
        path = core.save_template(DEFAULT_USER_DIR, tpl)
        log.info("template saved: %s (%s) -> %s", tpl["id"], tpl.get("title"), path)
        self.tabs.setTabText(0, tpl.get("title", "Template"))
        QMessageBox.information(self, "Saved", f"Template saved:\n{path}")

    def open_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open template", core.template_dir(DEFAULT_USER_DIR), "JSON (*.json)")
        if not path:
            return
        tpl = core.load_template(path)
        self.tab = TemplateTab(tpl, self.dicts, self.settings)
        self.tabs.removeTab(0)
        self.tabs.addTab(self.tab, tpl.get("title", "Template"))

    def new_template(self):
        tpl = {
            "schema_version": 1,
            "id": "",
            "title": "New template",
            "description": "",
            "subject_type": "army_officer",
            "side": self.dicts["sides"][0]["id"],
            "sex": ["male", "female"],
            "age_low": 30, "age_high": 60,
            "ethnicity": [e["id"] for e in self.dicts["ethnicities"]],
            "composition": "formal_portrait",
            "uniforms": ["service_dress"],
            "style_core_injection": "",
            "negative_injection": "",
        }
        self.tab = TemplateTab(tpl, self.dicts, self.settings)
        self.tabs.removeTab(0)
        self.tabs.addTab(self.tab, "New template")

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
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


DEFAULT_SETTINGS = {
    "seed": 1234,
    "logging": False,
    "endpoint": "http://127.0.0.1:8188",
    "checkpoint": "flux1-schnell-fp8.safetensors",
    "threshold": 100,
    "count_default": 10,
    "output_dir": RENDER_DIR,
    "width": 1024, "height": 1024, "quality": 85,
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
        "composition": "formal_portrait",
        "uniforms": ["service_dress", "field_uniform"],
        "style_core_injection": "",
        "negative_injection": "",
    }


def main():
    setup_logging(DEFAULT_SETTINGS.get("logging", False))
    log.info("app start")
    app = QApplication([])
    dicts = core.load_dictionary(DEFAULT_DICTS)
    log.info("loaded %d sides / %d uniforms / %d compositions from %s",
             len(dicts["sides"]), len(dicts["uniforms"]),
             len(dicts["compositions"]), DEFAULT_DICTS)
    win = MainWindow(dicts, DEFAULT_SETTINGS, default_template(dicts))
    win.resize(1000, 700)
    win.show()
    raise SystemExit(app.exec())
