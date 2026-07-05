import json
import tempfile
import unittest
from pathlib import Path

from src.config import ConfigError, load_config
from src.data.providers import BinancePublicDataProvider


class ConfigAndSecurityTests(unittest.TestCase):
    def test_default_config_is_locked(self):
        config = load_config("config.yaml")
        self.assertIs(config.security["live_trading_enabled"], False)
        self.assertIs(config.security["broker_connected"], False)
        self.assertIs(config.security["orders_sent"], False)
        self.assertIs(config.security["paper_internal_enabled"], False)
        self.assertIs(config.security["paper_broker_enabled"], False)

    def test_unsafe_config_is_rejected(self):
        unsafe = {
            "security": {
                "live_trading_enabled": True,
                "broker_connected": False,
                "orders_sent": False,
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.yaml"
            path.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_public_provider_exposes_no_broker_actions(self):
        provider = BinancePublicDataProvider()
        public_names = {name.lower() for name in dir(provider) if not name.startswith("_")}
        forbidden = {"send_order", "submit_order", "place_order", "connect_broker"}
        self.assertTrue(forbidden.isdisjoint(public_names))


if __name__ == "__main__":
    unittest.main()
