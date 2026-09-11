from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from statistics import median

from .content import CODE_EXTENSIONS, Content


def classify_content(
    ext: str, content: Content, filename: str = ""
) -> tuple[str, list[str]]:
    stats, text = content.stats, content.text
    cells = stats.get("cells", 0)
    ratio = stats.get("non_empty_cells", 0) / cells if cells else 1
    chars = len(text.strip())
    reasons = []
    if stats.get("image_quality") == "suspected_empty_grid":
        return "EMPTY_TEMPLATE", ["GRID_MOSTLY_EMPTY_INFERRED"]
    if stats.get("image_quality") in {"blank", "blurred", "low_resolution"}:
        return "SUSPECTED_INCOMPLETE", ["IMAGE_" + stats["image_quality"].upper()]
    if ext == ".xlsx" and stats.get("populated_rows", 0) <= max(
        1, stats.get("sheets", 1)
    ):
        return "EMPTY_TEMPLATE", ["ONLY_HEADERS_OR_EMPTY_SHEETS"]
    if (cells >= 6 and ratio < 0.35) or (
        stats.get("placeholder_count", 0) >= 3 and chars < 800
    ):
        return "EMPTY_TEMPLATE", ["EMPTY_CELLS_OR_PLACEHOLDERS"]
    if chars == 0 and not stats.get("embedded_images"):
        if ext in {".png", ".jpg", ".jpeg", ".pdf"}:
            return "UNKNOWN", ["OCR_REQUIRED"]
        return "EMPTY_TEMPLATE", ["NO_CONTENT"]
    if stats.get("placeholder_count", 0) >= 2 or (cells >= 6 and ratio < 0.65):
        return "PARTIALLY_FILLED", ["PARTIAL_CELLS_OR_PLACEHOLDERS"]
    if re.search("实验要求|作业要求|提交要求|请完成|实验指导", text) and not re.search(
        "实验结果|结果分析|测量数据|结论", text
    ):
        return "ASSIGNMENT_INSTRUCTION", ["INSTRUCTIONS_ONLY_SUSPECTED"]
    if ext in CODE_EXTENSIONS:
        return "CODE", reasons
    if ext == ".xlsx" and stats.get("numeric_cells", 0) > 2 or ext == ".csv":
        return "RAW_DATA", reasons
    if ext == ".pptx":
        return "SLIDES", reasons
    if "笔记" in filename or "复习" in filename:
        return "NOTES", reasons
    if chars < 80:
        return "SUSPECTED_INCOMPLETE", ["VERY_LITTLE_TEXT"]
    return "FILLED_CONTENT", reasons


def fingerprint(text: str) -> list[str]:
    text = re.sub(r"\s+", "", text).lower()
    if len(text) < 30:
        return []
    return sorted(
        {
            hashlib.sha256(text[i : i + 20].encode()).hexdigest()[:20]
            for i in range(0, len(text) - 19, 10)
        }
    )[:2000]


def quality_report(inventory, contents: dict[str, Content]) -> dict:
    items, hash_groups, lengths = [], defaultdict(list), defaultdict(list)
    for number, source in enumerate(inventory.items, 1):
        file_id = f"F{number:04d}"
        content = contents.get(source.relative_path, Content())
        if source.status == "FAILED":
            kind, reasons = "UNREADABLE", ["UNREADABLE_FILE"]
        elif source.status == "UNSUPPORTED":
            kind, reasons = "UNKNOWN", ["UNSUPPORTED_FORMAT"]
        else:
            kind, reasons = classify_content(
                source.extension, content, source.relative_path
            )
        reasons += content.warnings
        academic = bool(
            re.search(
                r"实验报告|课程论文|作业答案|直接提交|照抄",
                source.relative_path + "\n" + content.text,
            )
        )
        if academic:
            reasons.append("ACADEMIC_INTEGRITY_REVIEW_REQUIRED")
        risk = (
            "RED"
            if kind == "UNREADABLE"
            else "YELLOW"
            if reasons
            or kind
            in {"UNKNOWN", "EMPTY_TEMPLATE", "PARTIALLY_FILLED", "SUSPECTED_INCOMPLETE"}
            else "GREEN"
        )
        item = {
            "file_id": file_id,
            "source_ref": source.relative_path,
            "classification": kind,
            "risk": risk,
            "reasons": reasons,
            "stats": content.stats,
            "headings": content.headings,
            "text_fingerprint": fingerprint(content.text),
            "sha256": source.sha256,
            "academic_review_required": academic,
            "provenance": "INFERRED",
        }
        items.append(item)
        hash_groups[source.sha256].append(file_id)
        if content.stats.get("characters", 0) > 0:
            lengths[source.extension].append(content.stats["characters"])
    for item, source in zip(items, inventory.items):
        group = lengths[source.extension]
        if (
            len(group) >= 3
            and item["stats"].get("characters", 0) < median(group) * 0.15
        ):
            item["reasons"].append("LOW_CONTENT_COMPARED_WITH_GROUP")
            if item["risk"] == "GREEN":
                item["risk"] = "YELLOW"
    counts = dict(Counter(i["classification"] for i in items))
    return {
        "schema_version": "2.0",
        "items": items,
        "counts": counts,
        "effective_content_files": sum(
            counts.get(k, 0)
            for k in ("FILLED_CONTENT", "RAW_DATA", "NOTES", "SLIDES", "CODE")
        ),
        "duplicate_groups": [group for group in hash_groups.values() if len(group) > 1],
        "risk_counts": dict(Counter(i["risk"] for i in items)),
        "note": "分类为规则推断，不等于验证内容正确、完整或有权分享。",
    }
