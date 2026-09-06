"""Rastgele sahte deger ureticiler (orijinali ele vermez, formati korur)."""
import re
import secrets
import string

ALNUM = string.ascii_letters + string.digits


def _rand(n, alpha=None):
    alpha = alpha or ALNUM
    return "".join(secrets.choice(alpha) for _ in range(n))


def fake_for(label, original):
    if label == "API":
        m = re.match(r"^([A-Za-z]+[-_][A-Za-z]+[-_])", original)
        if m:
            pre = m.group(1)
            return pre + "fake" + _rand(max(8, len(original) - len(pre) - 4))
        m = re.match(r"^(sk-[A-Za-z0-9_-]{0,12})", original)
        if m:
            pre = m.group(1)
            return pre + _rand(max(8, len(original) - len(pre)))
        return "FAKE-API-" + _rand(max(12, len(original) - 9))
    return f"[REDACTED-{label}]"


def mask_for(label):
    return f"[REDACTED-{label}]"
