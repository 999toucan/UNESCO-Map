import argparse
from pathlib import Path

try:
    from .extract_construction_history import build_dataset, load_env, score_disagreements
except ImportError:
    from extract_construction_history import build_dataset, load_env, score_disagreements


def parse_args():
    parser = argparse.ArgumentParser(
        description="Score human labels and build the optional fine-tune JSONL.",
        epilog=(
            "Run this after you edit convert/disagreements.csv:\n"
            "  python3 convert/evaluate_construction_dates.py --score\n"
            "  python3 convert/evaluate_construction_dates.py --build-dataset\n"
            "  python3 convert/evaluate_construction_dates.py --score --build-dataset\n\n"
            "Inputs:\n"
            "  convert/disagreements.csv\n\n"
            "Outputs:\n"
            "  --score writes convert/eval_score.json\n"
            "  --build-dataset writes convert/fine_tune_dataset.jsonl\n\n"
            "EVAL_MODEL defaults to gpt-4.1 and is recorded in eval_score.json.\n"
            "Human labels are ground truth; this script does not ask an AI to overwrite them."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--score", action="store_true", help="Write convert/eval_score.json.")
    parser.add_argument(
        "--build-dataset",
        action="store_true",
        help="Write convert/fine_tune_dataset.jsonl from labeled rows.",
    )
    return parser.parse_args()


def main():
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")
    args = parse_args()

    if not args.score and not args.build_dataset:
        raise SystemExit("Choose --score, --build-dataset, or both. Use --help for examples.")

    if args.score:
        score_disagreements(root)
    if args.build_dataset:
        build_dataset(root)


if __name__ == "__main__":
    main()
