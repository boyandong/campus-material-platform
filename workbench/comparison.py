from __future__ import annotations

import re

from .models import (
    ComparisonReport,
    Conflict,
    PackageStatus,
    QuestionnaireReport,
    SourceInventory,
)


def _field_value(report: QuestionnaireReport, key: str):
    field = report.fields.get(key)
    return field.value if field else None


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _claimed_count(value) -> int | None:
    match = re.search(r"\d+", _as_text(value))
    return int(match.group()) if match else None


def compare_claims(
    questionnaire: QuestionnaireReport,
    inventory: SourceInventory,
    quality: dict | None = None,
) -> ComparisonReport:
    conflicts: list[Conflict] = []
    warnings = list(inventory.warnings)

    count = _claimed_count(_field_value(questionnaire, "claimed_file_count"))
    if count is not None and count != inventory.total_files:
        conflicts.append(
            Conflict(
                code="FILE_COUNT_MISMATCH",
                severity="error"
                if count >= 4 and abs(count - inventory.total_files) / count >= 0.5
                else "warning",
                message=f"卖家声明约 {count} 个文件，实际收到 {inventory.total_files} 个。",
                seller_value=count,
                detected_value=inventory.total_files,
                source_refs=[
                    "questionnaire:claimed_file_count",
                    "source_inventory:total_files",
                ],
                suggested_question="请确认文件数量差异是否由压缩包、临时文件或漏传资料导致。",
            )
        )

    completeness = _as_text(_field_value(questionnaire, "completeness"))
    missing = _as_text(_field_value(questionnaire, "missing_status")) + _as_text(
        _field_value(questionnaire, "missing_details")
    )
    claims_complete = bool(re.search("完整|齐全", completeness)) and not bool(
        re.search("不完整|不齐全|部分|缺", completeness)
    )
    if (
        claims_complete
        and missing
        and not re.fullmatch(r"(无|没有|不缺|无缺失)+", missing)
    ):
        conflicts.append(
            Conflict(
                code="COMPLETE_WITH_MISSING",
                severity="error",
                message="问卷同时出现“完整”和明确缺失说明。",
                seller_value={"completeness": completeness, "missing": missing},
                source_refs=[
                    "questionnaire:completeness",
                    "questionnaire:missing_details",
                ],
                suggested_question="请确认资料是否完整；若有缺失，请列出具体章节或文件。",
            )
        )

    claimed_types = _as_text(_field_value(questionnaire, "material_types"))
    found_types = {
        item.detected_material_type
        for item in inventory.items
        if item.detected_material_type
    }
    type_aliases = {
        "课件": "课件",
        "PPT": "课件",
        "实验": "实验方法与数据处理参考",
        "习题": "习题与练习",
        "题库": "习题与练习",
        "笔记": "学习笔记",
        "代码": "代码参考",
        "复习": "复习资料",
    }
    for token, normalized in type_aliases.items():
        if token.lower() in claimed_types.lower() and normalized not in found_types:
            conflicts.append(
                Conflict(
                    code="DECLARED_TYPE_NOT_FOUND",
                    severity="warning",
                    message=f"问卷声明包含“{token}”，文件名和基础结构中未明确发现对应资料。",
                    seller_value=token,
                    detected_value=sorted(found_types),
                    source_refs=[
                        "questionnaire:material_types",
                        "source_inventory:items",
                    ],
                    suggested_question=f"请指出“{token}”对应的文件，或确认本次是否漏传。",
                )
            )

    for item in inventory.items:
        if item.status == "FAILED":
            conflicts.append(
                Conflict(
                    code="UNREADABLE_FILE",
                    severity="error",
                    message=f"文件无法打开：{item.relative_path}",
                    detected_value=item.error,
                    source_refs=[f"file:{item.relative_path}"],
                    suggested_question="请重新导出或重新上传该文件。",
                )
            )

    if quality and claims_complete:
        empty = [
            row["file_id"]
            for row in quality["items"]
            if row["classification"] == "EMPTY_TEMPLATE"
        ]
        if empty:
            conflicts.append(
                Conflict(
                    code="COMPLETE_WITH_EMPTY_TEMPLATES",
                    severity="error",
                    message="声明完整，但检测到只有表头或大量空栏的模板；需核实实际内容。",
                    detected_value=empty,
                    source_refs=empty,
                    suggested_question="这些文件是否本来就是空白模板？请修正完整性声明或补交已填写内容。",
                )
            )
    claimed_year = _as_text(_field_value(questionnaire, "year"))
    years = sorted(
        set(
            re.findall(
                r"20[0-3]\d", " ".join(item.relative_path for item in inventory.items)
            )
        )
    )
    if claimed_year and years and not any(year in claimed_year for year in years):
        conflicts.append(
            Conflict(
                code="YEAR_MISMATCH",
                severity="warning",
                message="文件名中的年份与声明年份不一致，不能自动认定为同一版本。",
                detected_value=years,
                suggested_question="请确认学年、文件创建年份与实际适用年份的区别。",
            )
        )

    recommended = (
        PackageStatus.NEEDS_SELLER_CONFIRMATION
        if conflicts
        else PackageStatus.NEEDS_MANUAL_REVIEW
    )
    return ComparisonReport(
        conflicts=conflicts, warnings=warnings, recommended_status=recommended
    )
