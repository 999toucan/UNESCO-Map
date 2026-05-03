# UNESCO Heritage Map

Interactive Leaflet map of UNESCO World Heritage Sites with category filters and a timeline based on estimated construction/origin dates.

The frontend reads:

```text
convert/sites.geojson
```

## Main Workflow

Use three separate scripts:

| Step | Script | Output |
| --- | --- | --- |
| 1. LLM extraction | `convert/extract_construction_history.py` | `convert/llm_cache_gemini.json`, `convert/llm_cache_gpt.json` |
| 2. Human label prep | `convert/human_label_disagreements.py` | `convert/llm_disagreements.json`, `convert/disagreements.csv` |
| 3. Evaluation/dataset | `convert/evaluate_construction_dates.py` | `convert/eval_score.json`, `convert/fine_tune_dataset.jsonl` |

The idea is simple:

```text
Run Gemini/GPT extraction -> compare disagreements -> label CSV by hand -> score/build JSONL
```

Prompting comes first. Human-labeled disagreements become the benchmark. Fine-tuning is optional later.

## Quick Commands

Run both extraction models:

```bash
python3 convert/extract_construction_history.py --both
```

Create the human-label CSV:

```bash
python3 convert/human_label_disagreements.py
```

Edit this file by hand:

```text
convert/disagreements.csv
```

Fill `human_choice` with one of:

```text
gemini
gpt
tie
neither
```

If you know the exact correct date, also fill:

```text
correct_start, correct_end, correct_BC_AD, correct_display
```

Then score and build the labeled JSONL:

```bash
python3 convert/evaluate_construction_dates.py --score --build-dataset
```

Final useful outputs:

```text
convert/eval_score.json
convert/fine_tune_dataset.jsonl
```

## Extraction

Gemini extraction:

```bash
python3 convert/extract_construction_history.py --gemini
```

GPT extraction:

```bash
python3 convert/extract_construction_history.py --gpt
```

Both:

```bash
python3 convert/extract_construction_history.py --both
```

Small test batch:

```bash
LLM_BATCH_LIMIT=10 python3 convert/extract_construction_history.py --both
```

Force re-run API calls even when cache exists:

```bash
python3 convert/extract_construction_history.py --both --force
```

Local parser only, no API calls:

```bash
NO_LLM=1 python3 convert/extract_construction_history.py --no-llm
```

Extraction caches are resumable and saved atomically after each row.

Cache behavior:

- cached successful rows are reused automatically
- pandas builds the filter table before API calls
- duplicate rows are handled manually by cache key before API calls
- `heritage_category=Natural` rows are handled manually without LLM calls and cached as `date: null`
- `LLM_BATCH_LIMIT` max batch API calls
- if `LLM_BATCH_LIMIT` is larger than the filtered row count, only the filtered row count is sent
- if every row is already cached, extraction makes no API calls
- use `--force` or `FORCE_LLM=1` to ignore cache and call APIs again

## Human Labels

Prepare disagreements:

```bash
python3 convert/human_label_disagreements.py
```

This compares the Gemini and GPT caches. A row is included when:

- `llm_built` differs
- normalized `date` differs
- one model has `date: null` and the other does not

It writes:

```text
convert/llm_disagreements.json
convert/disagreements.csv
```

The CSV is for humans. Re-running the script preserves existing label columns, so AI output does not overwrite your labels.

This step also uses pandas. It compares cache rows, preserves existing human labels, and writes the CSV without calling any model.

## Evaluation

Score labels:

```bash
python3 convert/evaluate_construction_dates.py --score
```

Build optional future fine-tune dataset:

```bash
python3 convert/evaluate_construction_dates.py --build-dataset
```

Do both:

```bash
python3 convert/evaluate_construction_dates.py --score --build-dataset
```

`--score` reads `convert/disagreements.csv` and writes:

```text
convert/eval_score.json
```

`--build-dataset` reads labeled rows and writes:

```text
convert/fine_tune_dataset.jsonl
```

Only labeled rows are included. Unlabeled rows are skipped.

Scoring and dataset building use pandas to read/filter labeled rows. They do not call an LLM.

## Models

Extraction uses lighter models:

```env
GEMINI_MODEL=gemini-2.5-flash-lite
OPENAI_MODEL=gpt-4o-mini
```

Evaluation metadata uses a stronger model config:

```env
EVAL_MODEL=gpt-4.1
```

Human labels are still the ground truth.

## Result Shape

Each cached LLM extraction result is normalized to:

```json
{
  "provider": "gemini",
  "site_id": 123,
  "site_name": "Example Site",
  "llm_built": "17th century",
  "llm_renovated": null,
  "evidence": "short quote from the source text",
  "date": {
    "start_date": 1600,
    "end_date": 1700,
    "BC_AD": "AD",
    "display": "1600-1700 AD",
    "timeline_start": 1600,
    "timeline_end": 1700
  },
  "confidence": "high",
  "error": null,
  "tokens_used": {
    "input": 1000,
    "output": 120,
    "total": 1120
  },
  "latency_ms": 900,
  "cost_estimate": null
}
```

Rules:

- `null`, `None`, `unknown`, and empty values become `date: null`
- Natural heritage sites are not sent to extraction models
- missing dates are not guessed
- `A long time ago` is only for explicit million-year cases
- malformed LLM dates are validated and may fall back to the local parser

## Environment

Create `.env` from `.env.example` and fill your keys:

```bash
cp .env.example .env
```

Important variables:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required for `--gemini` or `--both` |
| `OPENAI_API_KEY` | Required for `--gpt` or `--both` |
| `GEMINI_MODEL` | Gemini extraction model |
| `OPENAI_MODEL` | OpenAI extraction model |
| `EVAL_MODEL` | Stronger evaluation model metadata |
| `GEOJSON_INPUT` | Input GeoJSON, usually `convert/sites.geojson` |
| `GEOJSON_OUTPUT` | Output GeoJSON, usually `convert/sites.geojson` |
| `GEMINI_CACHE_PATH` | Gemini cache path |
| `GPT_CACHE_PATH` | GPT cache path |
| `LLM_BATCH_LIMIT` | Optional number of new API rows to process |
| `LLM_REQUEST_DELAY_SECONDS` | Delay between API calls |
| `FORCE_LLM` | Set `1` to ignore cache and call APIs again |

Python dependency for extraction filtering:

```bash
python3 -m pip install pandas
```

Optional cost estimate variables:

```env
GEMINI_INPUT_COST_PER_1M=
GEMINI_OUTPUT_COST_PER_1M=
GPT_INPUT_COST_PER_1M=
GPT_OUTPUT_COST_PER_1M=
```

If prices are blank, `cost_estimate` is `null`.

## Frontend

Start a local server from the project root:

```bash
python3 -m http.server 8000
```

Open:

```text
http://localhost:8000/index/
```

Timeline controls:

- `All` clears the timeline filter and shows all category-matching sites, including `date: null`
- `Unknown` keeps `date: null` sites visible while a specific timeline year is selected

## Help

Each script has command help:

```bash
python3 convert/extract_construction_history.py --help
python3 convert/human_label_disagreements.py --help
python3 convert/evaluate_construction_dates.py --help
```
