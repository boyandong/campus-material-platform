from __future__ import annotations

import re
from pathlib import Path

from .models import ProductDocument
from .privacy import Redactor
from .storage import write_json


def _value(product: ProductDocument, section: str, key: str):
    field = getattr(product, section).get(key)
    return field.value if field else None


def build_buyer_card(product: ProductDocument, *, redactor=None) -> dict[str, object]:
    redactor = redactor or Redactor()
    redactor.known.update(str(v.value) for v in product.seller.values() if v.value)
    for section, key in [("pricing", "minimum_take_home"), ("course", "teacher")]:
        value = _value(product, section, key)
        if value:
            redactor.known.add(str(value))
    card: dict[str, object] = {
        "schema_version": "2.0",
        "product_id": product.product_id,
        "course": {
            "name": _value(product, "course", "name"),
            "college": _value(product, "course", "college"),
            "major": _value(product, "course", "major"),
            "year": _value(product, "course", "year"),
        },
        "materials": {
            "types": _value(product, "materials", "types"),
            "summary": _value(product, "materials", "summary"),
            "ai_summary_draft": _value(product, "materials", "ai_summary"),
            "summary_provenance": "INFERRED",
            "file_count": _value(product, "materials", "file_count"),
            "readable_file_count": _value(product, "materials", "readable_file_count"),
            "extensions": _value(product, "materials", "extensions"),
        },
        "objective_quality": {
            "content_counts": _value(product, "quality", "content_counts"),
            "effective_content_files_inferred": _value(
                product, "quality", "effective_content_files"
            ),
            "declared_completeness": _value(
                product, "quality", "declared_completeness"
            ),
            "declared_missing": _value(product, "quality", "declared_missing"),
            "unreadable_files": _value(product, "quality", "unreadable_files"),
            "has_preview_authorization": _value(
                product, "authorization", "preview_authorization"
            ),
        },
        "compatibility": {
            "scope": _value(product, "compatibility", "scope"),
            "basis": _value(product, "compatibility", "basis"),
        },
        "catalog": _value(product, "materials", "verified_headings") or [],
        "chapters_declared": _value(product, "materials", "chapters_declared"),
        "warnings": ["仍需核对适用年份、资料完整性和授权范围。"]
        if product.warnings
        else [],
        "review_status": product.quality_gate.get("status"),
        "disclaimer": "课程内容会因学院、专业、教师和年份而异，请先核对目录与预览。",
        "academic_integrity": "仅供理解原理、方法和数据处理过程，不得复制或直接作为本人课程作业、实验报告提交。",
        "previews": [
            {"file": item["path"], "kind": item["kind"]}
            for item in product.preview.get("items", [])
        ],
        "faq": [
            {
                "question": "是否适合我的课程？",
                "answer": "先比较课程章节、学院和年份，无法确认时请登记具体需求。",
            },
            {
                "question": "是否保证成绩或通过？",
                "answer": "不保证；资料只作学习思路参考。",
            },
        ],
        "publishable": product.quality_gate.get("status") == "APPROVED",
    }
    historical = _value(product, "historical_result", "seller_declared")
    if historical:
        card["historical_result"] = {
            "value": historical,
            "label": "卖家声明，未经核验",
            "disclaimer": "历史结果不代表资料效果，不构成成绩、提分或通过保证。",
        }
    for key in ("summary", "ai_summary_draft"):
        value = card["materials"].get(key)
        if value and re.search(
            "保过|保证.*(?:分|通过)|提分|通过率|高分保证|直接提交|代写", str(value)
        ):
            card["materials"][key] = "内容概述存在不适当效果或用途表述，待人工改写。"
    pricing = _value(product, "pricing", "calculated") or {}
    if card["publishable"] and product.review.get("confirmations", {}).get("price"):
        card["asking_price"] = pricing.get("recommended_list_price")

    # Free-text fields are not made public merely by appearing under a whitelisted key.
    def remove_internal(value):
        if isinstance(value, str) and re.search(
            "最低到手|底价|内部备注|内部成本|私人账号", value
        ):
            return "内部信息已省略"
        if isinstance(value, dict):
            return {k: remove_internal(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remove_internal(v) for v in value]
        return value

    return redactor.clean_object(remove_internal(card))


def render_buyer_card_markdown(card: dict[str, object]) -> str:
    course = card["course"]
    materials = card["materials"]
    quality = card["objective_quality"]
    lines = [
        f"# {course.get('name') or '课程资料（待确认）'}",
        "",
        f"- 来源学院：{course.get('college') or '待人工确认'}",
        f"- 来源专业：{course.get('major') or '待人工确认'}",
        f"- 年份：{course.get('year') or '待人工确认'}",
        f"- 资料类型：{materials.get('types') or '待人工确认'}",
        f"- 文件数量：{materials.get('file_count') or 0}",
        f"- 可打开文件：{materials.get('readable_file_count') or 0}",
        f"- 有效内容文件（规则推断）：{quality.get('effective_content_files_inferred') or 0}",
        f"- 声明完整情况：{quality.get('declared_completeness') or '未声明'}",
        "",
        str(card["disclaimer"]),
        str(card["academic_integrity"]),
    ]
    if materials.get("summary"):
        lines.extend(["", "## 内容概述（声明）", str(materials["summary"])])
    if materials.get("ai_summary_draft"):
        lines.extend(
            ["", "## AI 摘要草稿（需核对）", str(materials["ai_summary_draft"])]
        )
    if card.get("previews"):
        lines.extend(
            [
                "",
                "## 选定样图",
                *[f"- {item['file']}（{item['kind']}）" for item in card["previews"]],
            ]
        )
    if card.get("catalog"):
        lines.extend(["", "## 目录", *["- " + str(h) for h in card["catalog"]]])
    if quality.get("content_counts"):
        lines.extend(["", "内容构成（推断）：" + str(quality["content_counts"])])
    if card.get("asking_price"):
        lines.extend(
            [
                "",
                "人工确认挂牌价："
                + str(card["asking_price"])
                + " 元（不含在线交易功能）",
            ]
        )
    if card.get("historical_result"):
        result = card["historical_result"]
        lines.extend(
            [
                "",
                f"历史结果：{result['value']}（{result['label']}）",
                result["disclaimer"],
            ]
        )
    if card.get("warnings"):
        lines.extend(
            ["", "## 需注意", *[f"- {warning}" for warning in card["warnings"]]]
        )
    lines.extend(
        [
            "",
            "> 已完成人工入库审核；仍只能在授权范围内分享。"
            if card["publishable"]
            else "> 本地草稿，未经人工审核不得对外发送。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_buyer_card(
    package_path: Path, product: ProductDocument, *, redactor=None
) -> tuple[dict[str, object], str]:
    card = build_buyer_card(product, redactor=redactor)
    markdown = render_buyer_card_markdown(card)
    write_json(package_path / "buyer_card.json", card)
    (package_path / "buyer_card.md").write_text(markdown, encoding="utf-8")
    return card, markdown
