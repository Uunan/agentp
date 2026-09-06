"""Lokal FastAPI proxy: /detect + OpenAI-uyumlu /v1/chat/completions."""
import copy
import json
import os
import uuid
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .config import load_config, load_model_config, enabled_labels
from .model import NerEngine
from .fake import fake_for, mask_for
from .secrets import find_secret_spans

cfg = load_config()
mc = load_model_config()
active = mc["active_model"]
mentry = cfg["models"][active]

engine = NerEngine(mentry["path"], threshold=mc.get("threshold", 0.6))
LABELS = enabled_labels(mc)
THR = mc.get("threshold", 0.6)
SCAN_ROLES = set(mc.get("scan_roles", ["user", "assistant", "system", "tool", "function"]))
UP = cfg["upstream"]
API_KEY = os.environ.get(UP.get("api_key_env", "OPENAI_API_KEY"), "")

# ANSI Styles
_L_REDACT = "\033[38;2;255;138;30;1m[🔒 AGENT-P REDACT]\033[0m"
_L_RESTORE = "\033[38;2;0;230;118;1m[🔄 AGENT-P RESTORE]\033[0m"
_L_PASS = "\033[38;2;144;164;174m[⚡ AGENT-P PASSTHROUGH]\033[0m"
_L_RESET = "\033[0m"
_L_CYAN = "\033[38;2;0;229;255m"
_L_GRAY = "\033[38;2;144;164;174m"
_L_WHITE = "\033[38;2;255;255;255m"


def _log_event(endpoint: str, count: int, extra: str = ""):
    if count > 0:
        s = f"{count} item{'s' if count > 1 else ''}"
        print(f"{_L_REDACT} {_L_CYAN}{s}{_L_RESET} redacted {_L_GRAY}({endpoint}{f' | {extra}' if extra else ''}){_L_RESET}", flush=True)
    else:
        print(f"{_L_PASS} {_L_GRAY}Clean payload ({endpoint}){_L_RESET}", flush=True)


def _log_restored(endpoint: str, count: int):
    if count > 0:
        s = f"{count} fake token{'s' if count > 1 else ''}"
        print(f"{_L_RESTORE} {_L_WHITE}{s}{_L_RESET} restored to original {_L_GRAY}({endpoint}){_L_RESET}", flush=True)


app = FastAPI(title="AgentP privacy proxy")


class DetectIn(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok", "model": mc["active_model"], "labels": list(LABELS.keys())}


@app.head("/api/hello")
@app.get("/api/hello")
def api_hello():
    return {"status": "ok"}


@app.get("/v1/models")
@app.get("/models")
def list_models():
    model_id = UP.get("model", "nvidia/nemotron-3.5-lightning-30b-a3b")
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": "agentp",
            },
            {
                "id": "agentp-privacy-proxy",
                "object": "model",
                "created": 1700000000,
                "owned_by": "agentp",
            },
        ],
    }


@app.post("/detect")
def detect(inp: DetectIn):
    spans = engine.detect(inp.text, labels=set(LABELS), threshold=THR)
    if "API" in LABELS:
        seen = {(s["start"], s["end"]) for s in spans}
        for rs in find_secret_spans(inp.text):
            if (rs["start"], rs["end"]) not in seen:
                spans.append(rs)
    return {"spans": spans}


def _swap_out(text, mapping=None, orig_to_fake=None):
    """Replace active labels with fake/mask values. Returns: (new_text, {fake: original}).
    NER + deterministic regex (secrets.py) operate concurrently; longer span wins on collisions.
    Trailing punctuation in API spans is trimmed.
    Consistent fake values are assigned to identical keys within the same request via orig_to_fake."""
    if mapping is None:
        mapping = {}
    if orig_to_fake is None:
        orig_to_fake = {}

    spans = engine.detect(text, labels=set(LABELS), threshold=THR)
    if "API" in LABELS:
        spans = list(spans) + find_secret_spans(text)
    # trailing noktalama temizligi (NER "ABC." gibi yakalayabiliyor)
    cleaned = []
    for sp in spans:
        s, e = sp["start"], sp["end"]
        while e > s and text[e - 1] in ".,;:!?\"')]}>":
            e -= 1
        if e <= s:
            continue
        sp = dict(sp)
        sp["end"] = e
        sp["text"] = text[s:e]
        cleaned.append(sp)
    # overlap cozumu: start'a gore sirala, bitiseni ele; ayni start'ta uzun kazanir
    cleaned.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged = []
    last_end = -1
    for sp in cleaned:
        if sp["start"] < last_end:
            continue
        merged.append(sp)
        last_end = sp["end"]

    for sp in sorted(merged, key=lambda s: s["start"], reverse=True):
        strat = LABELS[sp["label"]].get("strategy", "mask")
        if strat == "fake":
            orig = sp["text"]
            if orig in orig_to_fake:
                fake = orig_to_fake[orig]
            else:
                fake = fake_for(sp["label"], orig)
                while fake in mapping:
                    fake = fake_for(sp["label"], orig + uuid.uuid4().hex[:4])
                orig_to_fake[orig] = fake
                mapping[fake] = orig
            repl = fake
        else:
            repl = mask_for(sp["label"])
        text = text[:sp["start"]] + repl + text[sp["end"]:]
    return text, mapping


