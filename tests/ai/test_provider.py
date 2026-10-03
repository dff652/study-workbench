import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import override_settings

from app.ai.provider import MAX_REQUEST_PAYLOAD, ProviderFailure, chat_completion


class _Server(ThreadingHTTPServer):
    response_status = 200
    response_body = b""
    last_authorization = None


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.last_authorization = self.headers.get("Authorization")
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.server.response_body)

    def log_message(self, *_args):
        pass


class ProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = {"base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "model": "synthetic-model", "timeout_seconds": 2, "max_output_tokens": 50,
            "test_http_enabled": True}

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    @override_settings(SWB_AI_ALLOW_TEST_HTTP=True, SWB_TEST_OWNER="synthetic", SWB_PRODUCTION=False)
    def test_loopback_mock_uses_fixed_server_key_and_parses_usage(self):
        self.server.response_body = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": "{}"}}], "usage": {"prompt_tokens": 4,
            "completion_tokens": 2}}).encode()
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False):
            content, usage = chat_completion(self.config, [{"role": "user", "content": "fiction"}])
        self.assertEqual(content, "{}")
        self.assertEqual(usage, {"prompt_tokens": 4, "completion_tokens": 2})
        self.assertEqual(self.server.last_authorization, "Bearer synthetic-only")

    @override_settings(SWB_AI_ALLOW_TEST_HTTP=True, SWB_TEST_OWNER="synthetic", SWB_PRODUCTION=False)
    def test_refusal_truncation_and_redirect_are_separate_failures(self):
        base = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        for finish, refusal, expected in (("length", None, "provider_truncated"),
                ("stop", "synthetic refusal", "provider_refusal")):
            body = dict(base)
            body["choices"] = [{"finish_reason": finish, "message": {"content": "{}", "refusal": refusal}}]
            self.server.response_status = 200
            self.server.response_body = json.dumps(body).encode()
            with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False):
                with self.assertRaises(ProviderFailure) as failure:
                    chat_completion(self.config, [])
            self.assertEqual(failure.exception.code, expected)
        self.server.response_status = 302
        self.server.response_body = b"{}"
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False):
            with self.assertRaises(ProviderFailure) as failure:
                chat_completion(self.config, [])
        self.assertEqual(failure.exception.code, "provider_redirect")

    @override_settings(SWB_AI_ALLOW_TEST_HTTP=True, SWB_TEST_OWNER="synthetic", SWB_PRODUCTION=False)
    def test_non_stop_finish_and_invalid_usage_never_become_success(self):
        for finish, usage, expected in (("content_filter", {"prompt_tokens": 1, "completion_tokens": 1}, "provider_incomplete"),
                ("stop", {"prompt_tokens": -1, "completion_tokens": 1}, "provider_usage_invalid"),
                ("stop", {"prompt_tokens": True, "completion_tokens": 1}, "provider_usage_invalid")):
            self.server.response_body = json.dumps({"choices": [{"finish_reason": finish,
                "message": {"content": "{}"}}], "usage": usage}).encode()
            with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False):
                with self.assertRaises(ProviderFailure) as failure:
                    chat_completion(self.config, [])
            self.assertEqual(failure.exception.code, expected)

    def test_unapproved_https_host_fails_before_request(self):
        config = {**self.config, "base_url": "https://example.invalid/v1"}
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only", "SWB_MODEL_ALLOWED_HOSTS": ""}, clear=False):
            with self.assertRaises(ProviderFailure) as failure:
                chat_completion(config, [])
        self.assertEqual(failure.exception.code, "endpoint_rejected")

    @override_settings(SWB_AI_ALLOW_TEST_HTTP=True, SWB_TEST_OWNER="synthetic", SWB_PRODUCTION=False)
    def test_oversized_serialized_request_fails_before_http_request(self):
        messages = [{"role": "user", "content": "x" * MAX_REQUEST_PAYLOAD}]
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False):
            with self.assertRaises(ProviderFailure) as failure:
                chat_completion(self.config, messages)
        self.assertEqual(failure.exception.code, "request_payload_too_large")
        self.assertIsNone(self.server.last_authorization)
