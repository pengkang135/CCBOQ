"""Outlook Email Pipeline — standalone orchestrator.

Runs: outlook_com (fetch) → outlook_classify (index + shortcuts + junctions)

Usage:
    python pipeline.py [--config pipeline_config.yaml]
    python pipeline.py --fetch-only
    python pipeline.py --classify-only
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger("pipeline")


def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "pipeline_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(config_path: str = None, fetch: bool = True, classify: bool = True):
    config = load_config(config_path)
    start = datetime.now(timezone.utc)

    results = {"fetched": 0, "indexes": 0, "shortcuts": 0, "junctions": 0}

    if fetch:
        from outlook_com import run as fetch_run
        logger.info("── Fetch phase ──")
        items = fetch_run(config_path)
        results["fetched"] = len(items)

    if classify:
        from outlook_classify import run as classify_run
        logger.info("── Classify phase ──")
        index_files = classify_run(config_path)
        # Count by type
        for f in index_files:
            fname = Path(f).name
            if "_index" in str(f):
                results["indexes"] += 1
            if "_shortcuts" in str(f):
                results["shortcuts"] += 1
            if "_junctions" in str(f):
                results["junctions"] += 1

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(f"Pipeline complete in {elapsed:.1f}s — {results}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Outlook Email Pipeline")
    parser.add_argument("--config", type=str, help="Path to pipeline_config.yaml")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--classify-only", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    fetch = not args.classify_only
    classify = not args.fetch_only

    run(args.config, fetch=fetch, classify=classify)


if __name__ == "__main__":
    main()
