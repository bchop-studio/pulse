import importlib.machinery
import importlib.util
import io
import os
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch


def load_pulse():
    loader = importlib.machinery.SourceFileLoader("pulse_module", "./pulse")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("could not load pulse")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


_TEST_HOME = Path(tempfile.gettempdir()) / f"pulse-tests-{os.getpid()}-missing"
with patch.dict(os.environ, {"HERMES_HOME": str(_TEST_HOME)}):
    pulse = load_pulse()


CATALOG = [
    {
        "id": "vendor/free-model:free",
        "name": "Free Model",
        "pricing": {"prompt": "0", "completion": "0"},
    },
    {
        "id": "vendor/sale-model",
        "name": "Sale Model",
        "pricing": {
            "prompt": "0.0000012",
            "completion": "0.000004",
            "original": {"prompt": "0.0000015", "completion": "0.000005"},
        },
    },
    {
        "id": "vendor/regular-model",
        "name": "Regular Model",
        "pricing": {"prompt": "0.000002", "completion": "0.000006"},
    },
]


class CatalogTests(unittest.TestCase):
    def test_price_output_strips_model_control_characters(self):
        rows = pulse.normalize_catalog([
            {"id": "model\x1b[2J", "pricing": {"prompt": "0", "completion": "0"}}
        ])

        output = pulse.render_catalog(rows, "all")

        self.assertNotIn("\x1b[2J", output)
        self.assertIn("model", output)

    def test_normalizes_prices_per_million_tokens_and_labels(self):
        rows = pulse.normalize_catalog(CATALOG)

        self.assertEqual(rows[0]["kind"], "free")
        self.assertEqual(rows[0]["input_per_million"], 0.0)
        self.assertEqual(rows[1]["kind"], "sale")
        self.assertEqual(rows[1]["input_per_million"], 1.2)
        self.assertEqual(rows[1]["output_per_million"], 4.0)
        self.assertEqual(rows[1]["original_input_per_million"], 1.5)
        self.assertEqual(rows[2]["kind"], "standard")

    def test_filters_catalog_to_free_or_sale_models(self):
        rows = pulse.normalize_catalog(CATALOG)

        self.assertEqual([r["id"] for r in pulse.filter_catalog(rows, "free")],
                         ["vendor/free-model:free"])
        self.assertEqual([r["id"] for r in pulse.filter_catalog(rows, "sale")],
                         ["vendor/sale-model"])

    def test_fetches_full_nous_model_metadata(self):
        provider = {"provider": "nous", "base_url": "https://example.test/v1", "key": "hidden"}
        response = {"data": CATALOG}

        with patch.object(pulse, "_http_json", return_value=(200, response, "")) as request:
            rows, error = pulse.get_model_catalog(provider)

        self.assertEqual(rows, CATALOG)
        self.assertEqual(error, "")
        self.assertEqual(request.call_args.args[0], "https://example.test/v1/models")

    def test_price_output_explains_units_and_sale_price(self):
        text = pulse.render_catalog(pulse.normalize_catalog(CATALOG), "all")

        self.assertIn("USD per 1M tokens", text)
        self.assertIn("vendor/free-model:free", text)
        self.assertIn("FREE", text)
        self.assertIn("SALE", text)
        self.assertIn("$1.20", text)
        self.assertIn("was $1.50", text)
        self.assertIn("3 models", text)

    def test_json_prices_do_not_contain_float_artifacts(self):
        rows = pulse.normalize_catalog([
            {"id": "vendor/model", "pricing": {"prompt": "0.0000008", "completion": "0.0000016"}}
        ])

        self.assertEqual(rows[0]["input_per_million"], 0.8)
        self.assertEqual(rows[0]["output_per_million"], 1.6)

    def test_catalog_rejects_unexpected_success_shape_clearly(self):
        provider = {"provider": "nous", "base_url": "https://example.test/v1", "key": "hidden"}

        with patch.object(pulse, "_http_json", return_value=(200, {"data": {}}, "")):
            rows, error = pulse.get_model_catalog(provider)

        self.assertEqual(rows, [])
        self.assertEqual(error, "unexpected response shape")


