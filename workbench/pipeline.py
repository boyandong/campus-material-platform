from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buyer_card import write_buyer_card
from .comparison import compare_claims
from .content import Content, extract_content
from .database import Database
from .deepseek import DeepSeekProvider
from .duplicates import compare_packages
from .imaging import ImageProcessor, LocalOCR
from .models import (
    ComparisonReport,
    PackageStatus,
    ProductDocument,
    Provenance,
    QuestionnaireReport,
    SourcedValue,
    SourceInventory,
    utc_now,
)
from .parser import parse_questionnaire
from .previews import authorized, generate_previews
from .pricing import calculate_pricing
from .privacy import Redactor
from .quality import quality_report
from .redaction import redact_sources
from .scanner import scan_materials
from .storage import (
    append_audit,
    copy_directory_read_only,
    copy_file_read_only,
    extract_zip_read_only,
    initialize_package,
    make_package_id,
    sha256_file,
    write_json,
)


class WorkbenchPipeline:
    def __init__(
        self,
        data_root: Path,
        database: Database,
        provider: DeepSeekProvider,
        *,
        ocr=None,
    ):
        self.data_root = data_root
        self.database = database
        self.provider = provider
        self.settings = getattr(provider, "settings", None)
        self.ocr = ocr or LocalOCR(data_root.parent / "models" / "rapidocr")
        self._processing = threading.Lock()

    def create_package(
        self, questionnaire: Path, materials: Path, materials_are_zip: bool = False
    ) -> str:
        package_id = make_package_id()
        package_path = initialize_package(self.data_root, package_id)
        self.database.create_package(package_id, package_path)
        audit = package_path / "reports" / "audit_log.jsonl"
        try:
            self.database.update_package(
                package_id, PackageStatus.COPYING_INPUTS, "copying_inputs"
            )
            questionnaire_record = copy_file_read_only(
                questionnaire, package_path / "original" / "questionnaire.docx"
            )
            if materials_are_zip:
                material_records = extract_zip_read_only(
                    materials, package_path / "original" / "materials"
                )
            else:
                material_records = copy_directory_read_only(
                    materials, package_path / "original" / "materials"
                )
            append_audit(
                audit,
                "originals_copied",
                {
                    "questionnaire_sha256": questionnaire_record["sha256"],
                    "material_file_count": len(material_records),
                    "material_hashes": [
                        {"file_id": f"F{i:04d}", "sha256": row["sha256"]}
                        for i, row in enumerate(material_records, 1)
                    ],
                },
            )
            write_json(
                package_path / "reports" / "original_manifest.json",
                {
                    "questionnaire": questionnaire_record["sha256"],
                    "materials": {
                        row["path"]: row["sha256"] for row in material_records
                    },
                },
            )
            self.database.update_package(
                package_id, PackageStatus.CREATED, "inputs_ready"
            )
            return package_id
        except Exception as exc:
            self.database.update_package(
                package_id, PackageStatus.FAILED, "copy_failed", type(exc).__name__
            )
            append_audit(audit, "copy_failed", {"error_type": type(exc).__name__})
            raise

    def _set_stage(self, package_id: str, status: PackageStatus, stage: str) -> None:
        self.database.update_package(package_id, status, stage)
        package = self._package_path(package_id)
        append_audit(
            package / "reports" / "audit_log.jsonl",
            "stage_changed",
            {"status": status.value, "stage": stage},
        )

    def _package_path(self, package_id: str) -> Path:
        row = self.database.get_package(package_id)
        if not row:
            raise KeyError(package_id)
        package = Path(row["package_path"]).resolve()
        if package.parent != self.data_root.resolve():
            raise ValueError("Package path is outside configured data root")
        return package

    @staticmethod
    def _from_questionnaire(report: QuestionnaireReport, key: str) -> SourcedValue:
        field = report.fields[key]
        return SourcedValue(
            value=field.value,
            raw_value=field.raw_value,
            provenance=field.provenance,
            source_refs=field.source_refs,
            confidence=field.confidence,
            verified_by=field.verified_by,
            verified_at=field.verified_at,
        )

    @staticmethod
    def _file_value(
        value: Any, source_ref: str, confidence: float = 1.0
    ) -> SourcedValue:
        return SourcedValue(
            value=value,
            provenance=Provenance.FILE_VERIFIED,
            source_refs=[source_ref],
            confidence=confidence,
        )

    def _build_product(
        self,
        package_id: str,
        questionnaire: QuestionnaireReport,
        inventory: SourceInventory,
        comparison: ComparisonReport,
        semantic_warning: str | None,
        semantic: Any,
        advanced_warning: str | None,
        advanced_review: Any,
    ) -> ProductDocument:
        extensions = dict(Counter(item.extension for item in inventory.items))
        detected_types = sorted(
            {
                item.detected_material_type
                for item in inventory.items
                if item.detected_material_type
            }
        )
        warnings = [*questionnaire.parser_warnings, *comparison.warnings]
        warnings.extend(conflict.message for conflict in comparison.conflicts)
        if semantic_warning:
            warnings.append(semantic_warning)
        if advanced_warning:
            warnings.append(advanced_warning)
        unanswered = [
            questionnaire.fields[key].label for key in questionnaire.unknown_fields
        ]
        unanswered.extend(
            conflict.suggested_question
            for conflict in comparison.conflicts
            if conflict.suggested_question
        )
        if semantic and semantic.normalized_material_types:
            normalized_types = SourcedValue(
                value=semantic.normalized_material_types,
                provenance=Provenance.INFERRED,
                source_refs=["deepseek:semantic_classification"],
                confidence=semantic.confidence,
            )
        else:
            normalized_types = SourcedValue(
                value=detected_types,
                provenance=Provenance.INFERRED,
                source_refs=["source_inventory:detected_material_type"],
                confidence=0.75,
            )
        status = comparison.recommended_status
        return ProductDocument(
            product_id=package_id,
            seller={
                "contact_method": self._from_questionnaire(
                    questionnaire, "contact_method"
                ),
                "contact_account": self._from_questionnaire(
                    questionnaire, "contact_account"
                ),
            },
            course={
                "name": self._from_questionnaire(questionnaire, "course_name"),
                "college": self._from_questionnaire(questionnaire, "college"),
                "major": self._from_questionnaire(questionnaire, "major"),
                "year": self._from_questionnaire(questionnaire, "year"),
                "teacher": self._from_questionnaire(questionnaire, "teacher"),
            },
            materials={
                "types": self._from_questionnaire(questionnaire, "material_types"),
                "normalized_types": normalized_types,
                "summary": self._from_questionnaire(questionnaire, "content_summary"),
                "ai_summary": SourcedValue(
                    value=semantic.material_summary if semantic else None,
                    provenance=Provenance.INFERRED
                    if semantic and semantic.material_summary
                    else Provenance.UNKNOWN,
                    source_refs=["deepseek:default_text_tasks"]
                    if semantic and semantic.material_summary
                    else [],
                    confidence=semantic.confidence
                    if semantic and semantic.material_summary
                    else 0,
                ),
                "catalog_outline": SourcedValue(
                    value=semantic.catalog_outline if semantic else [],
                    provenance=Provenance.INFERRED
                    if semantic and semantic.catalog_outline
                    else Provenance.UNKNOWN,
                    source_refs=["deepseek:default_text_tasks"]
                    if semantic and semantic.catalog_outline
                    else [],
                    confidence=semantic.confidence
                    if semantic and semantic.catalog_outline
                    else 0,
                ),
                "file_count": self._file_value(
                    inventory.total_files, "source_inventory:total_files"
                ),
                "readable_file_count": self._file_value(
                    inventory.readable_files, "source_inventory:readable_files"
                ),
                "extensions": self._file_value(extensions, "source_inventory:items"),
            },
            quality={
                "declared_completeness": self._from_questionnaire(
                    questionnaire, "completeness"
                ),
                "declared_missing": self._from_questionnaire(
                    questionnaire, "missing_details"
                ),
                "unreadable_files": self._file_value(
                    inventory.failed_files, "source_inventory:failed_files"
                ),
                "unsupported_files": self._file_value(
                    inventory.unsupported_files, "source_inventory:unsupported_files"
                ),
            },
            compatibility={
                "scope": self._from_questionnaire(questionnaire, "similar_scope"),
                "basis": self._from_questionnaire(questionnaire, "compatibility_basis"),
                "buyer_warnings": self._from_questionnaire(
                    questionnaire, "buyer_warnings"
                ),
            },
            authorization={
                "preview_authorization": self._from_questionnaire(
                    questionnaire, "preview_authorization"
                ),
                "preview_scope": self._from_questionnaire(
                    questionnaire, "preview_scope"
                ),
            },
            pricing={
                "minimum_take_home": self._from_questionnaire(
                    questionnaire, "minimum_take_home"
                ),
                "ai_suggestion": SourcedValue(
                    value=semantic.pricing_suggestion if semantic else None,
                    provenance=Provenance.INFERRED
                    if semantic and semantic.pricing_suggestion
                    else Provenance.UNKNOWN,
                    source_refs=["deepseek:default_text_tasks"]
                    if semantic and semantic.pricing_suggestion
                    else [],
                    confidence=semantic.confidence
                    if semantic and semantic.pricing_suggestion
                    else 0,
                ),
            },
            historical_result={
                "seller_declared": self._from_questionnaire(
                    questionnaire, "historical_grade"
                ),
                "evidence_declared": self._from_questionnaire(
                    questionnaire, "grade_evidence"
                ),
                "scope": self._from_questionnaire(questionnaire, "grade_scope"),
            },
            warnings=warnings,
            unanswered_questions=unanswered,
            quality_gate={
                "status": status.value,
                "approval_enabled": False,
                "privacy_scan": "NOT_RUN",
                "redaction": "NOT_RUN",
                "reason": "检测尚未完成，不能自动通过。",
                "advanced_review": advanced_review.model_dump(mode="json")
                if advanced_review
                else None,
                "advanced_review_model": self.provider.review_model
                if advanced_review and hasattr(self.provider, "review_model")
                else None,
            },
            artifacts={
                "questionnaire_report": "reports/questionnaire_report.json",
                "source_inventory": "reports/source_inventory.json",
                "comparison_report": "reports/comparison_report.json",
                "audit_report": "reports/audit_report.md",
                "buyer_card": "buyer_card.json",
                "catalog": "catalog.md",
            },
        )

    def process(self, package_id: str, *, allow_cloud_images=False) -> ProductDocument:
        package = self._package_path(package_id)
        if not self._processing.acquire(blocking=False):
            raise ValueError("已有任务正在处理，请完成后再试。")
        reports = package / "reports"
        audit = reports / "audit_log.jsonl"
        run_id = uuid4().hex[:12]
        call_start = len(getattr(self.provider, "call_log", []))
        try:
            manifest_path = reports / "original_manifest.json"
            manifest = self._read(manifest_path)
            if not manifest:
                manifest = {
                    "questionnaire": sha256_file(
                        package / "original/questionnaire.docx"
                    ),
                    "materials": {
                        p.relative_to(
                            package / "original/materials"
                        ).as_posix(): sha256_file(p)
                        for p in (package / "original/materials").rglob("*")
                        if p.is_file()
                    },
                }
                write_json(manifest_path, manifest)
            self._verify_originals(package, manifest)
            answers = self._read(reports / "human_answers.json") or {}
            self._set_stage(
                package_id, PackageStatus.PARSING_QUESTIONNAIRE, "parsing_questionnaire"
            )
            questionnaire = parse_questionnaire(
                package / "original" / "questionnaire.docx"
            )
            for key, answer in answers.items():
                if key.startswith("field:") and key[6:] in questionnaire.fields:
                    field = questionnaire.fields[key[6:]]
                    field.value = answer["answer"]
                    field.provenance = Provenance.HUMAN_VERIFIED
                    field.verified_by, field.verified_at = (
                        answer["reviewer"],
                        answer["at"],
                    )
                    field.confidence = 1
            questionnaire.unknown_fields = [
                k for k, v in questionnaire.fields.items() if v.value is None
            ]
            write_json(
                reports / "questionnaire_report.json",
                questionnaire.model_dump(mode="json"),
            )
            self._set_stage(package_id, PackageStatus.SCANNING_FILES, "scanning_files")
            inventory = scan_materials(package / "original" / "materials")
            write_json(
                reports / "source_inventory.json", inventory.model_dump(mode="json")
            )
            contents = {}
            for source in inventory.items:
                if source.status != "READABLE":
                    continue
                try:
                    contents[source.relative_path] = extract_content(
                        package / "original/materials" / source.relative_path
                    )
                except Exception as exc:  # noqa: BLE001 -- record incomplete extraction as a blocking warning
                    contents[source.relative_path] = Content(
                        warnings=["EXTRACTION_FAILED:" + type(exc).__name__]
                    )
            redactor = Redactor(
                [
                    str(questionnaire.fields[k].value or "")
                    for k in ("contact_account", "teacher")
                ]
            )
            for field in questionnaire.fields.values():
                redactor.discover(str(field.value or ""))
            self._set_stage(
                package_id, PackageStatus.PRIVACY_SCAN, "privacy_scan_and_redaction"
            )
            images = ImageProcessor(
                self.ocr,
                redactor,
                self.provider,
                allow_cloud=allow_cloud_images,
                max_calls=getattr(self.settings, "max_image_calls", 5),
            )
            privacy = redact_sources(
                package / "original/materials",
                package / "processed" / run_id,
                inventory,
                contents,
                images,
                max_pdf_pages=getattr(self.settings, "max_pdf_pages", 60),
            )
            self._set_stage(
                package_id, PackageStatus.QUALITY_CHECK, "content_quality_gate"
            )
            quality = quality_report(inventory, contents)
            for row, privacy_row in zip(quality["items"], privacy["items"]):
                if privacy_row["status"] == "BLOCKED":
                    row["risk"] = "RED"
                    row["reasons"].append("PRIVACY_COVERAGE_FAILED")
                elif privacy_row["findings"] or privacy_row["images"]:
                    if row["risk"] == "GREEN":
                        row["risk"] = "YELLOW"
                    row["reasons"].append("PRIVACY_MANUAL_REVIEW_REQUIRED")
            quality["risk_counts"] = dict(
                Counter(row["risk"] for row in quality["items"])
            )
            for row in quality["items"]:
                row["headings"] = redactor.clean_object(row["headings"])
            write_json(reports / "quality_report.json", quality)
            self._set_stage(package_id, PackageStatus.COMPARING, "comparing_claims")
            comparison = compare_claims(questionnaire, inventory, quality)
            write_json(
                reports / "comparison_report.json", comparison.model_dump(mode="json")
            )
            safe_text = {
                key: questionnaire.fields[key].value
                for key in (
                    "course_name",
                    "material_types",
                    "content_summary",
                    "similar_scope",
                    "compatibility_basis",
                    "buyer_warnings",
                )
                if questionnaire.fields[key].value
            }
            safe_text["detected_file_count"] = inventory.total_files
            safe_text["detected_extensions"] = dict(
                Counter(item.extension for item in inventory.items)
            )
            safe_text["content_excerpts"] = [
                {
                    "file_id": f"F{i:04d}",
                    "excerpt": contents[s.relative_path].text[:1200],
                }
                for i, s in enumerate(inventory.items[:20], 1)
                if s.relative_path in contents
            ]
            safe_text = redactor.clean_object(safe_text)
            semantic, semantic_warning = self.provider.classify(safe_text)
            if semantic:
                semantic = type(semantic).model_validate(
                    redactor.clean_object(semantic.model_dump())
                )
            versions = compare_packages(
                self.data_root,
                package_id,
                {
                    ("name" if k == "course_name" else k): questionnaire.fields[k].value
                    for k in ("course_name", "college", "major", "year")
                },
                quality,
            )
            write_json(reports / "version_comparison.json", versions)
            advanced_review = None
            advanced_warning = None
            needs_advanced = bool(
                comparison.conflicts
                or quality["risk_counts"].get("RED")
                or len(versions.get("matches", [])) > 1
            )
            if needs_advanced and hasattr(self.provider, "advanced_review"):
                safe_conflicts = redactor.clean_object(
                    {
                        "trigger": "red_risk_or_information_conflict_or_complex_comparison",
                        "conflicts": [c.model_dump() for c in comparison.conflicts],
                        "risk_counts": quality["risk_counts"],
                        "version_comparisons": versions,
                    }
                )
                advanced_review, advanced_warning = self.provider.advanced_review(
                    safe_conflicts
                )
            self._set_stage(
                package_id, PackageStatus.BUILDING_PRODUCT, "building_product"
            )
            product = self._build_product(
                package_id,
                questionnaire,
                inventory,
                comparison,
                semantic_warning,
                semantic,
                advanced_warning,
                advanced_review,
            )
            self._set_stage(package_id, PackageStatus.PRICING, "pricing_suggestion")
            pricing = calculate_pricing(
                questionnaire.fields["minimum_take_home"].value,
                quality,
                getattr(self.settings, "commission_rate", "0.35"),
                getattr(self.settings, "referral_rate", "0.10"),
            )
            write_json(reports / "pricing_report.json", pricing)
            product.pricing["calculated"] = SourcedValue(
                value=pricing,
                provenance=Provenance.SYSTEM_CALCULATED,
                source_refs=["reports/pricing_report.json"],
                confidence=1,
            )
            product.quality["effective_content_files"] = SourcedValue(
                value=quality["effective_content_files"],
                provenance=Provenance.INFERRED,
                source_refs=["quality_report:effective_content_files"],
                confidence=0.7,
            )
            product.quality["content_counts"] = SourcedValue(
                value=quality["counts"],
                provenance=Provenance.INFERRED,
                source_refs=["reports/quality_report.json"],
                confidence=0.7,
            )
            product.materials["verified_headings"] = self._file_value(
                [h for row in quality["items"] for h in row["headings"]],
                "quality_report:headings",
            )
            product.materials["chapters_declared"] = self._from_questionnaire(
                questionnaire, "chapters_or_experiments"
            )
            self._set_stage(
                package_id,
                PackageStatus.GENERATING_PREVIEWS,
                "authorized_partial_previews",
            )
            scope_answer = answers.get("preview_scope", {})
            scope = scope_answer.get("selection")
            preview = generate_previews(
                package / "previews" / run_id,
                privacy,
                quality,
                questionnaire.fields["preview_authorization"].value,
                questionnaire.fields["preview_scope"].value,
                scope,
            )
            pricing = calculate_pricing(
                questionnaire.fields["minimum_take_home"].value,
                quality,
                getattr(self.settings, "commission_rate", "0.35"),
                getattr(self.settings, "referral_rate", "0.10"),
                context={
                    "source_known": bool(
                        questionnaire.fields["college"].value
                        and questionnaire.fields["major"].value
                    ),
                    "year_known": bool(questionnaire.fields["year"].value),
                    "has_catalog": any(row["headings"] for row in quality["items"]),
                    "has_previews": bool(preview["items"]),
                    "declared_missing": bool(comparison.conflicts),
                },
            )
            manual_price = answers.get("pricing:list_price")
            if manual_price and pricing.get("theoretical_min_sale_price"):
                from decimal import Decimal

                if Decimal(manual_price["answer"]) < Decimal(
                    pricing["theoretical_min_sale_price"]
                ):
                    pricing["status"] = "HOLD_FOR_REVIEW"
                    pricing["pricing_reasoning"].append(
                        "人工价格低于重新计算的底线，请更正。"
                    )
                else:
                    pricing["calculated_list_price"] = pricing["recommended_list_price"]
                    pricing["recommended_list_price"] = manual_price["answer"]
                    pricing["human_price"] = manual_price
                    from decimal import ROUND_HALF_UP

                    amount = Decimal(manual_price["answer"])
                    rate = Decimal(pricing["platform_commission_rate"])
                    referral = Decimal(pricing["referral_commission_rate"])
                    pricing["payout_example"] = {
                        "sale_price": str(amount),
                        "seller": str(
                            (amount * (1 - rate)).quantize(
                                Decimal(".01"), rounding=ROUND_HALF_UP
                            )
                        ),
                        "referrer": str(
                            (amount * referral).quantize(
                                Decimal(".01"), rounding=ROUND_HALF_UP
                            )
                        ),
                        "platform_with_referral": str(
                            (amount * (rate - referral)).quantize(
                                Decimal(".01"), rounding=ROUND_HALF_UP
                            )
                        ),
                    }
            write_json(reports / "pricing_report.json", pricing)
            product.pricing["calculated"].value = pricing
            product.pricing["list_price"] = SourcedValue(
                value=pricing.get("recommended_list_price"),
                provenance=Provenance.HUMAN_VERIFIED
                if manual_price
                else Provenance.SYSTEM_CALCULATED,
                source_refs=["reports/pricing_report.json"],
                confidence=1,
                verified_by=manual_price["reviewer"] if manual_price else None,
                verified_at=manual_price["at"] if manual_price else None,
            )
            # Internal reports refer only to package-relative derived paths.
            for row in privacy["items"]:
                if row["processed_file"]:
                    row["processed_file"] = (
                        Path(row["processed_file"]).relative_to(package).as_posix()
                    )
            for candidate in privacy["candidates"]:
                candidate["path"] = (
                    Path(candidate["path"]).relative_to(package).as_posix()
                )
            for row in preview["items"]:
                row["path"] = Path(row["path"]).relative_to(package).as_posix()
            privacy = redactor.clean_object(privacy)
            write_json(reports / "privacy_report.json", privacy)
            write_json(reports / "preview_report.json", preview)
            product.privacy, product.preview = privacy, preview
            product.questions = self._questions(
                questionnaire, comparison, privacy, preview, answers
            )
            product.unanswered_questions = [
                q["question"] for q in product.questions if not q.get("answer")
            ]
            write_json(reports / "questions.json", product.questions)
            hard_blocks = []
            if privacy["blocked_files"]:
                hard_blocks.append("部分文件隐私覆盖失败，需重新导出/补交后新建资料包")
            if not inventory.total_files:
                hard_blocks.append("没有实际资料文件")
            if any(c.severity == "error" for c in comparison.conflicts):
                hard_blocks.append("红色声明冲突未消除，请修正声明或补交资料后重新处理")
            if quality["risk_counts"].get("RED"):
                hard_blocks.append("存在内容或隐私覆盖高风险文件")
            if advanced_review and advanced_review.risk_level == "HIGH":
                hard_blocks.append("高级审核标记高风险，需处理证据后重新运行")
            if not authorized(questionnaire.fields["preview_authorization"].value):
                hard_blocks.append("尚未明确授权展示")
            if not preview["items"]:
                hard_blocks.append("没有授权范围内可供复核的样图")
            if pricing.get("status") != "DRAFT":
                hard_blocks.append("价格不明确或内容质量待处理，不能确认价格")
            if not questionnaire.fields["course_name"].value:
                hard_blocks.append("课程名称未明确")
            product.quality_gate = {
                "status": comparison.recommended_status.value,
                "approval_enabled": not hard_blocks,
                "risk_level": "RED"
                if hard_blocks
                else "YELLOW"
                if quality["risk_counts"].get("YELLOW")
                or comparison.conflicts
                or questionnaire.unknown_fields
                else "GREEN",
                "hard_blocks": hard_blocks,
                "privacy_scan": privacy["status"],
                "redaction": "DRAFTS_ONLY",
                "run_id": run_id,
                "originals_verified": True,
                "reason": "仅本地草稿。通过入库必须逐项人工确认，不会自动发布。",
                "advanced_review": redactor.clean_object(advanced_review.model_dump())
                if advanced_review
                else None,
            }
            product.review = {"confirmations": {}, "run_id": run_id}
            product.artifacts.update(
                {
                    name: "reports/" + name + ".json"
                    for name in (
                        "quality_report",
                        "privacy_report",
                        "pricing_report",
                        "preview_report",
                        "questions",
                        "version_comparison",
                    )
                }
            )
            write_json(
                reports / "model_calls.json",
                {
                    "calls": getattr(self.provider, "call_log", [])[call_start:],
                    "text_scope": "规则清理后的问卷白名单和最多20文件、每文件1200字符摘录；不是全量理解",
                    "cloud_images_consent": allow_cloud_images,
                },
            )
            self._verify_originals(package, manifest)
            self._save_outputs(package, product, inventory, quality, redactor)
            self._set_stage(
                package_id, PackageStatus.GENERATING_CARD, "generating_buyer_card"
            )
            final_status = comparison.recommended_status
            self._set_stage(package_id, final_status, "awaiting_human_review")
            append_audit(
                audit,
                "pipeline_completed",
                {
                    "final_status": final_status.value,
                    "conflict_count": len(comparison.conflicts),
                },
            )
            return product
        except Exception as exc:
            self.database.update_package(
                package_id, PackageStatus.FAILED, "pipeline_failed", type(exc).__name__
            )
            append_audit(audit, "pipeline_failed", {"error_type": type(exc).__name__})
            raise
        finally:
            self._processing.release()

    @staticmethod
    def _read(path: Path):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @staticmethod
    def _verify_originals(package: Path, manifest: dict):
        actual = {
            p.relative_to(package / "original/materials").as_posix(): sha256_file(p)
            for p in (package / "original/materials").rglob("*")
            if p.is_file()
        }
        if (
            actual != manifest["materials"]
            or sha256_file(package / "original/questionnaire.docx")
            != manifest["questionnaire"]
        ):
            raise ValueError("原件哈希发生变化，已停止处理。请保留现场并新建资料包。")

    @staticmethod
    def _questions(questionnaire, comparison, privacy, preview, answers):
        questions = [
            {
                "id": "field:" + key,
                "question": field.label + "：请填写或明确说明无法确定。",
            }
            for key, field in questionnaire.fields.items()
            if field.value is None or "field:" + key in answers
        ]
        questions += [
            {"id": "conflict:" + str(i), "question": c.suggested_question or c.message}
            for i, c in enumerate(comparison.conflicts)
        ]
        if preview["status"] in {"NEEDS_SCOPE_CONFIRMATION", "NO_SAFE_CANDIDATE"}:
            questions.append(
                {
                    "id": "preview_scope",
                    "question": "请在授权内选择文件编号和页/图序号，例如 F0001:1,F0002:2；不可超出卖家授权。",
                }
            )
        for q in questions:
            if q["id"] in answers:
                q.update(answers[q["id"]])
        return questions

    @staticmethod
    def _save_outputs(package, product, inventory, quality, redactor):
        product.updated_at = utc_now()
        write_json(package / "product.json", product.model_dump(mode="json"))
        write_buyer_card(package, product, redactor=redactor)
        lines = [
            "# "
            + redactor.clean(str(product.course["name"].value or "课程待确认"))
            + " · 目录草稿",
            "",
            "> 由实际文件结构提取；分类为规则推断，未证明内容正确或完整。",
            "",
        ]
        lines += [
            "## 内容构成",
            f"- 总文件：{inventory.total_files}",
            f"- 有效内容（推断）：{quality.get('effective_content_files', 0)}",
            *[
                f"- {kind}：{count}"
                for kind, count in quality.get("counts", {}).items()
            ],
            "",
        ]
        for row, item in zip(quality.get("items", []), inventory.items):
            lines.append(
                f"## {row['file_id']} · {item.extension} · {row['classification']}"
            )
            lines.extend("- " + h for h in row["headings"])
            if not row["headings"]:
                lines.append("- 未识别到明确章节标题，需人工补目录。")
        (package / "catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = [
            f"# {product.product_id} 审核报告",
            "",
            "状态：" + product.quality_gate["status"],
            "原件哈希核验：通过",
            f"文件：{inventory.total_files}；有效内容文件（推断）：{quality.get('effective_content_files', 0)}",
            "",
            "## 入库阻断项",
            *["- " + text for text in product.quality_gate.get("hard_blocks", [])],
            "",
            "## 警告",
            *["- " + redactor.clean(text) for text in product.warnings],
            "",
            "## 人工结论",
            json.dumps(product.review, ensure_ascii=False, indent=2),
            "",
            "全部报告为内部文件；只有审核后的买家卡和选定样图可按授权分享。",
        ]
        (package / "reports/audit_report.md").write_text(
            "\n".join(report) + "\n", encoding="utf-8"
        )

    def answer_question(
        self, package_id: str, question_id: str, answer: str, reviewer: str
    ) -> None:
        if self._processing.locked():
            raise ValueError("请等待处理完成。")
        if not answer.strip() or not reviewer.strip():
            raise ValueError("请填写回答及核验人。")
        package = self._package_path(package_id)
        questionnaire = self._read(package / "reports/questionnaire_report.json") or {}
        questions = self._read(package / "reports/questions.json") or []
        valid = (
            {q["id"] for q in questions}
            | {"field:" + key for key in questionnaire.get("fields", {})}
            | {"preview_scope", "pricing:list_price"}
        )
        if question_id not in valid:
            raise ValueError("未知问题编号")
        item = {
            "answer": answer.strip()[:2000],
            "reviewer": reviewer.strip()[:80],
            "at": utc_now(),
            "provenance": "HUMAN_VERIFIED",
        }
        if question_id == "preview_scope":
            import re

            selection = {}
            for entry in answer.replace("，", ",").split(","):
                match = re.fullmatch(r"\s*(F\d{4}):(\d+)\s*", entry)
                if not match or int(match[2]) < 1:
                    raise ValueError("格式应为 F0001:1,F0002:2，页/图序号从1开始。")
                selection.setdefault(match[1], []).append(int(match[2]))
            item["selection"] = selection
        if question_id == "pricing:list_price":
            from decimal import Decimal, InvalidOperation

            try:
                amount = Decimal(answer)
                if (
                    not amount.is_finite()
                    or amount <= 0
                    or amount.as_tuple().exponent < -2
                ):
                    raise ValueError()
            except (ValueError, InvalidOperation):
                raise ValueError("人工挂牌价请填写正数金额，最多两位小数。")
            item["answer"] = str(amount)
        answers = self._read(package / "reports/human_answers.json") or {}
        answers[question_id] = item
        write_json(package / "reports/human_answers.json", answers)
        product_path = package / "product.json"
        product = ProductDocument.model_validate(self._read(product_path))
        product.review = {
            "requires_reprocess": True,
            "reason": "人工回答已更新，须重新处理以刷新档案、目录和买家卡。",
        }
        product.quality_gate.update(
            status=PackageStatus.NEEDS_MANUAL_REVIEW.value, approval_enabled=False
        )
        self._save_outputs(
            package,
            product,
            SourceInventory.model_validate(
                self._read(package / "reports/source_inventory.json")
            ),
            self._read(package / "reports/quality_report.json") or {},
            self._product_redactor(product),
        )
        self.database.update_package(
            package_id,
            PackageStatus.NEEDS_MANUAL_REVIEW,
            "answer_saved_reprocess_required",
        )
        append_audit(
            package / "reports/audit_log.jsonl",
            "human_answer_saved",
            {"question_id": question_id},
        )

    @staticmethod
    def _product_redactor(product):
        return Redactor(
            [str(v.value or "") for v in product.seller.values()]
            + [str(product.course.get("teacher", SourcedValue()).value or "")]
        )

    def review(
        self,
        package_id: str,
        status: PackageStatus,
        reviewer: str,
        note: str,
        *,
        confirmations=None,
    ) -> None:
        allowed = {
            PackageStatus.NEEDS_SELLER_CONFIRMATION,
            PackageStatus.NEEDS_MANUAL_REVIEW,
            PackageStatus.REJECTED,
            PackageStatus.APPROVED,
        }
        if status not in allowed:
            raise ValueError("不支持的审核状态")
        if not reviewer.strip() or self._processing.locked():
            raise ValueError("必须填写审核人，且当前任务不能处于处理阶段。")
        package = self._package_path(package_id)
        product = ProductDocument.model_validate(self._read(package / "product.json"))
        confirmations = confirmations or {}
        if status == PackageStatus.APPROVED:
            if product.review.get("requires_reprocess") or not product.quality_gate.get(
                "approval_enabled"
            ):
                raise ValueError(
                    "仍有阻断项："
                    + "；".join(product.quality_gate.get("hard_blocks", ["须重新处理"]))
                )
            required = {
                "privacy",
                "previews",
                "authorization",
                "price",
                "description",
                "warnings",
            }
            if not all(confirmations.get(key) is True for key in required):
                raise ValueError(
                    "请逐项完成人工核验：隐私、样图、授权、价格、描述及风险处理。"
                )
            if not note.strip():
                raise ValueError("请填写人工审核依据/风险处理说明。")
            self._verify_originals(
                package, self._read(package / "reports/original_manifest.json")
            )
            for row in [
                *product.privacy.get("items", []),
                *product.preview.get("items", []),
            ]:
                relative = row.get("processed_file") or row.get("path")
                if relative:
                    target = (package / relative).resolve()
                    if (
                        not target.is_relative_to(package.resolve())
                        or not target.is_file()
                        or sha256_file(target) != row.get("sha256")
                    ):
                        raise ValueError("审核产物已改变或缺失，请重新处理。")
        product.quality_gate["status"] = status.value
        product.review = {
            "reviewer": reviewer.strip()[:80],
            "note": note[:1000],
            "at": utc_now(),
            "confirmations": confirmations,
            "run_id": product.quality_gate.get("run_id"),
            "provenance": "HUMAN_VERIFIED",
        }
        self._save_outputs(
            package,
            product,
            SourceInventory.model_validate(
                self._read(package / "reports/source_inventory.json")
            ),
            self._read(package / "reports/quality_report.json") or {},
            self._product_redactor(product),
        )
        self.database.update_package(package_id, status, "human_reviewed")
        append_audit(
            package / "reports" / "audit_log.jsonl",
            "human_review",
            {
                "status": status.value,
                "reviewed_at": utc_now(),
                "run_id": product.quality_gate.get("run_id"),
            },
        )
