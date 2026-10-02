"""Small OpenAI-compatible Chat Completions adapter with a strict endpoint boundary."""
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class ProviderFailure(Exception):
    def __init__(self, code, usage=None):
        self.code = code
        self.usage = usage
        super().__init__(code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parsed_url(config):
    parsed = urllib.parse.urlsplit(config["base_url"])
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderFailure("endpoint_rejected")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ProviderFailure("endpoint_rejected")
    try:
        parsed.port
    except ValueError:
        raise ProviderFailure("endpoint_rejected") from None
    return parsed, host


def _endpoint(config):
    parsed, host = _parsed_url(config)
    allowed = {item.strip().lower().rstrip(".") for item in
               os.environ.get("SWB_MODEL_ALLOWED_HOSTS", "").split(",") if item.strip()}
    loopback_test = (getattr(settings, "SWB_AI_ALLOW_TEST_HTTP", False)
        and not getattr(settings, "SWB_PRODUCTION", True)
        and getattr(settings, "SWB_TEST_OWNER", "")
        and config.get("test_http_enabled", False)
        and host in {"127.0.0.1", "::1", "localhost"}
        and parsed.scheme == "http")
    if not loopback_test and (parsed.scheme != "https" or host not in allowed):
        raise ProviderFailure("endpoint_rejected")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def validate_config_url(base_url, *, test_http_enabled=False):
    parsed, host = _parsed_url({"base_url": base_url})
    is_test_loopback = (parsed.scheme == "http" and host in {"127.0.0.1", "::1", "localhost"}
        and test_http_enabled and getattr(settings, "SWB_AI_ALLOW_TEST_HTTP", False)
        and not getattr(settings, "SWB_PRODUCTION", True) and getattr(settings, "SWB_TEST_OWNER", ""))
    if parsed.scheme != "https" and not is_test_loopback:
        raise ProviderFailure("endpoint_rejected")


def chat_completion(config, messages):
    endpoint = _endpoint(config)
    api_key = os.environ.get("SWB_MODEL_API_KEY", "")
    if not api_key:
        raise ProviderFailure("provider_key_missing")
    payload = json.dumps({"model": config["model"], "messages": messages,
        "temperature": 0, "max_tokens": config["max_output_tokens"],
        "response_format": {"type": "json_object"}}, separators=(",", ":")).encode()
    request = urllib.request.Request(endpoint, data=payload, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        "Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=config["timeout_seconds"]) as response:
            raw = response.read(1_048_577)
    except urllib.error.HTTPError as exc:
        code = "provider_redirect" if 300 <= exc.code < 400 else "provider_http_error"
        raise ProviderFailure(code) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise ProviderFailure("provider_timeout_or_network") from None
    if len(raw) > 1_048_576:
        raise ProviderFailure("provider_response_too_large")
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderFailure("provider_response_invalid") from None
    try:
        choice = envelope["choices"][0]
        message = choice["message"]
        usage = envelope["usage"]
        content = message["content"]
    except (TypeError, KeyError, IndexError):
        raise ProviderFailure("provider_response_invalid") from None
    if not isinstance(usage, dict):
        raise ProviderFailure("provider_usage_missing")
    prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if (type(prompt_tokens) is not int or type(completion_tokens) is not int
            or not 0 <= prompt_tokens <= 900_000 or not 0 <= completion_tokens <= 20_000):
        raise ProviderFailure("provider_usage_invalid")
    safe_usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise ProviderFailure("provider_truncated", safe_usage)
    if message.get("refusal"):
        raise ProviderFailure("provider_refusal", safe_usage)
    if finish_reason != "stop" or message.get("tool_calls"):
        raise ProviderFailure("provider_incomplete", safe_usage)
    if not isinstance(content, str):
        raise ProviderFailure("provider_response_invalid", safe_usage)
    return content, safe_usage
