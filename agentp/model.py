"""Egitilmis NER modelini yukler, metindeki hedefleri span olarak dondurur."""
from pathlib import Path
import torch
import torch.nn.functional as F
from transformers import PreTrainedTokenizerFast, AutoModelForTokenClassification

SPECIALS = {"unk_token": "<unk>", "pad_token": "<pad>", "cls_token": "<s>",
            "sep_token": "</s>", "mask_token": "<mask>", "bos_token": "<s>",
            "eos_token": "</s>"}


class NerEngine:
    def __init__(self, model_dir, threshold=0.6):
        p = Path(model_dir)
        if not p.is_absolute():
            from .config import ROOT
            cand = ROOT / p
            if cand.exists():
                p = cand
        if not p.exists() or not (p / "model.safetensors").exists():
            from huggingface_hub import snapshot_download
            print(f"[AgentP] Local model weights not found. Downloading from Hugging Face (Uunan/tamga-ner-b)...")
            downloaded = snapshot_download(repo_id="Uunan/tamga-ner-b")
            p = Path(downloaded)
        self.dir = p
        self.tok = PreTrainedTokenizerFast(
            tokenizer_file=str(self.dir / "tokenizer.json"), **SPECIALS)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModelForTokenClassification.from_pretrained(str(self.dir))
        self.model.to(self.device).eval()
        self.id2l = self.model.config.id2label
        self.threshold = threshold

    def _extract_spans_from_chunk(self, ids, offs, pmax, chunk_text, labels, thr, offset_start):
        cur = None
        spans = []
        for pid, (s, e) in zip(ids, offs):
            lab = self.id2l[pid]
            if s == e:
                continue
            if lab.startswith("B-"):
                if cur:
                    spans.append(cur)
                cur = {"label": lab[2:], "start": s, "end": e}
            elif lab.startswith("I-") and cur and cur["label"] == lab[2:]:
                cur["end"] = e
            else:
                if cur:
                    spans.append(cur)
                    cur = None
        if cur:
            spans.append(cur)

        out = []
        for o in spans:
            if labels is not None and o["label"] not in labels:
                continue
            ss = [p for p, (s, e) in zip(pmax, offs)
                  if not (s == 0 and e == 0) and s >= o["start"] and e <= o["end"]]
            o["score"] = round(sum(ss) / len(ss), 3) if ss else 0.0
            if o["score"] >= thr:
                raw_span = chunk_text[o["start"]:o["end"]]
                if o["label"] == "CONTACT":
                    while len(raw_span) > 1 and raw_span[-1] in ".,;:!?":
                        raw_span = raw_span[:-1]
                        o["end"] -= 1
                o["text"] = raw_span
                o["start"] += offset_start
                o["end"] += offset_start
                out.append(o)
        return out

    @torch.no_grad()
    def detect(self, text, labels=None, threshold=None):
        if not text or not text.strip():
            return []
        thr = self.threshold if threshold is None else threshold

        enc_full = self.tok(text, return_offsets_mapping=True)
        offs_full = enc_full["offset_mapping"]
        total_tokens = len(offs_full)

        candidate_spans = []
        if total_tokens <= 256:
            enc = self.tok(text, return_offsets_mapping=True, truncation=True, max_length=256, return_tensors="pt")
            offs = enc.pop("offset_mapping")[0].tolist()
            enc = {k: v.to(self.device) for k, v in enc.items()}
            probs = F.softmax(self.model(**enc).logits[0], -1)
            ids = probs.argmax(-1).tolist()
            pmax = probs.max(-1).values.tolist()
            candidate_spans.extend(self._extract_spans_from_chunk(ids, offs, pmax, text, labels, thr, 0))
        else:
            win_size = 200
            stride = 140
            windows = []
            for i in range(0, total_tokens, stride):
                s_token = i
                e_token = min(i + win_size, total_tokens - 1)
                s_char = offs_full[s_token][0]
                e_char = offs_full[e_token][1]
                if e_char > s_char:
                    windows.append((s_char, e_char))
                if e_token >= total_tokens - 1:
                    break

            chunk_texts = [text[sc:ec] for sc, ec in windows]
            chunk_starts = [sc for sc, ec in windows]
            enc_batch = self.tok(chunk_texts, return_offsets_mapping=True, truncation=True, padding=True, max_length=256, return_tensors="pt")
            all_offs = enc_batch.pop("offset_mapping").tolist()
            enc_batch = {k: v.to(self.device) for k, v in enc_batch.items()}

            num_chunks = len(chunk_texts)
            chunk_step = 16
            for start_idx in range(0, num_chunks, chunk_step):
                sub_enc = {k: v[start_idx:start_idx + chunk_step] for k, v in enc_batch.items()}
                logits = self.model(**sub_enc).logits
                probs = F.softmax(logits, -1)
                batch_ids = probs.argmax(-1).tolist()
                batch_pmax = probs.max(-1).values.tolist()

                for j, (ids, offs, pmax) in enumerate(zip(batch_ids, all_offs[start_idx:start_idx + chunk_step], batch_pmax)):
                    c_start = chunk_starts[start_idx + j]
                    c_text = chunk_texts[start_idx + j]
                    candidate_spans.extend(self._extract_spans_from_chunk(ids, offs, pmax, c_text, labels, thr, c_start))

        candidate_spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"]), -s["score"]))
        res = []
        for o in candidate_spans:
            if res and o["start"] < res[-1]["end"]:
                prev = res[-1]
                if prev["label"] == o["label"]:
                    prev["end"] = max(prev["end"], o["end"])
                    prev["score"] = max(prev["score"], o["score"])
                    prev["text"] = text[prev["start"]:prev["end"]]
                    if prev["label"] == "CONTACT":
                        while len(prev["text"]) > 1 and prev["text"][-1] in ".,;:!?":
                            prev["text"] = prev["text"][:-1]
                            prev["end"] -= 1
                continue
            res.append(o)
        return res
