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
        names = [c["name"] for c in
                 info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]]
        log.info("fetched %d checkpoints from %s", len(names), self.endpoint)
        return names

    def queue_and_wait(self, wf: dict, timeout: int = 600) -> None:
        log.debug("queuing workflow: prefix=%s ckpt=%s seed=%s",
                  wf["8"]["inputs"]["filename_prefix"], wf["1"]["inputs"]["ckpt_name"],
                  wf["2"]["inputs"]["seed"])
        log.info("prompt: %s", wf["3"]["inputs"]["text"])
        req = urllib.request.Request(
            f"{self.endpoint}/prompt",
            data=json.dumps({"prompt": wf}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                pid = json.loads(r.read())["prompt_id"]
        except Exception as e:
            log.error("queue request failed for %s: %s",
                      wf["8"]["inputs"]["filename_prefix"], e)
            raise
        log.info("queued %s as %s", wf["8"]["inputs"]["filename_prefix"], pid)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if (time.time() - t0) % 30 < 1.5:
                log.debug("waiting on %s (%.0fs elapsed)", pid, time.time() - t0)
            with urllib.request.urlopen(f"{self.endpoint}/history/{pid}", timeout=30) as r:
                hist = json.loads(r.read())
            if pid in hist and hist[pid].get("status", {}).get("completed"):
                if hist[pid]["status"].get("status_str") == "error":
                    log.error("ComfyUI reported error for %s", pid)
                    raise RuntimeError(f"ComfyUI error for {pid}")
                log.info("finished %s in %.1fs", pid, time.time() - t0)
                return
            time.sleep(1.0)
        log.error("timeout waiting for %s after %ss", pid, timeout)
        raise TimeoutError(f"Image {pid} timed out")


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