def _swap_back(text, mapping):
    for fake, orig in mapping.items():
        text = text.replace(fake, orig)
    return text


def _swap_back_json(obj, mapping):
    if isinstance(obj, str):
        return _swap_back(obj, mapping)
    if isinstance(obj, list):
        return [_swap_back_json(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: _swap_back_json(v, mapping) for k, v in obj.items()}
    return obj


def _redact_input(inp, mapping=None, orig_to_fake=None):
    """Responses-API input: str veya mesaj listesi. Donus: (yeni_input, mapping)."""
    if mapping is None:
        mapping = {}
    if orig_to_fake is None:
        orig_to_fake = {}
    if isinstance(inp, str):
        return _swap_out(inp, mapping, orig_to_fake)
    if isinstance(inp, list):
        out = []
        for item in inp:
            if isinstance(item, dict) and "content" in item:
                if item.get("role", "user") in SCAN_ROLES or "role" not in item:
                    item = dict(item)
                    item["content"], _ = _redact_text_content(item["content"], mapping, orig_to_fake)
            out.append(item)
        return out, mapping
    return inp, mapping


def _redact_text_content(content, mapping=None, orig_to_fake=None):
    """OpenAI message content: str veya multimodal liste. Donus: (yeni, mapping)."""
    if mapping is None:
        mapping = {}
    if orig_to_fake is None:
        orig_to_fake = {}
    if isinstance(content, str):
        return _swap_out(content, mapping, orig_to_fake)
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part = dict(part)
                part["text"], _ = _swap_out(part["text"], mapping, orig_to_fake)
            out.append(part)
        return out, mapping
    return content, mapping


@app.post("/v1/chat/completions")
async def chat(body: dict):
    if not API_KEY:
        raise HTTPException(500, f"Missing upstream API key in environment: {UP.get('api_key_env')}")
    is_stream = bool(body.get("stream", False))
    body = copy.deepcopy(body)
    body["stream"] = False
    body.pop("stream_options", None)
    if UP.get("model"):
        body["model"] = UP["model"]
    mapping = {}
    orig_to_fake = {}
    msgs = body.get("messages", [])
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get("role") in SCAN_ROLES:
            if "content" in m and m["content"]:
                m["content"], _ = _redact_text_content(m["content"], mapping, orig_to_fake)
            if "tool_calls" in m and isinstance(m["tool_calls"], list):
                for tc in m["tool_calls"]:
                    if isinstance(tc, dict) and "function" in tc:
                        fn = tc["function"]
                        if isinstance(fn.get("arguments"), str):
                            fn["arguments"], _ = _swap_out(fn["arguments"], mapping, orig_to_fake)
    _log_event("/v1/chat/completions", len(mapping), f"roles={','.join(SCAN_ROLES)}")
    url = UP["base_url"].rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=UP.get("timeout_s", 60)) as cli:
            r = await cli.post(url, json=body,
                               headers={"Authorization": f"Bearer {API_KEY}"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach upstream endpoint: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    for ch in data.get("choices", []):
        msg = ch.get("message", {})
        if isinstance(msg.get("content"), str):
            msg["content"] = _swap_back(msg["content"], mapping)
        if isinstance(msg.get("tool_calls"), list):
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict) and "function" in tc:
                    fn = tc["function"]
                    if isinstance(fn.get("arguments"), str):
                        fn["arguments"] = _swap_back(fn["arguments"], mapping)
    _log_restored("/v1/chat/completions", len(mapping))
    data["agentp_redacted"] = sorted(set(mapping.values()))

    if is_stream:
        async def sse_generator():
            chunk_id = data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}")
            created = data.get("created", 1700000000)
            model = data.get("model", UP.get("model", "agentp"))
            for ch in data.get("choices", []):
                idx = ch.get("index", 0)
                msg = ch.get("message", {})
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
                role = msg.get("role", "assistant")

                # Chunk 1: content + role
                chunk1 = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": idx,
                            "delta": {
                                "role": role,
                                "content": content
                            },
                            "finish_reason": None
                        }
                    ]
                }
                if tool_calls is not None:
                    chunk1["choices"][0]["delta"]["tool_calls"] = tool_calls
                yield f"data: {json.dumps(chunk1, ensure_ascii=False)}\n\n"

                # Chunk 2: finish_reason
                chunk2 = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": idx,
                            "delta": {},
                            "finish_reason": ch.get("finish_reason", "stop")
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk2, ensure_ascii=False)}\n\n"

            if "usage" in data:
                usage_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": data["usage"]
                }
                yield f"data: {json.dumps(usage_chunk, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    return data


