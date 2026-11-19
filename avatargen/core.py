"""AvatarGen core: dictionaries, templates, prompt assembly.

Spec ref: D33/D37 (generic insignia, no rank words), D36 (template fields),
D38 (no reproducibility contract), D43/D44 (dictionaries + template format).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .logging_util import get_logger

log = get_logger("core")

STYLE_CORE = (
    "1940s black and white portrait photograph, "
    "large format film look, silver gelatin print, vintage film grain, "
    "slight dust and scratches, shallow depth of field"
)

NEGATIVE = (
    "color, sepia, illustration, digital art, cartoon, anime, modern, smooth skin, "
    "watermark, text, lettering, flag symbols, emblems, coat of arms, crests, "
    "swastika, nazi symbols, low quality"
)

# Generic-but-consistent insignia (D33/D37 #2): no rank, no nation motifs.
INSIGNIA_OFFICER = (
    "generic metal cap badge, plain collar tabs, officer rank insignia"
)
INSIGNIA_CIVILIAN = "plain lapels"

SEX_PROMPT = {"male": "male", "female": "female"}


def load_dictionary(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _by_id(items: list[dict]) -> dict:
    return {i["id"]: i for i in items}


def build_prompt(template: dict, dicts: dict, rng: random.Random) -> tuple[str, dict]:
    """Assemble one image prompt from a template. Returns (prompt, draw)."""
    subjects = _by_id(dicts["subject_types"])
    sides = _by_id(dicts["sides"])
    unis = _by_id(dicts["uniforms"])
    comps = _by_id(dicts["compositions"])
    ethn = _by_id(dicts["ethnicities"])

    subject = subjects[template["subject_type"]]
    side = sides[template["side"]]
    comp = comps[template["composition"]]

    sex = rng.choice(template["sex"])
    uniform_id = rng.choice(template["uniforms"])
    uniform = unis[uniform_id]
    if subject["id"] not in uniform["applies_to"]:
        raise ValueError(f"uniform {uniform_id} does not apply to {subject['id']}")
    eth = rng.choice(template["ethnicity"])
    age = rng.randint(template["age_low"], template["age_high"])

    sex_word = {"politician": "statesman", "industrialist": "businessman",
                "scientist": "scientist", "army_officer": "officer",
                "air_force_officer": "officer", "naval_officer": "officer"}[subject["id"]]
    if sex == "female":
        sex_word = {"politician": "stateswoman", "industrialist": "businesswoman",
                    "scientist": "scientist", "army_officer": "officer",
                    "air_force_officer": "officer", "naval_officer": "officer"}[subject["id"]]

    insignia = INSIGNIA_OFFICER if subject["military"] else INSIGNIA_CIVILIAN

    parts = [STYLE_CORE]
    if template.get("style_core_injection"):
        parts.append(template["style_core_injection"])
    if subject["military"]:
        parts.append(subject["display_name"].lower())
    parts.append(
        f"{ethn[eth]['prompt']} {age}-year-old {sex_word} from {side['display_name']}, "
        f"{side['flavor']}, {uniform['prompt_text']}, {insignia}, "
        f"{comp['prompt_text']}"
    )
    if template.get("negative_injection"):
        negative = NEGATIVE + ", " + template["negative_injection"]
    else:
        negative = NEGATIVE

    draw = {
        "template_id": template["id"],
        "subject_type": subject["id"], "side": side["id"],
        "sex": sex, "age": age, "ethnicity": eth,
        "uniform": uniform_id, "composition": comp["id"],
        "seed": rng.randrange(0, 2**31),
    }
    log.debug("draw: %s", json.dumps(draw))
    return ", ".join(parts), negative, draw


def workflow(prompt: str, negative: str, seed: int, ckpt: str,
             prefix: str, width: int, height: int) -> dict:
    """ComfyUI API-format workflow (flux1-schnell defaults)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "_meta": {"title": "Load Checkpoint"},
              "inputs": {"ckpt_name": ckpt}},
        "3": {"class_type": "CLIPTextEncode", "_meta": {"title": "Prompt"},
              "inputs": {"clip": ["1", 1], "text": prompt}},
        "4": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative"},
              "inputs": {"clip": ["1", 1], "text": negative}},
        "5": {"class_type": "EmptyLatentImage", "_meta": {"title": "Latent"},
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "2": {"class_type": "KSampler", "_meta": {"title": "KSampler"},
              "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0], "seed": seed, "steps": 4, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "_meta": {"title": "VAE Decode"},
              "inputs": {"samples": ["2", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "_meta": {"title": "Save"},
              "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


class ComfyClient:
    def __init__(self, endpoint: str, ckpt: str):
        self.endpoint = endpoint.rstrip("/")
        self.ckpt = ckpt

    def test_connection(self) -> str:
        try:
            with urllib.request.urlopen(f"{self.endpoint}/system_stats", timeout=5) as r:
                data = json.loads(r.read())
        except Exception as e:
            log.warning("connection test failed for %s: %s", self.endpoint, e)
            raise
        version = f"ComfyUI {data.get('system', {}).get('comfyui_version', 'unknown')}"
        log.info("connection test OK: %s at %s", version, self.endpoint)
        return version

    def list_checkpoints(self) -> list[str]:
        with urllib.request.urlopen(
                f"{self.endpoint}/object_info/CheckpointLoaderSimple", timeout=10) as r:
            info = json.loads(r.read())
        raw = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        # Entries are plain names (strings) in current ComfyUI; tolerate dicts.
        names = [c["name"] if isinstance(c, dict) else c for c in raw]
        log.info("fetched %d checkpoints from %s", len(names), self.endpoint)
        return names

    def queue_and_wait(self, wf: dict, timeout: int = 600) -> list[dict]:
        """Queue a workflow, wait for completion, return saved output images
        (list of {filename, subfolder, type}) so the app can fetch them."""
        log.debug("queuing workflow: prefix=%s ckpt=%s seed=%s",
                  wf["8"]["inputs"]["filename_prefix"], wf["1"]["inputs"]["ckpt_name"],
                  wf["2"]["inputs"]["seed"])
        log.info("prompt: %s", wf["3"]["inputs"]["text"])
        # Validate the checkpoint exists before queueing — /prompt 400s on a
        # bad ckpt_name and this gives a far clearer message (D42 model list).
        ckpt = wf["1"]["inputs"]["ckpt_name"]
        try:
            installed = self.list_checkpoints()
        except Exception as e:  # noqa: BLE001 — ComfyUI may be mid-reload
            log.warning("could not list checkpoints to validate %r: %s", ckpt, e)
            installed = None
        if installed is not None and ckpt not in installed:
            raise RuntimeError(
                f"Checkpoint {ckpt!r} not found on ComfyUI. Installed: {installed}")
        req = urllib.request.Request(
            f"{self.endpoint}/prompt",
            data=json.dumps({"prompt": wf}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                pid = json.loads(r.read())["prompt_id"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            log.error("queue request failed for %s: HTTP %s — body: %s",
                      wf["8"]["inputs"]["filename_prefix"], e.code, body)
            raise RuntimeError(f"ComfyUI rejected the workflow (HTTP {e.code}): {body}") from e
        except Exception as e:
            log.error("queue request failed for %s: %s",
                      wf["8"]["inputs"]["filename_prefix"], e)
            raise
        log.info("queued %s as %s", wf["8"]["inputs"]["filename_prefix"], pid)
        t0 = time.time()
        last_status = ""
        while time.time() - t0 < timeout:
            # every 30s log queue state (running/pending) so stalls are visible
            if (time.time() - t0) % 30 < 1.5:
                try:
                    with urllib.request.urlopen(f"{self.endpoint}/queue", timeout=10) as r:
                        q = json.loads(r.read())
                    running = any(e[1] == pid for e in q.get("queue_running", []))
                    pending = any(e[1] == pid for e in q.get("queue_pending", []))
                    state = "running" if running else ("pending" if pending else "NOT IN QUEUE")
                    if state != last_status:
                        log.info("%s state: %s (%.0fs elapsed)", pid, state, time.time() - t0)
                        last_status = state
                except Exception as e:  # noqa: BLE001 — queue probe is best-effort
                    log.debug("queue probe failed: %s", e)
            with urllib.request.urlopen(f"{self.endpoint}/history/{pid}", timeout=30) as r:
                hist = json.loads(r.read())
            if pid in hist and hist[pid].get("status", {}).get("completed"):
                status = hist[pid]["status"]
                if status.get("status_str") == "error":
                    log.error("ComfyUI reported error for %s: %s", pid,
                              json.dumps(status.get("messages", []))[:400])
                    raise RuntimeError(f"ComfyUI error for {pid}")
                # Collect images from ANY output node — do not assume the
                # SaveImage node kept id "8" (ComfyUI may renumber; found in
                # integration testing where outputs was {} under key "8").
                outputs = []
                for node_out in (hist[pid].get("outputs") or {}).values():
                    outputs.extend(node_out.get("images", []))
                if not outputs:
                    # Race guard: some ComfyUI builds record completion before
                    # the outputs dict is populated — wait 2s and re-fetch once.
                    time.sleep(2.0)
                    with urllib.request.urlopen(f"{self.endpoint}/history/{pid}",
                                                timeout=30) as r:
                        hist = json.loads(r.read())
                    for node_out in (hist.get(pid, {}).get("outputs") or {}).values():
                        outputs.extend(node_out.get("images", []))
                if not outputs:
                    # Never treat this as success silently. Dump status and
                    # outputs ONLY — the prompt echo floods the truncation
                    # budget (seen in integration testing, 13:59:58).
                    detail = json.dumps({
                        "status": hist.get(pid, {}).get("status", {}),
                        "outputs": hist.get(pid, {}).get("outputs", {}),
                        "elapsed_s": round(time.time() - t0, 2),
                    })
                    log.error("prompt %s completed with no images in %.1fs — %s",
                              pid, time.time() - t0, detail)
                    raise RuntimeError(
                        f"ComfyUI returned no image for {pid} "
                        f"(elapsed {time.time() - t0:.1f}s; {detail[:500]})")
                log.info("finished %s in %.1fs, %d image(s)", pid,
                         time.time() - t0, len(outputs))
                return outputs
            time.sleep(1.0)
        log.error("timeout waiting for %s after %ss", pid, timeout)
        raise TimeoutError(f"Image {pid} timed out")

    def fetch_image(self, out: dict, dest_path: str) -> None:
        """Download a generated image from ComfyUI (/view) into the app's
        render dir — ComfyUI saves into its own output folder, which the
        preview pane cannot read (discovered in first integration test)."""
        q = urllib.parse.urlencode({
            "filename": out["filename"], "subfolder": out.get("subfolder", ""),
            "type": out.get("type", "output")})
        url = f"{self.endpoint}/view?{q}"
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(dest_path, "wb") as f:
            f.write(data)
        log.info("fetched %s -> %s (%d bytes)", out["filename"], dest_path, len(data))


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "template"


def template_dir(base: str) -> str:
    return os.path.join(base, "templates")


def save_template(base: str, tpl: dict) -> str:
    os.makedirs(template_dir(base), exist_ok=True)
    path = os.path.join(template_dir(base), f"{tpl['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tpl, f, indent=2)
    return path


def load_template(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_templates(base: str) -> list[str]:
    d = template_dir(base)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json"))


# --- project file (D46): one file holds dictionaries + all templates --------
PROJECT_VERSION = 2

def default_project(dicts: dict) -> dict:
    return {
        "schema_version": PROJECT_VERSION,
        "dictionaries": dicts,
        "templates": [],
    }


def save_project(path: str, project: dict) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2)
    return path


def load_project(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        project = json.load(f)
    if project.get("schema_version") != PROJECT_VERSION:
        raise ValueError(f"Unsupported project schema_version "
                         f"{project.get('schema_version')!r} in {path}")
    for key in ("dictionaries", "templates"):
        if key not in project:
            raise ValueError(f"Project file {path} missing '{key}'")
    return project


def mark_deleted(outdir: str, filename: str) -> None:
    """Mark the manifest row(s) for a deleted render (D48: keep history)."""
    manifest = os.path.join(outdir, "manifest.jsonl")
    if not os.path.isfile(manifest):
        return
    seed_token = filename.rsplit("_", 1)[-1].split(".")[0]  # '<seed:010d>'
    rows = []
    with open(manifest, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("seed")) == seed_token.lstrip("0") or \
                    str(row.get("seed")).zfill(10) == seed_token:
                row["deleted"] = True
            rows.append(row)
    with open(manifest, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
