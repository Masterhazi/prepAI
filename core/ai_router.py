"""
ai_router.py — Three-engine router: Claude → Gemini → Groq
Automatic fallback, per-model cooldown, smart model selection.
"""

import os, time, json
from core.vault import get_key

# ── Model lists (text-only, suitable for our tasks) ───────────────────────────

CLAUDE_MODELS = [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]

GEMINI_TEXT_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",   # best quality, supports tool calling
    "llama-3.1-8b-instant",      # ultra-fast fallback
    "mixtral-8x7b-32768",        # strong alternative, long context
    # gemma2-9b-it excluded — Gemma is Google's model, not suited for agent tool calling
]

# ── State ──────────────────────────────────────────────────────────────────────

_preferred_engine = "auto"   # auto | claude | gemini | groq
_current_engine   = "claude"
_current_model    = ""
_last_fallback    = None

_cooldowns: dict[str, float] = {}          # model_id → epoch when cooldown expires
_gemini_models_cache = None

SYSTEM_PROMPT = "You are PrepAI, an expert interview preparation assistant. Be concise and actionable."


# ── Preference ────────────────────────────────────────────────────────────────

def set_preferred_engine(engine: str):
    global _preferred_engine
    _preferred_engine = engine


def get_preferred_engine() -> str:
    return _preferred_engine


# ── Cooldown helpers ──────────────────────────────────────────────────────────

def _set_cooldown(model_id: str, seconds: int = 60):
    _cooldowns[model_id] = time.time() + seconds


def _is_on_cooldown(model_id: str) -> bool:
    exp = _cooldowns.get(model_id, 0)
    if exp and time.time() < exp:
        return True
    if model_id in _cooldowns:
        del _cooldowns[model_id]
    return False


# ── Clients ───────────────────────────────────────────────────────────────────

def _get_claude_client():
    key = get_key("anthropic_api_key")
    if not key:
        raise ValueError("Anthropic API key not set.")
    from anthropic import Anthropic
    return Anthropic(api_key=key)


def _get_gemini_client():
    key = get_key("gemini_api_key")
    if not key:
        raise ValueError("Gemini API key not set.")
    from google import genai
    return genai.Client(api_key=key)


def _get_groq_client():
    key = get_key("groq_api_key")
    if not key:
        raise ValueError("Groq API key not set.")
    from groq import Groq
    return Groq(api_key=key)


# ── Model pickers ─────────────────────────────────────────────────────────────

def _pick_claude_model() -> str | None:
    for m in CLAUDE_MODELS:
        if not _is_on_cooldown(m):
            return m
    return None


def _get_available_gemini_models(client) -> list:
    global _gemini_models_cache
    if _gemini_models_cache:
        return _gemini_models_cache
    try:
        available = []
        for m in client.models.list():
            name = m.name.replace("models/", "")
            if name in GEMINI_TEXT_MODELS:
                available.append(name)
        if available:
            # Sort by preferred order
            _gemini_models_cache = sorted(available, key=lambda x: GEMINI_TEXT_MODELS.index(x) if x in GEMINI_TEXT_MODELS else 99)
            return _gemini_models_cache
    except Exception:
        pass
    return GEMINI_TEXT_MODELS


def _pick_gemini_model(client) -> str | None:
    models = _get_available_gemini_models(client)
    for m in models:
        if not _is_on_cooldown(m):
            return m
    return None


def _pick_groq_model() -> str | None:
    for m in GROQ_MODELS:
        if not _is_on_cooldown(m):
            return m
    return None


# ── Current state ─────────────────────────────────────────────────────────────

def current_engine() -> str:
    return _current_engine


def current_model() -> str:
    return _current_model


def last_fallback_reason() -> str | None:
    return _last_fallback


def engine_status() -> dict:
    return {
        "current_engine":         _current_engine,
        "current_model":          _current_model,
        "preferred":              _preferred_engine,
        "last_fallback":          _last_fallback,
        "claude_has_key":         bool(get_key("anthropic_api_key")),
        "gemini_has_key":         bool(get_key("gemini_api_key")),
        "groq_has_key":           bool(get_key("groq_api_key")),
        "claude_models":          CLAUDE_MODELS,
        "gemini_models_preferred": GEMINI_TEXT_MODELS,
        "groq_models":            GROQ_MODELS,
    }


# ── Core ask functions ────────────────────────────────────────────────────────

def _ask_claude(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 1500) -> dict:
    global _current_engine, _current_model, _last_fallback
    from anthropic import RateLimitError, APIStatusError
    client = _get_claude_client()
    model = _pick_claude_model()
    if not model:
        raise RuntimeError("All Claude models on cooldown")
    try:
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        _current_engine = "claude"
        _current_model = model
        _last_fallback = None
        return {"engine": "claude", "model": model, "text": resp.content[0].text, "grounded": False}
    except (RateLimitError, APIStatusError) as e:
        _set_cooldown(model, 60)
        raise RuntimeError(f"Claude rate limited: {e}")


