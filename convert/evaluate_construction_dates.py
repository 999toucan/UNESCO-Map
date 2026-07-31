import argparse
import json
import os
from pathlib import Path

try:
    from .date_parser import format_display
    from .extract_construction_history import (
        build_date_from_parts,
        load_env,
        parse_correct_date,
        require_pandas,
        row_date,
        save_json_atomic,
        score_disagreements,
    )
except ImportError:
    from date_parser import format_display
    from extract_construction_history import (
        build_date_from_parts,
        load_env,
        parse_correct_date,
        require_pandas,
        row_date,
        save_json_atomic,
        score_disagreements,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Score human labels and apply the final human-selected dates to the GeoJSON.",
        epilog=(
            "Run this after you edit convert/disagreements.csv:\n"
            "  python3 convert/evaluate_construction_dates.py --score\n"
            "  python3 convert/evaluate_construction_dates.py --apply-final-dates\n"
            "  python3 convert/evaluate_construction_dates.py --score --apply-final-dates\n\n"
            "Inputs:\n"
            "  convert/disagreements.csv\n"
            "  convert/sites.geojson\n\n"
            "Outputs:\n"
            "  --score writes convert/eval_score.json\n"
            "  --apply-final-dates updates convert/sites.geojson\n\n"
            "When human_choice is neither, fill correct_start, correct_end, and correct_BC_AD.\n"
            "correct_display is optional; if blank, it is generated automatically.\n"
            "Human labels are ground truth; this script does not ask an AI to overwrite them."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--score", action="store_true", help="Write convert/eval_score.json.")
    parser.add_argument(
        "--apply-final-dates",
        action="store_true",
        help="Apply human-selected final dates from convert/disagreements.csv to convert/sites.geojson.",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="GeoJSON input path. Defaults to GEOJSON_INPUT or convert/sites.geojson.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="GeoJSON output path. Defaults to GEOJSON_OUTPUT or convert/sites.geojson.",
    )
    return parser.parse_args()


def row_identifier(row):
    for field in ("site_id", "id_no"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def feature_identifier(feature):
    props = feature.get("properties", {})
    for field in ("site_id", "id_no"):
        value = str(props.get(field) or "").strip()
        if value:
            return value
    feature_id = str(feature.get("id") or "").strip()
    return feature_id


def feature_name(feature):
    props = feature.get("properties", {})
    return str(props.get("name_en") or props.get("name") or "").strip()


def build_manual_date(row):
    manual_date = parse_correct_date(row)
    if not manual_date:
        return None

    display = str(row.get("correct_display") or "").strip()
    if display:
        return manual_date

    start = manual_date.get("start_date")
    end = manual_date.get("end_date")
    era = manual_date.get("BC_AD")
    generated_display = format_display(start, end, era)
    return build_date_from_parts(start, end, era, generated_display)


def selected_final_date(row):
    choice = str(row.get("human_choice") or "").strip().lower()
    if choice == "gemini":
        return row_date(row, "gemini"), "gemini"
    if choice == "gpt":
        return row_date(row, "gpt"), "gpt"
    if choice == "tie":
        return row_date(row, "gemini") or row_date(row, "gpt"), "tie"
    if choice == "neither":
        return build_manual_date(row), "manual"
    return None, None


def apply_final_dates(root, input_path, output_path):
    pd = require_pandas()
    csv_path = root / "convert/disagreements.csv"
    if not csv_path.exists():
        raise SystemExit("Run convert/human_label_disagreements.py first, then label convert/disagreements.csv.")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    features = data.get("features", [])

    features_by_id = {}
    features_by_name = {}
    for feature in features:
        identifier = feature_identifier(feature)
        if identifier:
            features_by_id[identifier] = feature
        name = feature_name(feature)
        if name and name not in features_by_name:
            features_by_name[name] = feature

    summary = {
        "gemini_selections": 0,
        "gpt_selections": 0,
        "ties": 0,
        "manual_corrections": 0,
        "skipped_rows": 0,
        "updated_geojson_features": 0,
    }
    updated_feature_ids = set()

    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    for row in frame.to_dict(orient="records"):
        final_date, source = selected_final_date(row)
        if not final_date or not source:
            summary["skipped_rows"] += 1
            continue

        identifier = row_identifier(row)
        feature = features_by_id.get(identifier) if identifier else None

        if feature is None and not identifier:
            name = str(row.get("name_en") or "").strip()
            if name:
                feature = features_by_name.get(name)

        if feature is None:
            summary["skipped_rows"] += 1
            continue

        props = feature.setdefault("properties", {})
        props["date"] = final_date

        feature_key = feature_identifier(feature) or feature_name(feature) or str(id(feature))
        if feature_key not in updated_feature_ids:
            updated_feature_ids.add(feature_key)
            summary["updated_geojson_features"] += 1

        if source == "gemini":
            summary["gemini_selections"] += 1
        elif source == "gpt":
            summary["gpt_selections"] += 1
        elif source == "tie":
            summary["ties"] += 1
        elif source == "manual":
            summary["manual_corrections"] += 1

    save_json_atomic(output_path, data)
    print(f"Wrote {output_path}")
    print(json.dumps(summary, indent=2))


def main():
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")
    args = parse_args()

    if not args.score and not args.apply_final_dates:
        raise SystemExit("Choose --score, --apply-final-dates, or both. Use --help for examples.")

    input_path = root / (args.input or os.environ.get("GEOJSON_INPUT", "convert/sites.geojson"))
    output_path = root / (args.output or os.environ.get("GEOJSON_OUTPUT", "convert/sites.geojson"))

    if args.score:
        score_disagreements(root)
    if args.apply_final_dates:
        apply_final_dates(root, input_path, output_path)


if __name__ == "__main__":
    main()
