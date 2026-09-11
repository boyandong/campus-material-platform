from __future__ import annotations

import json
from pathlib import Path


def compare_packages(
    data_root: Path, product_id: str, course: dict, quality: dict
) -> dict:
    hashes = {item["sha256"] for item in quality["items"] if item["sha256"]}
    fingerprints = (
        set().union(*(set(item["text_fingerprint"]) for item in quality["items"]))
        if quality["items"]
        else set()
    )
    matches = []
    for other in data_root.glob("PRD-*/product.json"):
        if other.parent.name == product_id:
            continue
        try:
            product = json.loads(other.read_text(encoding="utf-8"))
            report = json.loads(
                (other.parent / "reports/quality_report.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, ValueError):
            continue
        old_hashes = {
            item["sha256"] for item in report.get("items", []) if item["sha256"]
        }
        old_fingerprints = (
            set().union(
                *(set(i.get("text_fingerprint", [])) for i in report.get("items", []))
            )
            if report.get("items")
            else set()
        )
        union = fingerprints | old_fingerprints
        similarity = len(fingerprints & old_fingerprints) / len(union) if union else 0
        old_course = product.get("course", {})
        same_course = bool(course.get("name")) and course.get("name") == old_course.get(
            "name", {}
        ).get("value")
        if hashes and hashes == old_hashes:
            kind = "EXACT_DUPLICATE"
        elif similarity >= 0.65:
            kind = "HIGH_OVERLAP"
        elif (
            same_course
            and course.get("year")
            and old_course.get("year", {}).get("value")
            and course["year"] != old_course["year"]["value"]
        ):
            kind = "DIFFERENT_VERSION"
        elif same_course and hashes & old_hashes:
            kind = "HIGH_OVERLAP"
        elif (
            same_course
            and fingerprints
            and old_fingerprints
            and similarity < 0.1
            and any(i.get("headings") for i in quality["items"])
            and any(i.get("headings") for i in report.get("items", []))
        ):
            kind = "POSSIBLY_COMPLEMENTARY"
        elif same_course:
            kind = "UNKNOWN"
        else:
            continue
        matches.append(
            {
                "other_product_id": product.get("product_id", other.parent.name),
                "classification": kind,
                "exact_shared_files": len(hashes & old_hashes),
                "text_shingle_jaccard": round(similarity, 3) if union else None,
                "provenance": "SYSTEM_CALCULATED",
                "requires_manual_review": True,
            }
        )
    return {
        "schema_version": "2.0",
        "matches": matches,
        "automatic_merge": False,
        "note": "相似度是实际文本分片的 Jaccard 指标，不是版权或完整性判定。互补资料必须人工确认。",
    }
