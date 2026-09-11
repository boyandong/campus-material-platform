from __future__ import annotations

import re
from pathlib import Path

from .imaging import preview_image


def authorized(value) -> bool:
    text = "、".join(value) if isinstance(value, list) else str(value or "")
    if re.search("不|否|禁止|未|unknown", text, re.IGNORECASE):
        return False
    return bool(
        re.fullmatch(
            r"\s*(允许|同意|授权|是|可以|允许脱敏预览|允许制作脱敏预览)\s*", text
        )
    )


def generate_previews(
    output: Path,
    privacy: dict,
    quality: dict,
    permission,
    scope,
    manual_scope: dict | None = None,
) -> dict:
    report = {
        "status": "NEEDS_AUTHORIZATION",
        "items": [],
        "scope": scope,
        "note": "样图只截取部分内容并加水印，未经人工确认不得对外发送。",
    }
    if not authorized(permission):
        return report
    scope_text = str(scope or "").strip()
    max_page = None
    # Only exact, unambiguous page constraints are machine interpreted.
    match = re.fullmatch(r"前\s*(\d+)\s*页", scope_text)
    if match:
        max_page = int(match.group(1))
    elif (
        scope_text
        and scope_text not in {"无", "不限", "脱敏后展示", "仅脱敏部分预览"}
        and manual_scope is None
    ):
        report["status"] = "NEEDS_SCOPE_CONFIRMATION"
        return report
    academic = {
        row["file_id"] for row in quality["items"] if row["academic_review_required"]
    }
    candidates, seen = [], set()
    for candidate in sorted(
        privacy["candidates"], key=lambda c: c["score"], reverse=True
    ):
        fid, page = candidate["file_id"], candidate["ordinal"]
        if candidate["quality"] != "readable" or candidate["sha256"] in seen:
            continue
        if manual_scope is not None:
            if page not in manual_scope.get(fid, []):
                continue
        elif fid in academic:
            continue
        if max_page is not None and (
            candidate["kind"] != "pdf_page" or page > max_page
        ):
            continue
        candidates.append(candidate)
        seen.add(candidate["sha256"])
        if len(candidates) == 5:
            break
    output.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(candidates, 1):
        target = output / f"preview-{index:02d}.png"
        digest = preview_image(Path(candidate["path"]), target)
        report["items"].append(
            {
                "path": str(target),
                "sha256": digest,
                "file_id": candidate["file_id"],
                "ordinal": candidate["ordinal"],
                "kind": candidate["kind"],
            }
        )
    report["status"] = "DRAFT_NEEDS_REVIEW" if report["items"] else "NO_SAFE_CANDIDATE"
    report["academic_scope_required"] = bool(academic and manual_scope is None)
    report["count"] = len(report["items"])
    return report
