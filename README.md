# Hermes Weather skill

A small, original [Hermes Agent](https://hermes-agent.nousresearch.com/) skill that returns a two-day, city-level forecast in Fahrenheit and Celsius from [Open-Meteo](https://open-meteo.com/), with [wttr.in](https://github.com/chubin/wttr.in) and its mirror wttr.is as fallbacks. It needs no account, API key or secret. It uses only the Python standard library and validates its input, the provider hosts, units, timezone and response shape.

This repository is a Hermes **skill tap**: Hermes reads skills from its `skills/` directory.

```
skills/weather/SKILL.md            # skill instructions and metadata
skills/weather/scripts/forecast.py # forecast script used by the skill
tests/test_forecast.py             # offline tests with synthetic provider data
```

## Install with the Hermes skill-tap flow

Requires a Hermes Agent release with skill-tap support (developed against v0.21.5):

```bash
hermes skills tap add jlcg-git/hermes-weather-skill
hermes skills search weather
hermes skills install jlcg-git/hermes-weather-skill/skills/weather
hermes skills list
```

Hermes downloads the whole `skills/weather` directory at a pinned commit and runs its own skill scan before installing.

## Use

Ask Hermes, for example: *"Use the weather skill for Los Angeles and give me the two-day forecast with the source."* The skill runs:

```bash
python3 "${HERMES_SKILL_DIR}/scripts/forecast.py" Los Angeles
```

The script prints JSON with the location, timezone, two daily records (low/high in °C and in °F converted locally, precipitation probability, conditions), `source` (the service that answered), `source_url` and `retrieved_at`. On any failure it prints a `FAIL:` line to stderr, exits with status 1 and returns no forecast data.

Input is limited to a city-level name of 2–80 letters, spaces and ordinary punctuation. Addresses, coordinates, URLs and shell symbols are rejected.

Sources and timing:
- `geocoding-api.open-meteo.com` turns the city into coordinates and a timezone (two 8-second attempts).
- `api.open-meteo.com` gives the forecast (one 8-second attempt).
- If that forecast does not answer or fails validation, `wttr.in` and then `wttr.is` are asked for the same coordinates (one 8-second attempt each). Open-Meteo's forecast host can be silent from some cloud networks while it answers others, which is why the fallbacks exist.
- If geocoding does not answer, the two fallbacks are asked by city name and the output sets `location_resolved_by_provider`. An unknown city is reported as unknown, not guessed.

No other host can be contacted, and the whole call stays under 45 seconds.

## Test

```bash
python3 -m unittest discover -s tests -v
```

Tests require Python 3.10 or later and make no network calls.

## Data and license

Code: [MIT](LICENSE). Forecast data comes from Open-Meteo, subject to its [terms of use](https://open-meteo.com/en/terms), or on fallback from wttr.in; attribute the `source` you display.
