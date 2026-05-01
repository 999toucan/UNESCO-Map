# UNESCO Heritage Map

## Project Overview

This project is an interactive Leaflet map of UNESCO World Heritage Sites. It shows sites as clustered markers, supports category filtering, and includes a timeline slider for exploring sites by estimated construction or origin date.

The frontend reads one GeoJSON file:

```text
convert/sites.geojson
```

Each feature can include:

```json
{
  "construction_history": {
    "llm_built": "17th century",
    "llm_renovated": null,
    "llm_evidence": "short quote from the source text",
    "llm_error": null
  },
  "date": {
    "start_date": 1600,
    "end_date": 1700,
    "BC_AD": "AD",
    "display": "1600-1700 AD",
    "timeline_start": 1600,
    "timeline_end": 1700
  }
}
```

## Data Pipeline

The notebook in `convert/Scripts.ipynb` is used for the earlier data preparation steps, such as building the UNESCO CSV/GeoJSON data and adding image URLs.

The construction-date extraction is handled separately by:

```text
convert/extract_construction_history.py
```

That script:

- loads `convert/sites.geojson`
- sends each site description to Gemini
- stores the raw LLM result in `properties.construction_history`
- stores Gemini's normalized timeline object in `properties.date` when it is valid
- falls back to the local Python parser when Gemini returns a malformed `date`
- can run without Gemini by parsing dates directly from descriptions
- saves progress after each row so interrupted runs can continue
- uses `convert/llm_cache.json` to avoid repeated API calls

## LLM Construction-Date Extraction

The LLM is asked to find the earliest concrete evidence of a site's original creation, construction, opening, establishment, or completion.

It should not use later renovation, restoration, alteration, expansion, heritage listing, reopening, or repair dates as the built date.

Gemini now returns both the raw date text and the frontend-ready date object:

- `construction_history.llm_built`: raw LLM answer, such as `"17th century"`
- `date.display`: Gemini's normalized display text, such as `"1600-1700 AD"`
- `date.timeline_start` and `date.timeline_end`: signed numeric years used by the frontend timeline

Python still validates the returned `date` object before writing it to GeoJSON. If Gemini returns an invalid or incomplete date object, the script falls back to `convert/date_parser.py` and parses `llm_built`. If both fail, `properties.date` is set to `null`.

You can also run without Gemini. In that mode the script parses the full site description locally. This is free and fast, but it does not understand context. It may grab a renovation date, a later historical period, or the wrong century if that appears before the true construction date.

## Date Parsing Rules

Fallback date parsing lives in:

```text
convert/date_parser.py
```

Gemini is asked to return this normalized shape directly, and the Python parser can produce the same shape as a backup:

```json
{
  "start_date": 1600,
  "end_date": 1700,
  "BC_AD": "AD",
  "display": "1600-1700 AD",
  "timeline_start": 1600,
  "timeline_end": 1700
}
```

Examples:

| LLM value | Parsed display |
| --- | --- |
| `"17th century"` | `1600-1700 AD` |
| `"10th century BC"` | `900-1000 BC` |
| `"5th millennium BC"` | `4000-5000 BC` |
| `"1700s"` | `1700-1799 AD` |
| `"ten million years ago"` | `A long time ago` |
| `None`, `null`, or `unknown` | `null` |

Timeline numeric rules:

- AD years are positive.
- BC years are negative for timeline comparison.
- `900-1000 BC` is compared internally as `-1000` to `-900`.
- Date ranges stay visible across the full range.
- Dates older than `50,000 BC`, or anything like “million years ago,” are grouped into `A long time ago`.

You can test the parser without calling Gemini:

```bash
python3 -m convert.extract_construction_history --test-parser
```

## Timeline Behavior

The frontend timeline covers:

```text
A long time ago, then 50,000 BC to 2026 AD
```

The special `A long time ago` bucket is stored as:

```json
{
  "BC_AD": "LONG_AGO",
  "display": "A long time ago",
  "timeline_start": -50001,
  "timeline_end": -50001
}
```

In the UI, that bucket is placed one 1000-year tick before `50,000 BC`, so it stays close to the normal human-history timeline instead of stretching the slider.

When the timeline is cleared, all category-matching markers are shown. When a year is selected, a marker is visible if the selected year is between `date.timeline_start` and `date.timeline_end`.

## Running The Pipeline

Create or update `.env`:

```bash
cp .env.example .env
nano .env
```

Run a small LLM batch:

```bash
LLM_BATCH_LIMIT=10 python3 convert/extract_construction_history.py
```

The same command also works as a module:

```bash
LLM_BATCH_LIMIT=10 python3 -m convert.extract_construction_history
```

Run full enrichment:

```bash
python3 convert/extract_construction_history.py
```

Force reprocess, ignoring existing cache/construction fields:

```bash
FORCE_LLM=1 python3 convert/extract_construction_history.py
```

Re-parse existing LLM results without making Gemini calls:

```bash
NORMALIZE_ONLY=1 python3 convert/extract_construction_history.py
```

Run without LLM calls by parsing descriptions locally:

```bash
NO_LLM=1 python3 -m convert.extract_construction_history
```

Safer no-LLM test run that writes a separate file:

```bash
NO_LLM=1 GEOJSON_OUTPUT=convert/sites.no_llm.geojson python3 -m convert.extract_construction_history
```

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Your Gemini API key. Required for LLM extraction. |
| `GEMINI_MODEL` | Gemini model name. Current default is `gemini-2.5-flash-lite`. |
| `GEOJSON_INPUT` | GeoJSON file to read. Usually `convert/sites.geojson`. |
| `GEOJSON_OUTPUT` | GeoJSON file to write. Usually `convert/sites.geojson`. |
| `LLM_CACHE_PATH` | Cache file for Gemini responses. Usually `convert/llm_cache.json`. |
| `LLM_BATCH_LIMIT` | Optional limit for how many new LLM requests to make in one run. |
| `LLM_REQUEST_DELAY_SECONDS` | Delay between requests to be friendlier to API rate limits. |
| `FORCE_LLM` | Set to `1` to call Gemini again even when cached or existing results are present. |
| `NO_LLM` | Set to `1` to skip Gemini and parse descriptions locally. Faster and free, but less accurate. |

## Frontend Usage

Start a local server from the project root:

```bash
python3 -m http.server 8000
```

Open:

```text
http://localhost:8000/index/
```

Use the category panel to filter Cultural, Natural, or Mixed sites. Use the timeline slider to filter by construction date. Click markers to see site details, the parsed built date, evidence text, and images where available.

## Troubleshooting

If the LLM script says the API key is missing, check `.env`:

```bash
GEMINI_API_KEY=your_key_here
```

If a run is interrupted, run the same command again. The script saves after each row and reuses `LLM_CACHE_PATH`.

If date parsing changes but you do not want to spend API requests, run:

```bash
NORMALIZE_ONLY=1 python3 convert/extract_construction_history.py
```

If the frontend does not load data, make sure the local server is started from the project root, not from inside `index/`.

If cached results look wrong, either edit/remove `convert/llm_cache.json` or run:

```bash
FORCE_LLM=1 python3 convert/extract_construction_history.py
```