def _ask_gemini(prompt: str, system: str = SYSTEM_PROMPT,
                use_search: bool = False, max_tokens: int = 1500) -> dict:
    global _current_engine, _current_model
    from google.genai import types as gt
    client = _get_gemini_client()
    model = _pick_gemini_model(client)
    if not model:
        raise RuntimeError("All Gemini models on cooldown")

    full = f"{system}\n\n{prompt}"
    cfg_kwargs = {"max_output_tokens": max_tokens}
    if use_search:
        cfg_kwargs["tools"] = [gt.Tool(google_search=gt.GoogleSearch())]

    resp = client.models.generate_content(
        model=model, contents=full,
        config=gt.GenerateContentConfig(**cfg_kwargs),
    )
    _current_engine = "gemini"
    _current_model = model
    grounded = use_search and bool(
        resp.candidates and getattr(resp.candidates[0], "grounding_metadata", None)
    )
    return {"engine": "gemini", "model": model, "text": resp.text or "", "grounded": grounded}


def _ask_groq(prompt: str, system: str = SYSTEM_PROMPT, max_tokens: int = 1500) -> dict:
    global _current_engine, _current_model
    client = _get_groq_client()
    model = _pick_groq_model()
    if not model:
        raise RuntimeError("All Groq models on cooldown")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
            max_tokens=max_tokens, temperature=0.7,
        )
        _current_engine = "groq"
        _current_model = model
        return {"engine": "groq", "model": model, "text": resp.choices[0].message.content, "grounded": False}
    except Exception as e:
        err = str(e).lower()
        if "rate" in err or "quota" in err or "429" in err:
            _set_cooldown(model, 60)
        raise RuntimeError(f"Groq error: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def ask(prompt: str, system: str = SYSTEM_PROMPT,
        use_search_grounding: bool = False,
        force_gemini: bool = False,
        force_groq: bool = False,
        max_tokens: int = 1500) -> dict:
    """
    Send prompt using user's preferred engine with automatic fallback.
    Claude → Gemini → Groq
    """
    global _last_fallback
    pref = _preferred_engine

    if force_gemini or pref == "gemini":
        return _ask_gemini(prompt, system, use_search_grounding, max_tokens)
    if force_groq or pref == "groq":
        return _ask_groq(prompt, system, max_tokens)

    # Try Claude
    if pref in ("auto", "claude") and get_key("anthropic_api_key"):
        try:
            return _ask_claude(prompt, system, max_tokens)
        except RuntimeError as e:
            _last_fallback = f"Claude unavailable ({e}) — trying Gemini"

    # Try Gemini
    if pref in ("auto",) and get_key("gemini_api_key"):
        try:
            return _ask_gemini(prompt, system, use_search_grounding, max_tokens)
        except RuntimeError as e:
            _last_fallback = f"Gemini unavailable ({e}) — trying Groq"

    # Try Groq
    if pref in ("auto",) and get_key("groq_api_key"):
        try:
            return _ask_groq(prompt, system, max_tokens)
        except RuntimeError as e:
            _last_fallback = f"Groq unavailable ({e})"

    raise RuntimeError("All AI engines unavailable. Check your API keys in Settings.")


def ask_with_jobs(prompt: str) -> dict:
    """Always use Gemini with search grounding for live job data."""
    system = (
        "You are PrepAI's job scanner. Use Google Search to find current job listings. "
        "Return structured data with job_title, company, location, match_reason, "
        "apply_url, deadline, required_skills."
    )
    try:
        return _ask_gemini(prompt, system, use_search=True)
    except Exception:
        # Fall back to non-grounded if Gemini fails
        return ask(prompt, system)


def stream_ask(prompt: str, system: str = SYSTEM_PROMPT, on_chunk=None) -> dict:
    """
    Streaming ask — calls on_chunk(text) for each token if provided.
    Tries Claude streaming first, falls back to simulated streaming via ask().
    """
    import time as _time
    global _current_engine, _current_model, _last_fallback

    pref = get_preferred_engine()

    # Try Claude native streaming
    if pref in ("auto", "claude") and get_key("anthropic_api_key"):
        try:
            from anthropic import RateLimitError, APIStatusError
            client = _get_claude_client()
            model  = _pick_claude_model()
            if model:
                full = []
                with client.messages.stream(
                    model=model, max_tokens=1500, system=system,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        full.append(text)
                        if on_chunk: on_chunk(text)
                _current_engine = "claude"
                _current_model  = model
                return {"engine": "claude", "model": model,
                        "text": "".join(full), "grounded": False}
        except Exception as e:
            _last_fallback = f"Claude stream failed: {e}"

    # Fallback: regular ask + simulate streaming
    result = ask(prompt, system)
    if on_chunk and result.get("text"):
        for word in result["text"].split(" "):
            on_chunk(word + " ")
            _time.sleep(0.012)
    return result
