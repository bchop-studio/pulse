import importlib.machinery
import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


def load_pulse():
    loader = importlib.machinery.SourceFileLoader("pulse_module", "./pulse")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("could not load pulse")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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


if __name__ == "__main__":
    unittest.main()
