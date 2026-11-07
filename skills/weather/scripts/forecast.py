#!/usr/bin/env python3
"""Original keyless Open-Meteo city forecast with strict input and response checks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
WEATHER_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle",
    53: "moderate drizzle", 55: "dense drizzle", 61: "slight rain",
    63: "moderate rain", 65: "heavy rain", 71: "slight snow",
    73: "moderate snow", 75: "heavy snow", 80: "slight rain showers",
    81: "moderate rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def city_name(parts: list[str]) -> str:
    value = " ".join(parts).strip()
    if not 2 <= len(value) <= 80 or not re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]*", value):
        raise ValueError("city must contain only letters, spaces and ordinary punctuation")
    return value


def fetch_json(url: str) -> dict:
    if not url.startswith((GEOCODE + "?", FORECAST + "?")):
        raise ValueError("unapproved weather host")
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={"User-Agent": "Assignment3-Weather/0.1"}),
                         timeout=12) as response:
                if response.status != 200:
                    raise RuntimeError("weather provider HTTP failure")
                payload = response.read(200_001)
            if len(payload) > 200_000:
                raise ValueError("weather response too large")
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("weather response is not an object")
            return data
        except (OSError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.4)
    raise RuntimeError("weather provider unavailable") from last_error


def forecast(city: str) -> dict:
    geo_url = GEOCODE + "?" + urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
    locations = fetch_json(geo_url).get("results")
    if not isinstance(locations, list) or not locations:
        raise LookupError("city not found")
    place = locations[0]
    lat, lon, zone = place.get("latitude"), place.get("longitude"), place.get("timezone")
    if (not isinstance(lat, (int, float)) or isinstance(lat, bool) or not -90 <= lat <= 90 or
            not isinstance(lon, (int, float)) or isinstance(lon, bool) or not -180 <= lon <= 180 or
            not isinstance(zone, str)):
        raise ValueError("invalid geocoding result")
    ZoneInfo(zone)
    parameters = {"latitude": lat, "longitude": lon,
                  "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                  "timezone": zone, "forecast_days": 2,
                  "temperature_unit": "celsius", "precipitation_unit": "mm"}
    source_url = FORECAST + "?" + urlencode(parameters)
    data = fetch_json(source_url)
    daily = data.get("daily", {})
    units = data.get("daily_units", {})
    if (data.get("timezone") != zone or units.get("temperature_2m_max") != "°C" or
            units.get("temperature_2m_min") != "°C" or
            units.get("precipitation_probability_max") != "%"):
        raise ValueError("weather units or timezone mismatch")
    fields = ("time", "temperature_2m_max", "temperature_2m_min",
              "precipitation_probability_max", "weather_code")
    values = [daily.get(field) for field in fields]
    if any(not isinstance(value, list) or len(value) != 2 for value in values):
        raise ValueError("weather daily array mismatch")
    days = []
    for date, high, low, chance, code in zip(*values):
        if (not isinstance(date, str) or not isinstance(high, (int, float)) or
                not isinstance(low, (int, float)) or not isinstance(chance, (int, float)) or
                not 0 <= chance <= 100 or not isinstance(code, int)):
            raise ValueError("invalid forecast field")
        datetime.strptime(date, "%Y-%m-%d")
        days.append({"date": date, "high_c": high, "low_c": low,
                     "rain_chance_percent": chance,
                     "conditions": WEATHER_CODES.get(code, f"weather code {code}")})
    return {"location": f"{place.get('name', city)}, {place.get('country', '')}".strip(", "),
            "timezone": zone, "days": days, "source": "Open-Meteo",
            "source_url": source_url, "retrieved_at": datetime.now(timezone.utc).isoformat()}


def main() -> int:
    try:
        city = city_name(sys.argv[1:])
        print(json.dumps(forecast(city), ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"FAIL: weather forecast ({type(exc).__name__}); details withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
