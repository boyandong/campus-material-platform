from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Provenance(str, Enum):
    SELLER_DECLARED = "SELLER_DECLARED"
    FILE_VERIFIED = "FILE_VERIFIED"
    BUYER_VERIFIED = "BUYER_VERIFIED"
    SYSTEM_CALCULATED = "SYSTEM_CALCULATED"
    INFERRED = "INFERRED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    UNKNOWN = "UNKNOWN"


class PackageStatus(str, Enum):
    CREATED = "CREATED"
    COPYING_INPUTS = "COPYING_INPUTS"
    PARSING_QUESTIONNAIRE = "PARSING_QUESTIONNAIRE"
    SCANNING_FILES = "SCANNING_FILES"
    COMPARING = "COMPARING"
    BUILDING_PRODUCT = "BUILDING_PRODUCT"
    GENERATING_CARD = "GENERATING_CARD"
    NEEDS_SELLER_CONFIRMATION = "NEEDS_SELLER_CONFIRMATION"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    QUALITY_CHECK = "QUALITY_CHECK"
    PRIVACY_SCAN = "PRIVACY_SCAN"
    GENERATING_PREVIEWS = "GENERATING_PREVIEWS"
    PRICING = "PRICING"
    APPROVED = "APPROVED"


FINAL_REVIEW_STATUSES = {
    PackageStatus.NEEDS_SELLER_CONFIRMATION,
    PackageStatus.NEEDS_MANUAL_REVIEW,
    PackageStatus.REJECTED,
}


class SourcedValue(BaseModel):
    value: Any = None
    raw_value: str | None = None
    provenance: Provenance = Provenance.UNKNOWN
    source_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    verified_by: str | None = None
    verified_at: str | None = None


class QuestionnaireField(BaseModel):
    key: str
    label: str
    value: str | list[str] | None = None
    raw_value: str | None = None
    provenance: Provenance = Provenance.UNKNOWN
    source_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    verified_by: str | None = None
    verified_at: str | None = None


class QuestionnaireReport(BaseModel):
    schema_version: str = "1.0"
    source_sha256: str
    parsed_at: str = Field(default_factory=utc_now)
    fields: dict[str, QuestionnaireField]
    unknown_fields: list[str] = Field(default_factory=list)
    parser_warnings: list[str] = Field(default_factory=list)


class FileInventoryItem(BaseModel):
    relative_path: str
    sha256: str
    size_bytes: int
    extension: str
    status: str
    error: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    detected_material_type: str | None = None


class SourceInventory(BaseModel):
    schema_version: str = "1.0"
    scanned_at: str = Field(default_factory=utc_now)
    root_sha256: str
    total_files: int
    readable_files: int
    unsupported_files: int
    failed_files: int
    items: list[FileInventoryItem]
    warnings: list[str] = Field(default_factory=list)


class Conflict(BaseModel):
    code: str
    severity: str
    message: str
    seller_value: Any = None
    detected_value: Any = None
    source_refs: list[str] = Field(default_factory=list)
    suggested_question: str | None = None


class ComparisonReport(BaseModel):
    schema_version: str = "1.0"
    compared_at: str = Field(default_factory=utc_now)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommended_status: PackageStatus = PackageStatus.NEEDS_MANUAL_REVIEW


class ProductDocument(BaseModel):
    schema_version: str = "2.0"
    product_id: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    seller: dict[str, SourcedValue]
    course: dict[str, SourcedValue]
    materials: dict[str, SourcedValue]
    quality: dict[str, SourcedValue]
    compatibility: dict[str, SourcedValue]
    authorization: dict[str, SourcedValue]
    pricing: dict[str, SourcedValue]
    historical_result: dict[str, SourcedValue]
    warnings: list[str]
    unanswered_questions: list[str]
    quality_gate: dict[str, Any]
    artifacts: dict[str, str]
    privacy: dict[str, Any] = Field(default_factory=dict)
    preview: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)
    questions: list[dict[str, Any]] = Field(default_factory=list)


class VisionRegion(BaseModel):
    kind: str = Field(max_length=80)
    box: tuple[float, float, float, float]


class VisionAssessment(BaseModel):
    quality: Literal["blank", "blurred", "readable", "unknown"]
    content_type: str = Field(max_length=120)
    privacy_regions: list[VisionRegion] = Field(default_factory=list)
    representative_score: float = Field(default=0, ge=0, le=1)
    confidence: float = Field(default=0, ge=0, le=1)


class SemanticClassification(BaseModel):
    normalized_material_types: list[str] = Field(default_factory=list)
    material_summary: str | None = None
    catalog_outline: list[str] = Field(default_factory=list)
    pricing_suggestion: str | None = None
    compatibility_summary: str | None = None
    buyer_warning_summary: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class AdvancedReview(BaseModel):
    risk_level: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    conflict_summary: str
    recommended_actions: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    confidence: float = Field(default=0.0, ge=0, le=1)


class ReviewRequest(BaseModel):
    status: PackageStatus
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
