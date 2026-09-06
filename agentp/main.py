"""Run:    python -m agentp.main            (server)
   Check:  python -m agentp.main --check    (model + sample detection, standalone)"""
import sys
import uvicorn
from .config import load_config, load_model_config
from .model import NerEngine
from .proxy import app  # noqa: F401  (uvicorn target)

SAMPLE = "Send a request using my API key sk-live_51N3xExample123456789, and write a summary."


def check():
    cfg = load_config()
    mc = load_model_config()
    mentry = cfg["models"][mc["active_model"]]
    eng = NerEngine(mentry["path"], threshold=mc.get("threshold", 0.6))
    print("model:", mc["active_model"], "| threshold:", mc.get("threshold"))
    for sp in eng.detect(SAMPLE):
        print(f"  {sp['text']!r:40} {sp['label']:10} score={sp['score']}")
    print("CHECK OK")


def main():
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
