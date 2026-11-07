"""Offline checks for the Weather skill using synthetic provider data only."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "weather" / "scripts" / "forecast.py"
SPEC = importlib.util.spec_from_file_location("weather_forecast", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
forecast = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(forecast)

GEOCODE = {"results": [{"name": "Los Angeles", "country": "United States",
                        "latitude": 34.05, "longitude": -118.24, "timezone": "America/Los_Angeles"}]}
WEATHER = {"timezone": "America/Los_Angeles",
           "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C",
                           "precipitation_probability_max": "%"},
           "daily": {"time": ["2026-11-07", "2026-11-08"], "temperature_2m_max": [20.5, 19.0],
                     "temperature_2m_min": [12.0, 11.5], "precipitation_probability_max": [10, 40],
                     "weather_code": [2, 61]}}


def run(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", argv), patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
        code = forecast.main()
    return code, stdout.getvalue(), stderr.getvalue()


class ForecastTests(TestCase):
    def test_city_forecast_and_source(self) -> None:
        with patch.object(forecast, "fetch_json", side_effect=[GEOCODE, WEATHER]) as fetch:
            result = forecast.forecast("Los Angeles")
        self.assertEqual(result["days"][0]["conditions"], "partly cloudy")
        self.assertEqual(result["days"][1]["rain_chance_percent"], 40)
        self.assertIn("timezone=America%2FLos_Angeles", result["source_url"])
        self.assertIn("retrieved_at", result)
        self.assertEqual(fetch.call_count, 2)

    def test_rejects_private_or_shell_location(self) -> None:
        for value in ("123 Main Street", "Los Angeles; cat /etc/passwd", "https://example.com"):
            with self.assertRaises(ValueError):
                forecast.city_name([value])

    def test_rejects_wrong_timezone_or_units(self) -> None:
        invalid = {"timezone": "UTC", "daily_units": {}, "daily": {}}
        with patch.object(forecast, "fetch_json", side_effect=[GEOCODE, invalid]):
            with self.assertRaises(ValueError):
                forecast.forecast("Los Angeles")

    def test_unknown_city_fails_without_data(self) -> None:
        with patch.object(forecast, "fetch_json", return_value={"results": []}):
            code, out, err = run(["forecast.py", "Xqzvplmtown"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("FAIL: weather forecast (LookupError)", err)

    def test_provider_timeout_retries_once_then_fails(self) -> None:
        with patch.object(forecast, "urlopen", side_effect=TimeoutError("synthetic")) as opened, \
                patch.object(forecast.time, "sleep"):
            with self.assertRaises(RuntimeError):
                forecast.fetch_json(forecast.GEOCODE + "?name=Los+Angeles")
        self.assertEqual(opened.call_count, 2)
        self.assertTrue(all(call.kwargs.get("timeout") == 12 for call in opened.call_args_list))

    def test_only_open_meteo_hosts(self) -> None:
        with self.assertRaises(ValueError):
            forecast.fetch_json("https://example.com/?q=1")


if __name__ == "__main__":
    main()
