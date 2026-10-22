"""Vision-model client for two backends:

- openrouter: hosted models through OpenRouter (default; needs OPENROUTER_API_KEY)
- ollama:     a local Ollama server (free, offline, slower and less accurate)

Every call is recorded in `LLM.usage` (tokens and the exact USD cost OpenRouter
bills) so the pipeline can report cost per bill.
"""
import base64
import io
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

from . import config

# python.org Python builds on macOS ship without a CA bundle; the system one works.
_SSL_CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else None


def to_b64(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


class LLM:
    def __init__(self, backend=None, model=None):
        self.backend = backend or config.default_backend()
        if self.backend not in config.MODELS:
            raise ValueError(f"unknown backend {self.backend!r}; choose from {list(config.MODELS)}")
        self.model = model or config.MODELS[self.backend]
        self.usage = []   # one dict per call; the pipeline clears it per bill

    @property
    def name(self):
        return f"{self.backend}:{self.model}"

    def chat(self, prompt, img, schema=None, max_tokens=4096, step="other"):
        """Send one prompt + one image; return the text answer.
        With `schema`, the answer is constrained to that JSON schema (returned as a JSON string)."""
        if self.backend == "openrouter":
            out = self._openrouter(prompt, img, schema, max_tokens, step)
        else:
            out = self._ollama(prompt, img, schema, max_tokens, step)
        out = re.sub(r"^.*?</think>", "", out, flags=re.S).strip()
        # some providers wrap JSON in a code fence despite response_format
        return re.sub(r"^```(?:json)?\s*|\s*```$", "", out) if schema else out

    def usage_summary(self):
        return {
            "calls": len(self.usage),
            "prompt_tokens": sum(c["prompt_tokens"] for c in self.usage),
            "completion_tokens": sum(c["completion_tokens"] for c in self.usage),
            "cost_usd": round(sum(c["cost_usd"] for c in self.usage), 8),
            "per_call": list(self.usage),
        }

    def _record(self, step, prompt_tokens, completion_tokens, cost, provider):
        self.usage.append({"step": step, "prompt_tokens": prompt_tokens or 0,
                           "completion_tokens": completion_tokens or 0, "cost_usd": cost or 0,
                           "provider": provider})

    def _openrouter(self, prompt, img, schema, max_tokens, step, attempts=7):
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set (put it in .env, see .env.example)")
        body = {
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
            "usage": {"include": True},
            # With reasoning on, Nemotron spends the whole token budget thinking and returns nothing.
            "reasoning": {"enabled": False},
            # Cheapest host first. For Nemotron that is Crusoe, which is also the only full-precision
            # (bf16) host; the rest run 4-bit. require_parameters skips hosts that ignore
            # response_format. Falls back to the next cheapest host if one is down.
            "provider": {"sort": "price", "require_parameters": True, "allow_fallbacks": True},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + to_b64(img)}}]}],
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "invoice", "schema": schema}}
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        for n in range(attempts):
            try:
                req = urllib.request.Request(config.OPENROUTER_URL, json.dumps(body).encode(), headers)
                with urllib.request.urlopen(req, timeout=300, context=_SSL_CTX) as r:
                    resp = json.loads(r.read())
                u = resp.get("usage") or {}
                self._record(step, u.get("prompt_tokens"), u.get("completion_tokens"), u.get("cost"), resp.get("provider"))
                return resp["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503) or n == attempts - 1:
                    raise RuntimeError(f"OpenRouter {e.code}: {e.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError):
                if n == attempts - 1:
                    raise
            time.sleep(min(60, 2 ** n * 5))   # rate limits / transient errors: back off and retry

    def _ollama(self, prompt, img, schema, max_tokens, step):
        body = {"model": self.model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": prompt, "images": [to_b64(img)]}],
                "options": {"temperature": 0, "num_ctx": 16384, "num_predict": max_tokens}}
        if schema:
            body["format"] = schema
        req = urllib.request.Request(config.OLLAMA_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            resp = json.loads(r.read())
        self._record(step, resp.get("prompt_eval_count"), resp.get("eval_count"), 0, "ollama")
        return resp["message"]["content"]
