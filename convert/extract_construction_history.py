import json
import os
import hashlib
import re
import sys
import time
import argparse
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .date_parser import format_display, parse_llm_date_text, parser_examples, validate_normalized_date
except ImportError:
    from date_parser import format_display, parse_llm_date_text, parser_examples, validate_normalized_date


PROMPT = """Extract the original construction date for one heritage site.

Return JSON only in this exact shape:
{
  "provider": "__PROVIDER__",
  "site_id": string|number|null,
  "site_name": string,
  "llm_built": string|null,
  "llm_renovated": string|null,
  "evidence": string|null,
  "date": {
    "start_date": number|null,
    "end_date": number|null,
    "BC_AD": "AD"|"BC"|"LONG_AGO",
    "display": string,
    "timeline_start": number,
    "timeline_end": number
  } | null,
  "confidence": "low"|"medium"|"high",
  "error": string|null
}

Rules:
- llm_built is the earliest concrete original creation/construction/opening/completion date.
- Ignore renovation, restoration, listing, designation, reopening, repair, or expansion dates for llm_built.
- Put later renovation/restoration/alteration dates in llm_renovated.
- If no reliable original date exists, set llm_built to null and date to null.
- null, None, unknown, unclear, n/a, or an empty value means date must be null.
- Never convert missing/unknown dates into a fake date.
- Do not guess.
- Use "A long time ago" only for explicit million-year cases.
- AD timeline values are positive.
- BC timeline values are negative.
- For BC ranges, timeline_start must be the older/more negative year and timeline_end must be the newer/less negative year.
- If the date is older than 50,000 BC or says millions of years ago, use:
  {
    "start_date": null,
    "end_date": null,
    "BC_AD": "LONG_AGO",
    "display": "A long time ago",
    "timeline_start": -50001,
    "timeline_end": -50001
  }

Examples:
- "1310" ->
  {
    "start_date": 1310,
    "end_date": 1310,
    "BC_AD": "AD",
    "display": "1310 AD",
    "timeline_start": 1310,
    "timeline_end": 1310
  }
- "17th century" ->
  {
    "start_date": 1600,
    "end_date": 1700,
    "BC_AD": "AD",
    "display": "1600-1700 AD",
    "timeline_start": 1600,
    "timeline_end": 1700
  }
- "1700s" ->
  {
    "start_date": 1700,
    "end_date": 1799,
    "BC_AD": "AD",
    "display": "1700-1799 AD",
    "timeline_start": 1700,
    "timeline_end": 1799
  }
- "10th century BC" ->
  {
    "start_date": 900,
    "end_date": 1000,
    "BC_AD": "BC",
    "display": "900-1000 BC",
    "timeline_start": -1000,
    "timeline_end": -900
  }
- "5th millennium BC" ->
  {
    "start_date": 4000,
    "end_date": 5000,
    "BC_AD": "BC",
    "display": "4000-5000 BC",
    "timeline_start": -5000,
    "timeline_end": -4000
  }
- "ten million years ago" ->
  {
    "start_date": null,
    "end_date": null,
    "BC_AD": "LONG_AGO",
    "display": "A long time ago",
    "timeline_start": -50001,
    "timeline_end": -50001
  }
- null/None/unknown/no date -> "date": null

Site name:
__NAME__

Site id:
__SITE_ID__

Description: __DESCRIPTION__
"""


PROVIDERS = {
    "gemini": {
        "cache": "convert/llm_cache_gemini.json",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.5-flash-lite",
    },
    "gpt": {
        "cache": "convert/llm_cache_gpt.json",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
    },
}

CSV_COLUMNS = [
    "id_no",
    "name_en",
    "short_description_en",
    "gemini_llm_built",
    "gpt_llm_built",
    "gemini_display",
    "gpt_display",
    "gemini_evidence",
    "gpt_evidence",
    "human_choice",
    "correct_start",
    "correct_end",
    "correct_BC_AD",
    "correct_display",
    "notes",
]

UNKNOWN_VALUES = {"", "none", "null", "unknown", "unclear", "n/a", "na", "no date"}


DATE_KEYWORDS = [
    "built", "build", "constructed", "construction", "created", "creation",
    "opened", "completed", "founded", "established", "erected", "dates",
    "century", "bc", "bce", "ad", "renovated", "restored", "altered",
    "expanded", "rebuilt", "reconstructed"
]


