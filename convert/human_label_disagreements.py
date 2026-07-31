import argparse
import json
import os
from pathlib import Path

try:
    from .extract_construction_history import (
        load_cache,
        load_env,
        provider_cache_path,
        write_disagreement_outputs,
    )
except ImportError:
    from extract_construction_history import (
        load_cache,
        load_env,
        provider_cache_path,
        write_disagreement_outputs,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare the human-label CSV from Gemini/GPT extraction disagreements.",
        epilog=(
            "Run this after LLM extraction:\n"
            "  python3 convert/extract_construction_history.py --both\n"
            "  python3 convert/human_label_disagreements.py\n\n"
            "Outputs:\n"
            "  convert/llm_disagreements.json\n"
            "  convert/disagreements.csv\n\n"
            "Then edit convert/disagreements.csv by hand. Fill human_choice with:\n"
            "  gemini, gpt, tie, or neither\n\n"
            "For manual corrections when human_choice is neither, fill:\n"
            "  correct_start, correct_end, correct_BC_AD\n"
            "Optional:\n"
            "  correct_display\n\n"
            "Existing human label columns are preserved when this script is re-run."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        default=None,
        help="GeoJSON input path. Defaults to GEOJSON_INPUT or convert/sites.geojson.",
    )
    return parser.parse_args()


def main():
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")
    args = parse_args()

    input_path = root / (args.input or os.environ.get("GEOJSON_INPUT", "convert/sites.geojson"))
    data = json.loads(input_path.read_text(encoding="utf-8"))

    write_disagreement_outputs(
        root,
        data,
        load_cache(provider_cache_path(root, "gemini")),
        load_cache(provider_cache_path(root, "gpt")),
    )


if __name__ == "__main__":
    main()