@app.post("/v1/responses")
async def responses(body: dict):
    if not API_KEY:
        raise HTTPException(500, f"Missing upstream API key in environment: {UP.get('api_key_env')}")
    body = dict(body)
    if UP.get("model") and "model" not in body:
        body["model"] = UP["model"]
    mapping = {}
    orig_to_fake = {}
    if "input" in body:
        body["input"], mapping = _redact_input(body["input"], mapping, orig_to_fake)
    else:
        mapping = {}
    _log_event("/v1/responses", len(mapping))
    url = UP["base_url"].rstrip("/") + "/responses"
    try:
        async with httpx.AsyncClient(timeout=UP.get("timeout_s", 120)) as cli:
            r = await cli.post(url, json=body,
                               headers={"Authorization": f"Bearer {API_KEY}",
                                        "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach upstream endpoint: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    data = _swap_back_json(r.json(), mapping)
    _log_restored("/v1/responses", len(mapping))
    if isinstance(data, dict):
        data["agentp_redacted"] = sorted(set(mapping.values()))
    return data


@app.post("/v1/messages")
@app.post("/messages")
async def anthropic_messages(body: dict):
    """Anthropic Claude Messages API adapter for Claude Code and Anthropic clients."""
    if not API_KEY:
        raise HTTPException(500, f"Missing upstream API key in environment: {UP.get('api_key_env')}")
    
    mapping = {}
    orig_to_fake = {}
    
    # 1. Redact system prompt
    system_content = body.get("system", "")
    if isinstance(system_content, str) and system_content:
        system_content, _ = _swap_out(system_content, mapping, orig_to_fake)
    elif isinstance(system_content, list):
        new_sys = []
        for blk in system_content:
            if isinstance(blk, dict) and "text" in blk:
                blk = dict(blk)
                blk["text"], _ = _swap_out(blk["text"], mapping, orig_to_fake)
            new_sys.append(blk)
        system_content = new_sys

    # 2. Redact messages
    msgs = body.get("messages", [])
    redacted_msgs = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        m_copy = dict(m)
        if m_copy.get("role") in SCAN_ROLES and "content" in m_copy:
            m_copy["content"], _ = _redact_text_content(m_copy["content"], mapping, orig_to_fake)
        redacted_msgs.append(m_copy)

    _log_event("/v1/messages (Claude Code)", len(mapping))

    is_upstream_anthropic = "anthropic.com" in UP.get("base_url", "").lower()

    if is_upstream_anthropic:
        url = UP["base_url"].rstrip("/") + "/messages"
        out_body = dict(body)
        out_body["messages"] = redacted_msgs
        if system_content:
            out_body["system"] = system_content
        headers = {
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
    else:
        url = UP["base_url"].rstrip("/") + "/chat/completions"
        openai_msgs = []
        if system_content:
            sys_text = system_content if isinstance(system_content, str) else json.dumps(system_content)
            openai_msgs.append({"role": "system", "content": sys_text})
        for rm in redacted_msgs:
            c = rm.get("content")
            text_c = c if isinstance(c, str) else json.dumps(c)
            openai_msgs.append({"role": rm.get("role", "user"), "content": text_c})
        
        out_body = {
            "model": UP.get("model", "nvidia/nemotron-3.5-lightning-30b-a3b"),
            "messages": openai_msgs,
            "stream": False
        }
        if "max_tokens" in body:
            out_body["max_tokens"] = body["max_tokens"]
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }

    try:
        async with httpx.AsyncClient(timeout=UP.get("timeout_s", 120)) as cli:
            r = await cli.post(url, json=out_body, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach upstream endpoint: {e}")

    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)

    resp_data = r.json()

    if is_upstream_anthropic:
        for blk in resp_data.get("content", []):
            if blk.get("type") == "text" and isinstance(blk.get("text"), str):
                blk["text"] = _swap_back(blk["text"], mapping)
        _log_restored("/v1/messages (Claude Code)", len(mapping))
        resp_data["agentp_redacted"] = sorted(set(mapping.values()))
        return resp_data
    else:
        first_choice = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
        restored_text = _swap_back(first_choice, mapping)
        _log_restored("/v1/messages (Claude Code)", len(mapping))
        return {
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", UP.get("model", "claude-3-5-sonnet")),
            "content": [
                {
                    "type": "text",
                    "text": restored_text
                }
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": resp_data.get("usage", {"input_tokens": 10, "output_tokens": 10}),
            "agentp_redacted": sorted(set(mapping.values()))
        }
