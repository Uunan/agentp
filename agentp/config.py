"""config.json + model_config.json yukleme/kaydetme."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _load(name):
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8"))


def load_config():
    _load_env()
    return _load("config.json")


def load_model_config():
    return _load("model_config.json")


def save_config(cfg):
    (ROOT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def save_model_config(cfg):
    (ROOT / "model_config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def enabled_labels(mc):
    return {k: v for k, v in mc.get("labels", {}).items() if v.get("enabled")}