def load_env(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def compact_description(description, max_chars=1200):
    description = re.sub(r"\s+", " ", str(description)).strip()
    sentences = re.split(r"(?<=[.!?])\s+", description)

    useful = [
        s for s in sentences
        if any(k in s.lower() for k in DATE_KEYWORDS)
        or re.search(r"\b\d{3,4}\b", s)
    ]

    compact = " ".join(useful) if useful else description
    return compact[:max_chars]


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```json|^```|```$", "", text, flags=re.I).strip()

    decoder = json.JSONDecoder()
    for match in re.finditer(r"{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError(f"No JSON object found: {text[:200]}")


def cache_key(props, description):
    stable_id = str(props.get("id_no") or props.get("name_en") or props.get("name") or "")
    digest = hashlib.sha256(description.encode("utf-8")).hexdigest()[:16]
    return f"{stable_id}:{digest}"


def load_cache(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_suffix(".broken.json")
        path.rename(backup)
        print(f"Cache was broken. Renamed to {backup}", file=sys.stderr)
        return {}


def save_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def provider_prompt(provider, site_id, name, description):
    return (
        PROMPT
        .replace("__PROVIDER__", provider)
        .replace("__SITE_ID__", json.dumps(site_id, ensure_ascii=False))
        .replace("__NAME__", name)
        .replace("__DESCRIPTION__", description)
    )


def token_cost(provider, tokens_used):
    if not tokens_used:
        return None

    prefix = provider.upper()
    input_price = os.environ.get(f"{prefix}_INPUT_COST_PER_1M")
    output_price = os.environ.get(f"{prefix}_OUTPUT_COST_PER_1M")
    if input_price is None or output_price is None:
        return None

    try:
        input_tokens = int(tokens_used.get("input") or 0)
        output_tokens = int(tokens_used.get("output") or 0)
        return round(
            (input_tokens / 1_000_000 * float(input_price))
            + (output_tokens / 1_000_000 * float(output_price)),
            8,
        )
    except (TypeError, ValueError):
        return None


def empty_result(provider, site_id, name, error=None, tokens_used=None, latency_ms=None):
    return {
        "provider": provider,
        "site_id": site_id,
        "site_name": name,
        "llm_built": None,
        "llm_renovated": None,
        "evidence": None,
        "date": None,
        "confidence": "low",
        "error": error,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "cost_estimate": token_cost(provider, tokens_used),
    }


def is_unknown(value):
    if value is None:
        return True
    return str(value).strip().lower() in UNKNOWN_VALUES


def clean_text(value):
    if is_unknown(value):
        return None
    return str(value).strip()


def clean_confidence(value):
    value = str(value or "").strip().lower()
    return value if value in {"low", "medium", "high"} else "low"


def normalize_llm_result(provider, site_id, name, result, tokens_used=None, latency_ms=None):
    if not isinstance(result, dict):
        return empty_result(provider, site_id, name, "LLM_RESULT_NOT_OBJECT", tokens_used, latency_ms)

    llm_built = clean_text(result.get("llm_built"))
    llm_renovated = clean_text(result.get("llm_renovated"))
    evidence = clean_text(result.get("evidence") or result.get("llm_evidence"))
    error = clean_text(result.get("error") or result.get("llm_error"))

    date = None
    if llm_built is not None:
        date = validate_normalized_date(result.get("date"))
        if not date:
            date = parse_llm_date_text(llm_built)

    return {
        "provider": provider,
        "site_id": site_id,
        "site_name": name,
        "llm_built": llm_built,
        "llm_renovated": llm_renovated,
        "evidence": evidence,
        "date": date,
        "confidence": clean_confidence(result.get("confidence")),
        "error": error,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "cost_estimate": token_cost(provider, tokens_used),
    }


def call_gemini(api_key, model, site_id, name, description):
    prompt = provider_prompt("gemini", site_id, name, description)

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "maxOutputTokens": 384,
        },
    }

    data = json.dumps(body).encode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    for attempt in range(5):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            started = time.perf_counter()
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = json.loads(res.read().decode("utf-8"))
            latency_ms = int((time.perf_counter() - started) * 1000)

            parts = payload["candidates"][0]["content"]["parts"]
            raw = extract_json("".join(part.get("text", "") for part in parts))
            usage = payload.get("usageMetadata", {})
            tokens_used = {
                "input": usage.get("promptTokenCount"),
                "output": usage.get("candidatesTokenCount"),
                "total": usage.get("totalTokenCount"),
            }
            return normalize_llm_result("gemini", site_id, name, raw, tokens_used, latency_ms)

        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 4:
                raise
            wait = min(60, 2 ** attempt)
            print(f"Retrying after HTTP {exc.code}, wait {wait}s", file=sys.stderr)
            time.sleep(wait)


def call_gpt(api_key, model, site_id, name, description):
    prompt = provider_prompt("gpt", site_id, name, description)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": 384,
    }
    data = json.dumps(body).encode("utf-8")
    url = "https://api.openai.com/v1/chat/completions"

    for attempt in range(5):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            started = time.perf_counter()
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = json.loads(res.read().decode("utf-8"))
            latency_ms = int((time.perf_counter() - started) * 1000)

            content = payload["choices"][0]["message"]["content"]
            raw = extract_json(content)
            usage = payload.get("usage", {})
            tokens_used = {
                "input": usage.get("prompt_tokens"),
                "output": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            }
            return normalize_llm_result("gpt", site_id, name, raw, tokens_used, latency_ms)

        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 4:
                raise
            wait = min(60, 2 ** attempt)
            print(f"Retrying after HTTP {exc.code}, wait {wait}s", file=sys.stderr)
            time.sleep(wait)


def call_provider(provider, api_key, model, site_id, name, description):
    if provider == "gemini":
        return call_gemini(api_key, model, site_id, name, description)
    if provider == "gpt":
        return call_gpt(api_key, model, site_id, name, description)
    raise ValueError(f"Unknown provider: {provider}")


def normalized_date_from_llm(value):
    return parse_llm_date_text(value)


def date_from_result(result):
    gemini_date = validate_normalized_date(result.get("date"))
    if gemini_date:
        return gemini_date

    return normalized_date_from_llm(result.get("llm_built"))


def result_from_description(description):
    date = parse_llm_date_text(description)
    if not date:
        return {
            "llm_built": None,
            "llm_renovated": None,
            "evidence": None,
            "error": "NO_LLM_DESCRIPTION_PARSE: no date found",
            "date": None,
        }

    return {
        "llm_built": date["display"],
        "llm_renovated": None,
        "evidence": "Parsed locally from description; may be wrong without LLM context.",
        "error": "NO_LLM_DESCRIPTION_PARSE",
        "date": date,
    }


def run_parser_examples():
    for example, parsed in parser_examples().items():
        print(f"{example}: {parsed}")


def enrich_feature(feature, result):
    props = feature.setdefault("properties", {})

    construction = {
        "llm_built": result.get("llm_built"),
        "llm_renovated": result.get("llm_renovated"),
        "llm_evidence": result.get("evidence") or result.get("llm_evidence"),
        "llm_error": result.get("error") or result.get("llm_error"),
    }

    props["construction_history"] = construction

    props["date"] = date_from_result(result)


def feature_lookup(data):
    lookup = {}
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        raw_description = props.get("short_description_en") or ""
        description = compact_description(raw_description)
        key = cache_key(props, description)
        lookup[key] = (feature, props, raw_description)
    return lookup


def date_signature(result):
    date = validate_normalized_date((result or {}).get("date"))
    if not date:
        return None
    return (
        date.get("start_date"),
        date.get("end_date"),
        date.get("BC_AD"),
        date.get("display"),
        date.get("timeline_start"),
        date.get("timeline_end"),
    )


def has_disagreement(gemini_result, gpt_result):
    gemini_built = (gemini_result or {}).get("llm_built")
    gpt_built = (gpt_result or {}).get("llm_built")
    gemini_date = date_signature(gemini_result)
    gpt_date = date_signature(gpt_result)
    return gemini_built != gpt_built or gemini_date != gpt_date or ((gemini_date is None) != (gpt_date is None))


def read_existing_labels(csv_path):
    pd = require_pandas()
    if not csv_path.exists():
        return {}
    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if "id_no" not in frame.columns:
        return {}
    return frame.set_index("id_no", drop=False).to_dict(orient="index")


def write_disagreement_outputs(root, data, gemini_cache, gpt_cache):
    pd = require_pandas()
    json_path = root / "convert/llm_disagreements.json"
    csv_path = root / "convert/disagreements.csv"
    existing_labels = read_existing_labels(csv_path)
    lookup = feature_lookup(data)
    rows = []
    disagreement_json = []

    for key in sorted(set(gemini_cache) & set(gpt_cache)):
        gemini_result = gemini_cache.get(key) or {}
        gpt_result = gpt_cache.get(key) or {}
        if not has_disagreement(gemini_result, gpt_result):
            continue

        feature, props, raw_description = lookup.get(key, ({}, {}, ""))
        site_id = props.get("id_no") or gemini_result.get("site_id") or gpt_result.get("site_id")
        site_id_key = str(site_id or "")
        gemini_date = validate_normalized_date(gemini_result.get("date"))
        gpt_date = validate_normalized_date(gpt_result.get("date"))
        previous = existing_labels.get(site_id_key, {})

        row = {
            "id_no": site_id,
            "name_en": props.get("name_en") or gemini_result.get("site_name") or gpt_result.get("site_name") or "",
            "short_description_en": raw_description or props.get("short_description_en") or "",
            "gemini_llm_built": gemini_result.get("llm_built"),
            "gpt_llm_built": gpt_result.get("llm_built"),
            "gemini_display": gemini_date.get("display") if gemini_date else None,
            "gpt_display": gpt_date.get("display") if gpt_date else None,
            "gemini_evidence": gemini_result.get("evidence"),
            "gpt_evidence": gpt_result.get("evidence"),
            "human_choice": previous.get("human_choice", ""),
            "correct_start": previous.get("correct_start", ""),
            "correct_end": previous.get("correct_end", ""),
            "correct_BC_AD": previous.get("correct_BC_AD", ""),
            "correct_display": previous.get("correct_display", ""),
            "notes": previous.get("notes", ""),
        }
        rows.append(row)
        disagreement_json.append({
            "id_no": site_id,
            "name_en": row["name_en"],
            "short_description_en": row["short_description_en"],
            "gemini": gemini_result,
            "gpt": gpt_result,
        })

    save_json_atomic(json_path, disagreement_json)
    temp_path = csv_path.with_name(f"{csv_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=CSV_COLUMNS).to_csv(temp_path, index=False)
    temp_path.replace(csv_path)

    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Disagreements: {len(rows)}")


def parse_correct_date(row):
    if not (str(row.get("correct_start") or "").strip() and str(row.get("correct_end") or "").strip() and str(row.get("correct_BC_AD") or "").strip()):
        return None
    try:
        start = int(float(str(row.get("correct_start")).strip()))
        end = int(float(str(row.get("correct_end")).strip()))
    except ValueError:
        return None
    era = str(row.get("correct_BC_AD") or "").strip().upper()
    if era not in {"AD", "BC", "LONG_AGO"}:
        return None
    display = str(row.get("correct_display") or "").strip() or format_display(start, end, era)
    return validate_normalized_date(build_date_from_parts(start, end, era, display))


def build_date_from_parts(start, end, era, display):
    if era == "LONG_AGO":
        return {
            "start_date": None,
            "end_date": None,
            "BC_AD": "LONG_AGO",
            "display": "A long time ago",
            "timeline_start": -50001,
            "timeline_end": -50001,
        }
    timeline_start = min(start, end)
    timeline_end = max(start, end)
    if era == "BC":
        timeline_start = -max(start, end)
        timeline_end = -min(start, end)
    return {
        "start_date": start,
        "end_date": end,
        "BC_AD": era,
        "display": display,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
    }


def row_date(row, provider):
    display = str(row.get(f"{provider}_display") or "").strip()
    if not display:
        return None
    if display.lower() == "a long time ago":
        return build_date_from_parts(None, None, "LONG_AGO", display)
    return parse_llm_date_text(display)


def matches_ground_truth(row, provider, correct_date):
    if correct_date:
        provider_date = row_date(row, provider)
        if not provider_date:
            return False
        return (
            provider_date.get("start_date") == correct_date.get("start_date")
            and provider_date.get("end_date") == correct_date.get("end_date")
            and provider_date.get("BC_AD") == correct_date.get("BC_AD")
        )
    choice = str(row.get("human_choice") or "").strip().lower()
    return choice == provider or choice == "tie"


def score_disagreements(root):
    pd = require_pandas()
    csv_path = root / "convert/disagreements.csv"
    if not csv_path.exists():
        raise SystemExit("Run convert/human_label_disagreements.py first, then label convert/disagreements.csv.")

    counts = {
        "gemini_wins": 0,
        "gpt_wins": 0,
        "ties": 0,
        "neither": 0,
        "labeled_count": 0,
        "gemini_correct": 0,
        "gpt_correct": 0,
    }

    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if "human_choice" not in frame.columns:
        frame["human_choice"] = ""

    for row in frame.to_dict(orient="records"):
        choice = str(row.get("human_choice") or "").strip().lower()
        correct_date = parse_correct_date(row)
        labeled = choice in {"gemini", "gpt", "tie", "neither"} or correct_date is not None
        if not labeled:
            continue

        counts["labeled_count"] += 1
        if choice == "gemini":
            counts["gemini_wins"] += 1
        elif choice == "gpt":
            counts["gpt_wins"] += 1
        elif choice == "tie":
            counts["ties"] += 1
        elif choice == "neither":
            counts["neither"] += 1

        if matches_ground_truth(row, "gemini", correct_date):
            counts["gemini_correct"] += 1
        if matches_ground_truth(row, "gpt", correct_date):
            counts["gpt_correct"] += 1

    labeled_count = counts["labeled_count"]
    score = {
        "evaluation_model": evaluation_model(),
        "gemini_wins": counts["gemini_wins"],
        "gpt_wins": counts["gpt_wins"],
        "ties": counts["ties"],
        "neither": counts["neither"],
        "labeled_count": labeled_count,
        "gemini_accuracy": round(counts["gemini_correct"] / labeled_count, 4) if labeled_count else None,
        "gpt_accuracy": round(counts["gpt_correct"] / labeled_count, 4) if labeled_count else None,
    }
    save_json_atomic(root / "convert/eval_score.json", score)
    print(json.dumps(score, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run LLM extraction for UNESCO construction dates.",
        epilog=(
            "Typical extraction commands:\n"
            "  python3 convert/extract_construction_history.py --both\n"
            "  python3 convert/extract_construction_history.py --gemini\n"
            "  python3 convert/extract_construction_history.py --gpt\n\n"
            "Cache behavior:\n"
            "  pandas builds the row filter before any API calls.\n"
            "  Natural rows are handled manually and are not sent to an LLM.\n"
            "  Duplicate rows are handled manually by cache key before API calls.\n"
            "  Cached successful rows are reused automatically.\n"
            "  LLM_BATCH_LIMIT counts only unique uncached non-Natural API calls.\n"
            "  If every row is cached, no API calls are made.\n"
            "  Use --force or FORCE_LLM=1 to call APIs again.\n\n"
            "Outputs:\n"
            "  --gemini writes convert/llm_cache_gemini.json\n"
            "  --gpt writes convert/llm_cache_gpt.json\n"
            "  --both writes both caches\n\n"
            "After extraction, run:\n"
            "  python3 convert/human_label_disagreements.py\n"
            "  Edit convert/disagreements.csv by hand\n"
            "  python3 convert/evaluate_construction_dates.py --score --apply-final-dates"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gemini", action="store_true", help="Run Gemini 2.5 Flash Lite extraction.")
    parser.add_argument("--gpt", action="store_true", help="Run GPT-4o Mini extraction.")
    parser.add_argument("--both", action="store_true", help="Run Gemini and GPT extraction.")
    parser.add_argument("--force", action="store_true", help="Ignore provider cache and call the selected APIs again.")
    parser.add_argument("--no-llm", action="store_true", help="Do not call APIs; parse descriptions locally.")
    parser.add_argument("--test-parser", action="store_true", help="Print local date parser examples and exit.")
    return parser.parse_args()


def selected_providers(args):
    providers = []
    if args.both or args.gemini:
        providers.append("gemini")
    if args.both or args.gpt:
        providers.append("gpt")
    if not providers and not (args.no_llm or args.test_parser):
        providers.append("gemini")
    return providers


def provider_cache_path(root, provider):
    override = os.environ.get(f"{provider.upper()}_CACHE_PATH")
    return root / (override or PROVIDERS[provider]["cache"])


def provider_model(provider):
    config = PROVIDERS[provider]
    return os.environ.get(config["model_env"], config["default_model"])


def evaluation_model():
    return os.environ.get("EVAL_MODEL", "gpt-4.1")


def provider_api_key(provider):
    if provider == "gemini":
        return os.environ.get("GEMINI_API_KEY")
    if provider == "gpt":
        return os.environ.get("OPENAI_API_KEY")
    return None


def is_cached_success(result):
    if not isinstance(result, dict):
        return False

    # Completed LLM results can legitimately have llm_built/date as null and
    # may include a semantic message like "no construction date found".
    # Only retry cached rows that look like transport/API failures from older runs.
    error = str(result.get("error") or result.get("llm_error") or "")
    transient_error_markers = (
        "HTTP Error",
        "Too Many Requests",
        "429",
        "500",
        "502",
        "503",
        "504",
        "timed out",
        "urlopen error",
    )
    if any(marker.lower() in error.lower() for marker in transient_error_markers):
        return False

    return any(key in result for key in ("provider", "llm_built", "date", "evidence", "llm_evidence"))


def is_natural_heritage(props):
    return str(props.get("heritage_category") or "").strip().lower() == "natural"


def natural_skip_result(provider, site_id, name):
    result = empty_result(provider, site_id, name)
    result["evidence"] = "Skipped LLM extraction because heritage_category is Natural."
    return result


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "pandas is required for this table step. Install it with: python3 -m pip install pandas"
        ) from exc
    return pd


def build_extraction_frame(data, cache, force_llm):
    pd = require_pandas()

    rows = []
    for index, feature in enumerate(data.get("features", [])):
        props = feature.get("properties", {})
        site_id = props.get("id_no")
        name = props.get("name_en") or props.get("name") or ""
        raw_description = props.get("short_description_en") or ""
        valid = bool(name and raw_description)
        natural = is_natural_heritage(props)
        description = compact_description(raw_description) if valid else ""
        key = cache_key(props, description) if valid else None
        cached_success = bool(valid and is_cached_success(cache.get(key)))

        rows.append({
            "index": index,
            "feature": feature,
            "props": props,
            "site_id": site_id,
            "name": name,
            "raw_description": raw_description,
            "description": description,
            "cache_key": key,
            "valid": valid,
            "natural": natural,
            "cached_success": cached_success,
            "needs_llm": bool(valid and not natural and (force_llm or not cached_success)),
        })

    columns = [
        "index",
        "feature",
        "props",
        "site_id",
        "name",
        "raw_description",
        "description",
        "cache_key",
        "valid",
        "natural",
        "cached_success",
        "needs_llm",
    ]
    return pd.DataFrame(rows, columns=columns)


def run_extraction(root, data, output_path, provider, force=False):
    api_key = provider_api_key(provider)
    model = provider_model(provider)
    cache_path = provider_cache_path(root, provider)
    if not api_key:
        key_name = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        raise SystemExit(f"Set {key_name} in .env before running --{provider}.")

    request_delay = float(os.environ.get("LLM_REQUEST_DELAY_SECONDS", "0.3"))
    batch_limit = os.environ.get("LLM_BATCH_LIMIT")
    batch_limit = int(batch_limit) if batch_limit else None
    if batch_limit is not None and batch_limit < 1:
        raise SystemExit("LLM_BATCH_LIMIT must be 1 or greater.")
    force_llm = force or os.environ.get("FORCE_LLM") == "1"
    cache = load_cache(cache_path)

    processed = 0
    failed = 0

    frame = build_extraction_frame(data, cache, force_llm)
    skipped = int((~frame["valid"]).sum()) if not frame.empty else 0
    cached_mask = frame["valid"] & frame["cached_success"] & (not force_llm) if not frame.empty else []
    cache_hits = int(cached_mask.sum()) if not frame.empty else 0
    natural_skipped = int((frame["valid"] & frame["natural"]).sum()) if not frame.empty else 0

    for _, row in frame[cached_mask].iterrows():
        enrich_feature(row["feature"], cache[row["cache_key"]])

    natural_work = frame[frame["valid"] & frame["natural"]].drop_duplicates("cache_key")
    for _, row in natural_work.iterrows():
        if is_cached_success(cache.get(row["cache_key"])):
            result = cache[row["cache_key"]]
        else:
            result = natural_skip_result(provider, row["site_id"], row["name"])
            cache[row["cache_key"]] = result
            save_json_atomic(cache_path, cache)
        for feature in frame[frame["cache_key"] == row["cache_key"]]["feature"]:
            enrich_feature(feature, result)

    work_before_dedupe = frame[frame["needs_llm"]].copy()
    work = work_before_dedupe.drop_duplicates("cache_key").copy()
    duplicate_rows_skipped = len(work_before_dedupe) - len(work)
    total_needing_llm = len(work)
    planned_requests = total_needing_llm
    if batch_limit:
        planned_requests = min(batch_limit, total_needing_llm)
        work = work.head(batch_limit)

    print(f"{provider} rows in input: {len(frame)}")
    print(f"{provider} cached successful rows: {cache_hits}")
    print(f"{provider} natural rows handled manually without LLM: {natural_skipped}")
    print(f"{provider} duplicate rows handled manually without LLM: {duplicate_rows_skipped}")
    print(f"{provider} unique uncached non-natural rows needing LLM: {total_needing_llm}")
    if batch_limit:
        print(f"{provider} batch limit: {batch_limit}; sending {planned_requests} uncached rows")
    else:
        print(f"{provider} sending {planned_requests} uncached rows")

    if planned_requests == 0:
        save_json_atomic(cache_path, cache)
        save_json_atomic(output_path, data)
        print(f"{provider} has no uncached non-natural rows to send.")
        print(f"Wrote {cache_path}")
        print(f"{provider} LLM requests: 0")
        print(f"{provider} cache hits: {cache_hits}")
        print(f"{provider} skipped: {skipped}")
        print(f"{provider} failed: 0")
        return

    for offset, (_, row) in enumerate(work.iterrows(), start=1):
        site_id = row["site_id"]
        name = row["name"]
        description = row["description"]
        key = row["cache_key"]
        feature = row["feature"]

        try:
            result = call_provider(provider, api_key, model, site_id, name, description)
            cache[key] = result
            save_json_atomic(cache_path, cache)
            for matching_feature in frame[frame["cache_key"] == key]["feature"]:
                enrich_feature(matching_feature, result)
            processed += 1
            print(f"[{provider} {processed}] {name}: built={result.get('llm_built')}")
        except KeyboardInterrupt:
            print(f"Interrupted during {provider}. Saved completed rows to {cache_path}.", file=sys.stderr)
            raise
        except Exception as exc:
            failed += 1
            result = empty_result(provider, site_id, name, str(exc))
            for matching_feature in frame[frame["cache_key"] == key]["feature"]:
                enrich_feature(matching_feature, result)
            print(f"Failed {provider}: {name}: {exc}", file=sys.stderr)

        save_json_atomic(output_path, data)

        if offset < planned_requests:
            time.sleep(request_delay)

    save_json_atomic(cache_path, cache)
    save_json_atomic(output_path, data)
    print(f"Wrote {cache_path}")
    print(f"{provider} LLM requests: {processed}")
    print(f"{provider} cache hits: {cache_hits}")
    print(f"{provider} skipped: {skipped}")
    print(f"{provider} failed: {failed}")


def run_no_llm(data, output_path):
    local_parsed = 0
    skipped = 0
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        raw_description = props.get("short_description_en") or ""
        if not raw_description:
            skipped += 1
            continue
        result = result_from_description(raw_description)
        enrich_feature(feature, result)
        local_parsed += 1
    save_json_atomic(output_path, data)
    print(f"Wrote {output_path}")
    print(f"Local parser rows: {local_parsed}")
    print(f"Skipped: {skipped}")


def main():
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")
    args = parse_args()

    if args.test_parser:
        run_parser_examples()
        return

    input_path = root / os.environ.get("GEOJSON_INPUT", "convert/sites.geojson")
    output_path = root / os.environ.get("GEOJSON_OUTPUT", "convert/sites.geojson")
    data = json.loads(input_path.read_text(encoding="utf-8"))

    if args.no_llm or os.environ.get("NO_LLM") == "1":
        run_no_llm(data, output_path)

    for provider in selected_providers(args):
        run_extraction(root, data, output_path, provider, force=args.force)

    if selected_providers(args):
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
