#!/usr/bin/env python3
"""Original keyless city forecast: Open-Meteo first, wttr.in and wttr.is as fallbacks.

Open-Meteo geocodes the city and gives the forecast. When its forecast does not
answer (its host is intermittently silent from some cloud networks), the same
coordinates are sent to wttr.in, then to its mirror wttr.is. When geocoding itself
fails, wttr.in and wttr.is are asked by city name and the location they resolved
is reported. Every response is validated; the output shape is the same for all
sources. The worst case stays below 45 seconds.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sys
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
FALLBACKS = ("https://wttr.in/", "https://wttr.is/")
USER_AGENT = "hermes-weather-skill/0.3 (+https://github.com/jlcg-git/hermes-weather-skill)"
# (attempts, seconds per attempt): geocoding 2 x 8, each forecast source 1 x 8.
GEOCODE_TRIES = (2, 8)
FORECAST_TRIES = (1, 8)
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
# Provider text is untrusted: a condition is only shown when it is a short plain phrase.
CONDITION_TEXT = re.compile(r"[A-Za-z][A-Za-z ,'()-]{0,59}")


def fahrenheit(celsius: float) -> float:
    return round(celsius * 9 / 5 + 32, 1)


def city_name(parts: list[str]) -> str:
    value = " ".join(parts).strip()
    if not 2 <= len(value) <= 80 or not re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]*", value):
        raise ValueError("city must contain only letters, spaces and ordinary punctuation")
    return value


def fetch_json(url: str, tries: tuple[int, int] = GEOCODE_TRIES) -> dict:
    if not url.startswith((GEOCODE + "?", FORECAST + "?", *FALLBACKS)):
        raise ValueError("unapproved weather host")
    attempts, seconds = tries
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=seconds) as response:
                if response.status != 200:
                    raise RuntimeError("weather provider HTTP failure")
                payload = response.read(400_001)
            if len(payload) > 400_000:
                raise ValueError("weather response too large")
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("weather response is not an object")
            return data
        except (OSError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4)
    raise RuntimeError("weather provider unavailable") from last_error


def geocode(city: str) -> dict:
    url = GEOCODE + "?" + urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
    locations = fetch_json(url, GEOCODE_TRIES).get("results")
    if not isinstance(locations, list) or not locations:
        raise LookupError("city not found")
    place = locations[0]
    lat, lon, zone = place.get("latitude"), place.get("longitude"), place.get("timezone")
    if (not isinstance(lat, (int, float)) or isinstance(lat, bool) or not -90 <= lat <= 90 or
            not isinstance(lon, (int, float)) or isinstance(lon, bool) or not -180 <= lon <= 180 or
            not isinstance(zone, str)):
        raise ValueError("invalid geocoding result")
    ZoneInfo(zone)
    return {"lat": lat, "lon": lon, "zone": zone,
            "location": f"{place.get('name', city)}, {place.get('country', '')}".strip(", ")}


def day_entry(date: object, high: object, low: object, chance: object, conditions: str) -> dict:
    if (not isinstance(date, str) or not isinstance(high, (int, float)) or isinstance(high, bool) or
            not isinstance(low, (int, float)) or isinstance(low, bool) or
            not isinstance(chance, (int, float)) or not 0 <= chance <= 100 or not -90 <= low <= high <= 60):
        raise ValueError("invalid forecast field")
    datetime.strptime(date, "%Y-%m-%d")
    return {"date": date, "high_c": high, "low_c": low, "high_f": fahrenheit(high), "low_f": fahrenheit(low),
            "rain_chance_percent": chance, "conditions": conditions}


def open_meteo(place: dict) -> tuple[list[dict], str]:
    parameters = {"latitude": place["lat"], "longitude": place["lon"],
                  "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                  "timezone": place["zone"], "forecast_days": 2,
                  "temperature_unit": "celsius", "precipitation_unit": "mm"}
    source_url = FORECAST + "?" + urlencode(parameters)
    data = fetch_json(source_url, FORECAST_TRIES)
    daily = data.get("daily", {})
    units = data.get("daily_units", {})
    if (data.get("timezone") != place["zone"] or units.get("temperature_2m_max") != "°C" or
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
        if not isinstance(code, int):
            raise ValueError("invalid forecast field")
        days.append(day_entry(date, high, low, chance, WEATHER_CODES.get(code, f"weather code {code}")))
    return days, source_url


def number(value: object) -> float:
    """wttr.in sends numbers as strings."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("invalid number")
    return float(value)


def wttr(base: str, where: str) -> tuple[list[dict], str, str]:
    source_url = base + where + "?format=j1"
    data = fetch_json(source_url, FORECAST_TRIES)
    forecast_days = data.get("weather")
    if not isinstance(forecast_days, list) or len(forecast_days) < 2:
        raise ValueError("weather daily array mismatch")
    days = []
    for day in forecast_days[:2]:
        hourly = day.get("hourly") if isinstance(day, dict) else None
        if not isinstance(hourly, list) or not hourly:
            raise ValueError("invalid forecast field")
        chance = max(number(slot.get("chanceofrain", 0)) for slot in hourly if isinstance(slot, dict))
        midday = hourly[len(hourly) // 2] if isinstance(hourly[len(hourly) // 2], dict) else {}
        text = " ".join(str(((midday.get("weatherDesc") or [{}])[0] or {}).get("value", "")).split()).lower()
        conditions = text if CONDITION_TEXT.fullmatch(text) else "conditions unavailable"
        days.append(day_entry(day.get("date"), number(day.get("maxtempC")), number(day.get("mintempC")),
                              chance, conditions))
    area = ((data.get("nearest_area") or [{}])[0] or {})
    names = [((area.get(key) or [{}])[0] or {}).get("value", "") for key in ("areaName", "country")]
    resolved = ", ".join(n for n in (" ".join(str(x).split()) for x in names) if CONDITION_TEXT.fullmatch(n))
    return days, source_url, resolved


def forecast(city: str) -> dict:
    # Any provider failure, including an unexpected response shape, moves on to the next source.
    # An unknown city is an answer, not a failure: wttr.in would guess another place.
    try:
        place = geocode(city)
    except LookupError:
        raise
    except Exception:
        place = None
    result = None
    if place is not None:
        try:
            days, source_url = open_meteo(place)
            result = {"location": place["location"], "timezone": place["zone"], "days": days,
                      "source": "Open-Meteo", "source_url": source_url}
        except Exception:
            result = None
    if result is None:
        # Coordinates when geocoding worked (4 decimals); otherwise the city name.
        where = f"{place['lat']:.4f},{place['lon']:.4f}" if place else quote(city)
        last_error: Exception | None = None
        for base in FALLBACKS:
            try:
                days, source_url, resolved = wttr(base, where)
            except Exception as exc:
                last_error = exc
                continue
            result = {"location": place["location"] if place else (resolved or city),
                      "timezone": place["zone"] if place else None, "days": days,
                      "source": base.split("/")[2], "source_url": source_url,
                      "primary_source_unavailable": True}
            if place is None:
                result["location_resolved_by_provider"] = True
            break
        if result is None:
            raise RuntimeError("weather provider unavailable") from last_error
    result["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    return result


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
