"""Read-only real-data scan. Exports aggregate metrics only; never calls an AI provider."""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.content import extract_content
from workbench.quality import classify_content
from workbench.scanner import scan_materials
from workbench.storage import sha256_file, write_json


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    start = time.monotonic()
    inventory = scan_materials(args.source)
    classes, errors = Counter(), Counter()
    for row in inventory.items:
        if row.status != "READABLE":
            continue
        try:
            content = extract_content(args.source / row.relative_path)
            kind, _ = classify_content(row.extension, content, row.relative_path)
            classes[kind] += 1
        except Exception as exc:  # noqa: BLE001 -- collect anonymous per-file failure totals
            errors[type(exc).__name__] += 1
    unchanged = all(
        sha256_file(args.source / row.relative_path) == row.sha256
        for row in inventory.items
    )
    result = {
        "files": inventory.total_files,
        "readable": inventory.readable_files,
        "unsupported": inventory.unsupported_files,
        "failed": inventory.failed_files,
        "classifications_inferred": dict(classes),
        "content_errors": dict(errors),
        "original_hashes_unchanged": unchanged,
        "seconds": round(time.monotonic() - start, 2),
        "cloud_calls": 0,
        "ocr_or_redaction_run": False,
        "note": "只读实际资料基准；仅统计，不保存真实内容、文件名或联系方式。",
    }
    write_json(args.report, result)
    import json

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
