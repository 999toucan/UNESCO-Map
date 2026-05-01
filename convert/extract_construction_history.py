import json
import os
import hashlib
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .date_parser import parse_llm_date_text, parser_examples, validate_normalized_date
except ImportError:
    from date_parser import parse_llm_date_text, parser_examples, validate_normalized_date


PROMPT = """Extract the original construction date for one heritage site.

Return JSON only in this exact shape:
{
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
  } | null
}

Rules:
- llm_built is the earliest concrete original creation/construction/opening/completion date.
- Ignore renovation, restoration, listing, designation, reopening, repair, or expansion dates for llm_built.
- Put later renovation/restoration/alteration dates in llm_renovated.
- If no reliable original date exists, set llm_built to null and date to null.
- Never convert missing/unknown dates into a fake date.
- Do not guess.
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

Description: __DESCRIPTION__
"""


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


def call_gemini(api_key, model, name, description):
    prompt = PROMPT.replace("__NAME__", name).replace("__DESCRIPTION__", description)

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
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = json.loads(res.read().decode("utf-8"))

            parts = payload["candidates"][0]["content"]["parts"]
            return extract_json("".join(part.get("text", "") for part in parts))

        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 4:
                raise
            wait = min(60, 2 ** attempt)
            print(f"Retrying after HTTP {exc.code}, wait {wait}s", file=sys.stderr)
            time.sleep(wait)


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


def main():
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")

    if "--test-parser" in sys.argv:
        run_parser_examples()
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

    input_path = root / os.environ.get("GEOJSON_INPUT", "convert/sites.geojson")
    output_path = root / os.environ.get("GEOJSON_OUTPUT", "convert/sites.geojson")
    cache_path = root / os.environ.get("LLM_CACHE_PATH", "convert/llm_cache.json")

    request_delay = float(os.environ.get("LLM_REQUEST_DELAY_SECONDS", "0.3"))
    batch_limit = os.environ.get("LLM_BATCH_LIMIT")
    batch_limit = int(batch_limit) if batch_limit else None

    force_llm = os.environ.get("FORCE_LLM") == "1"
    normalize_only = os.environ.get("NORMALIZE_ONLY") == "1"
    no_llm = os.environ.get("NO_LLM") == "1" or "--no-llm" in sys.argv

    if not api_key and not normalize_only and not no_llm:
        raise SystemExit("Set GEMINI_API_KEY in .env before running.")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    cache = load_cache(cache_path)

    processed = 0
    cache_hits = 0
    skipped = 0
    failed = 0
    local_parsed = 0

    for feature in data.get("features", []):
        props = feature.get("properties", {})

        name = props.get("name_en") or props.get("name") or ""
        raw_description = props.get("short_description_en") or ""

        if not name or not raw_description:
            skipped += 1
            continue

        description = compact_description(raw_description)
        key = cache_key(props, description)

        if no_llm:
            result = result_from_description(raw_description)
            enrich_feature(feature, result)
            local_parsed += 1
            continue

        if normalize_only:
            if "construction_history" in props:
                enrich_feature(feature, props["construction_history"])
            elif key in cache:
                enrich_feature(feature, cache[key])
                cache_hits += 1
            else:
                skipped += 1
            continue

        if not force_llm and key in cache:
            enrich_feature(feature, cache[key])
            cache_hits += 1
            continue

        if not force_llm and "construction_history" in props:
            enrich_feature(feature, props["construction_history"])
            skipped += 1
            continue

        try:
            result = call_gemini(api_key, model, name, description)

            result["_name"] = name
            result["_status"] = "ok"

            cache[key] = result
            enrich_feature(feature, result)

            processed += 1
            print(f"[{processed}] {name}: built={result.get('llm_built')}")

        except Exception as exc:
            failed += 1
            result = {
                "_name": name,
                "_status": "error",
                "error": str(exc),
                "llm_built": None,
                "llm_renovated": None,
                "evidence": None,
            }

            cache[key] = result
            enrich_feature(feature, result)

            print(f"Failed: {name}: {exc}", file=sys.stderr)

        save_json_atomic(cache_path, cache)
        save_json_atomic(output_path, data)

        if batch_limit and processed >= batch_limit:
            break

        time.sleep(request_delay)

    if not normalize_only and not no_llm:
        save_json_atomic(cache_path, cache)
    save_json_atomic(output_path, data)

    print(f"Wrote {output_path}")
    print(f"LLM requests: {processed}")
    print(f"Cache hits: {cache_hits}")
    print(f"Local parser rows: {local_parsed}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