class ProbeTests(unittest.TestCase):
    def test_terminal_output_strips_provider_control_characters(self):
        results = [{
            "provider": "provider\x1b[2J",
            "model": "model\x1b[2J",
            "state": "error",
            "detail": "detail\x1b[2J",
        }]

        output, _ = pulse.render(results, {"provider\x1b[2J": "quota\x1b[2J"})

        self.assertNotIn("\x1b[2J", output)
        self.assertIn("provider", output)
        self.assertIn("model", output)

    def test_github_cli_token_is_not_used_for_copilot(self):
        with tempfile.TemporaryDirectory() as home:
            auth_file = Path(home) / "auth.json"
            auth_file.write_text(
                '{"credential_pool":{"copilot":[{"base_url":"https://api.githubcopilot.com"}]}}'
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(pulse, "AUTH_JSON", auth_file),
                patch.object(pulse, "_DOTENV", {}),
                patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, "generic-github-token\n", ""),
                ) as gh_token,
            ):
                providers = pulse.discover()

        self.assertIsNone(providers[0]["key"])
        gh_token.assert_not_called()

    def test_generic_github_token_is_not_used_for_copilot(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(pulse, "_DOTENV", {"GITHUB_TOKEN": "generic-github-token"}),
        ):
            providers = pulse.discover()

        self.assertNotIn("copilot", [provider["provider"] for provider in providers])

    def test_remote_provider_credentials_require_https(self):
        with patch.object(pulse.urllib.request, "build_opener") as build_opener:
            build_opener.return_value.open.side_effect = AssertionError("network attempted")

            status, data, error = pulse._http_json(
                "http://provider.example.test/models",
                {"Authorization": "Bearer fake-token"},
                None,
                2,
            )

        self.assertEqual((status, data), (0, None))
        self.assertEqual(error, "refusing to send credentials over a non-HTTPS URL")
        build_opener.assert_not_called()

    def test_authorization_does_not_cross_redirect_origins(self):
        received = []

        class SinkHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format, *args):
                pass

        sink = HTTPServer(("127.0.0.1", 0), SinkHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/sink")
                self.end_headers()

            def log_message(self, format, *args):
                pass

        redirect = HTTPServer(("127.0.0.1", 0), RedirectHandler)
        threads = [threading.Thread(target=server.serve_forever) for server in (sink, redirect)]
        for thread in threads:
            thread.start()
        try:
            status, _, _ = pulse._http_json(
                f"http://127.0.0.1:{redirect.server_port}/start",
                {"Authorization": "Bearer fake-token"},
                None,
                2,
            )
        finally:
            redirect.shutdown()
            sink.shutdown()
            for thread in threads:
                thread.join()
            redirect.server_close()
            sink.server_close()

        self.assertEqual(status, 302)
        self.assertEqual(received, [])

    def test_nous_uses_the_runtime_agent_key(self):
        with tempfile.TemporaryDirectory() as home:
            auth_file = Path(home) / "auth.json"
            auth_file.write_text(
                '{"credential_pool":{"nous":[{"base_url":"https://portal.example.test",'
                '"inference_base_url":"https://inference.example.test/v1",'
                '"access_token":"portal-token","agent_key":"runtime-token"}]}}'
            )

            with patch.object(pulse, "AUTH_JSON", auth_file):
                providers = pulse.discover()

        self.assertEqual(providers[0]["key"], "runtime-token")
        self.assertEqual(providers[0]["base_url"], "https://inference.example.test/v1")

    def test_codex_timeout_is_not_reported_as_alive(self):
        provider = {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "key": "fake-token",
        }

        with patch.object(pulse, "_http_json", return_value=(0, None, "timed out")):
            state, detail = pulse.chat_probe(provider, "model-id")

        self.assertEqual(state, "error")
        self.assertEqual(detail, "timed out")


if __name__ == "__main__":
    unittest.main()
