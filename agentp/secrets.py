"""Deterministic secret/API-key regex detector (NER fallback).

NER may miss tokens based on context (e.g. naked keys, nvapi-*, contextless tokens).
These rules always run, assign score 1.0, and strip trailing punctuation from spans.
"""
import re

# (pattern, capture_group) — group 0 matches entire regex
_PATTERNS = [
    # Stripe / general sk_live / sk_test (underscore or hyphen)
    (r"sk[-_]live[-_][A-Za-z0-9]+", 0),
    (r"sk[-_]test[-_][A-Za-z0-9]+", 0),
    (r"rk[-_]live[-_][A-Za-z0-9]+", 0),
    (r"rk[-_]test[-_][A-Za-z0-9]+", 0),
    (r"whsec_[A-Za-z0-9]+", 0),
    # Anthropic / OpenAI project keys
    (r"sk-ant-[A-Za-z0-9\-_]+", 0),
    (r"sk-proj-[A-Za-z0-9\-_]+", 0),
    # OpenAI legacy: sk- + min 16 chars (reduces FP)
    (r"sk-[A-Za-z0-9]{16,}", 0),
    # GitHub
    (r"ghp_[A-Za-z0-9]{16,}", 0),
    (r"gho_[A-Za-z0-9]{16,}", 0),
    (r"ghu_[A-Za-z0-9]{16,}", 0),
    (r"ghs_[A-Za-z0-9]{16,}", 0),
    (r"github_pat_[A-Za-z0-9_]+", 0),
    # Slack
    (r"xox[bpas]-[A-Za-z0-9\-_]+", 0),
    # AWS access key id
    (r"AKIA[0-9A-Z]{16}", 0),
    # NVIDIA
    (r"nvapi-[A-Za-z0-9_\-\.]{8,}", 0),
    # Bearer token: capture only token ("Bearer " prefix preserved)
    (r"Bearer\s+([A-Za-z0-9_\-\.~\+/=_:]{16,})", 1),
    # Explicit assignments like api_key=... / api-key: ...
    (r"(?i)api[_-]?key\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.~]{12,})", 1),
    # General fallback: anything starting with sk_ / sk- (min 8 chars)
    (r"sk[_-][A-Za-z0-9_\-]{8,}", 0),
]

_COMPILED = [(re.compile(p), g) for p, g in _PATTERNS]

TRAILING = ".,;:!?\"')]}>、。，；：！？」』”’"


def find_secret_spans(text):
    """Returns secret spans in text: [{label,start,end,text,score}]."""
    spans = []
    for rx, grp in _COMPILED:
        for m in rx.finditer(text):
            try:
                s, e = m.span(grp)
            except IndexError:
                continue
            if e <= s:
                continue
            # Trim trailing punctuation (sentence dots, quotes, etc.)
            while e > s and text[e - 1] in TRAILING:
                e -= 1
            if e <= s:
                continue
            # Drop very short snippets
            if e - s < 8:
                continue
            spans.append({
                "label": "API",
                "start": s,
                "end": e,
                "text": text[s:e],
                "score": 1.0,
            })
    # Deduplicate identical spans
    uniq = {}
    for sp in spans:
        uniq[(sp["start"], sp["end"])] = sp
    return sorted(uniq.values(), key=lambda s: (s["start"], s["end"]))
