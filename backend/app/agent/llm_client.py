"""
Provider-agnostic LLM client, stdlib only (urllib).

The orchestrator speaks the Anthropic Messages format (content blocks with
`text` / `tool_use` / `tool_result`). This module returns that same shape no
matter which provider is configured, so orchestrator.py and the frontend do not
change when you switch providers.

Choose a provider with LLM_PROVIDER:

  anthropic  (paid)   ANTHROPIC_API_KEY, optional ANTHROPIC_MODEL
  ollama     (free, local, no key)   OLLAMA_MODEL (default qwen2.5:14b), OLLAMA_BASE_URL
  groq       (free tier)   GROQ_API_KEY, optional GROQ_MODEL
  gemini     (free tier)   GEMINI_API_KEY, optional GEMINI_MODEL
  openrouter (free ':free' models)   OPENROUTER_API_KEY, optional OPENROUTER_MODEL
  openai     (generic OpenAI-compatible)   LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

If LLM_PROVIDER is unset it is inferred: ANTHROPIC_API_KEY -> anthropic, else
GROQ_API_KEY -> groq, GEMINI_API_KEY -> gemini, OPENROUTER_API_KEY ->
openrouter, otherwise ollama.

Only the Anthropic path is paid. The OpenAI-compatible adapters were verified
against a local stub server (tests/test_llm_client.py), not against the live
services (no outbound network in the build sandbox) -- run
`python3 -m tests.agent_live_smoke_test` once with your chosen provider.
"""
import json
import os
import urllib.request
import urllib.error

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# provider -> (base_url, key_env, model_env, default_model, needs_key)
OPENAI_COMPAT = {
    "ollama": ("http://localhost:11434/v1", None, "OLLAMA_MODEL", "qwen2.5:14b", False),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "llama-3.3-70b-versatile", True),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash", True),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free", True),
    "openai": (None, "LLM_API_KEY", "LLM_MODEL", "gpt-4o-mini", False),
}


class LlmConfigError(Exception):
    pass


class LlmRequestError(Exception):
    def __init__(self, status, body):
        super().__init__(f"LLM API returned HTTP {status}: {body}")
        self.status = status
        self.body = body


def provider():
    p = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if p:
        if p != "anthropic" and p not in OPENAI_COMPAT:
            raise LlmConfigError(f"Unknown LLM_PROVIDER '{p}'. Use anthropic, ollama, groq, gemini, openrouter or openai.")
        return p
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    for name in ("groq", "gemini", "openrouter"):
        if os.environ.get(OPENAI_COMPAT[name][1]):
            return name
    return "ollama"


def _post(url, headers, body, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LlmRequestError(e.code, e.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as e:
        raise LlmRequestError(0, f"Network error reaching {url}: {e}")


# ---------------------------------------------------------------- Anthropic
def _call_anthropic(messages, tools, system, model, max_tokens):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LlmConfigError("ANTHROPIC_API_KEY is not set (paid provider). For a free option set "
                             "LLM_PROVIDER=ollama (local) or GROQ_API_KEY / GEMINI_API_KEY -- see the README.")
    body = {"model": model or DEFAULT_MODEL, "max_tokens": max_tokens, "messages": messages}
    if tools:
        body["tools"] = tools
    if system:
        body["system"] = system
    return _post(ANTHROPIC_API_URL, {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}, body, timeout=30)


# ------------------------------------------------- OpenAI-compatible adapter
def to_openai_messages(messages, system=None):
    out = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        if m["role"] == "assistant":
            text = "\n".join(b.get("text", "") for b in c if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
                     for b in c if b.get("type") == "tool_use"]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            for b in c:
                if b.get("type") == "tool_result":
                    content = b.get("content")
                    if not isinstance(content, str):
                        content = json.dumps(content)
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": content})
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b.get("text", "")})
    return out


def to_openai_tools(tools):
    return [{"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""),
        "parameters": t.get("input_schema", {"type": "object", "properties": {}})}} for t in tools]


def from_openai_response(data):
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LlmRequestError(200, f"Unexpected response shape: {str(data)[:300]}")
    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        content.append({"type": "tool_use", "id": tc.get("id") or f"call_{i}",
                        "name": fn.get("name", ""), "input": args})
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
    return {"role": "assistant", "content": content, "stop_reason": stop}


def _call_openai_compat(name, messages, tools, system, model, max_tokens):
    default_url, key_env, model_env, default_model, needs_key = OPENAI_COMPAT[name]
    base = os.environ.get("LLM_BASE_URL") if name == "openai" else os.environ.get("OLLAMA_BASE_URL", default_url) if name == "ollama" else default_url
    if not base:
        raise LlmConfigError("LLM_BASE_URL is not set for LLM_PROVIDER=openai.")
    key = os.environ.get(key_env) if key_env else None
    if needs_key and not key:
        raise LlmConfigError(f"{key_env} is not set (LLM_PROVIDER={name}). See the README for how to get a free key.")
    body = {"model": model or os.environ.get(model_env) or default_model,
            "messages": to_openai_messages(messages, system), "max_tokens": max_tokens}
    if tools:
        body["tools"] = to_openai_tools(tools)
    headers = {"Authorization": f"Bearer {key or 'none'}"}
    timeout = 180 if name == "ollama" else 60  # local models can be slow on CPU
    return from_openai_response(_post(base.rstrip("/") + "/chat/completions", headers, body, timeout))


def call_claude(messages, tools=None, system=None, model=None, max_tokens=1024):
    """Name kept for the orchestrator. Returns an Anthropic-shaped response
    ({'content': [text/tool_use blocks]}) from whichever provider is configured."""
    p = provider()
    if p == "anthropic":
        return _call_anthropic(messages, tools, system, model, max_tokens)
    return _call_openai_compat(p, messages, tools, system, model, max_tokens)
