"""Create separate redacted derivatives, with explicit coverage limits and review gates."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image

from .content import XML_PARSER, Content
from .imaging import excerpt_image
from .storage import sha256_file


def _xml_copy(data: bytes, redactor) -> bytes:
    root = etree.fromstring(data, XML_PARSER)
    # Drop comments and deleted revision text; retain inserted visible text, not author metadata.
    for node in list(
        root.xpath(
            '//*[local-name()="del" or local-name()="commentRangeStart" or local-name()="commentRangeEnd" or local-name()="commentReference"]'
        )
    ):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    for paragraph in root.xpath('//*[local-name()="p" or local-name()="si"]'):
        leaves = paragraph.xpath('.//*[local-name()="t"]')
        full = "".join(node.text or "" for node in leaves)
        safe = redactor.clean(full)
        if full != safe and leaves:
            leaves[0].text = safe
            for node in leaves[1:]:
                node.text = ""
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        for attr in list(node.attrib):
            local = etree.QName(attr).localname.lower()
            if local in {"author", "initials", "date", "userId".lower(), "email"}:
                del node.attrib[attr]
            elif local not in {"id", "r", "s", "t", "type", "target"}:
                node.attrib[attr] = redactor.clean(node.attrib[attr])
        if node.text:
            node.text = redactor.clean(node.text)
    # A redacted numeric XLSX value must become text, not an invalid numeric cell.
    for cell in root.xpath('//*[local-name()="c"]'):
        values = cell.xpath('./*[local-name()="v"]')
        if values and "[已遮蔽]" in (values[0].text or ""):
            cell.set("t", "str")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def redact_sources(
    source_root: Path,
    output: Path,
    inventory,
    contents: dict[str, Content],
    image_processor,
    *,
    max_pdf_pages=60,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    redactor = image_processor.redactor
    # Learn explicit labels across the whole package before any output is made.
    for content in contents.values():
        redactor.discover(content.text)
        for value in content.metadata.values():
            if isinstance(value, str) and 2 <= len(value.strip()) <= 80:
                redactor.known.add(value.strip())
    for source in inventory.items:
        redactor.discover(source.relative_path)
    items, candidates = [], []

    def raster(image, file_id, ordinal, kind):
        safe, report, text = image_processor.process(image)
        target = output / f"{file_id}-image-{ordinal:03d}.png"
        safe.save(target, format="PNG")
        candidates.append(
            {
                "file_id": file_id,
                "ordinal": ordinal,
                "kind": kind,
                "path": str(target),
                "quality": report["quality"],
                "score": (report.get("vision") or {}).get("representative_score", 0.5),
                "sha256": sha256_file(target),
            }
        )
        return safe, report, text

    for number, source in enumerate(inventory.items, 1):
        file_id = f"F{number:04d}"
        original = source_root / source.relative_path
        content = contents.get(source.relative_path, Content())
        row = {
            "file_id": file_id,
            "status": "NEEDS_REVIEW",
            "processed_file": None,
            "findings": redactor.findings(source.relative_path + "\n" + content.text),
            "metadata_removed": bool(content.metadata),
            "images": [],
            "errors": [],
            "manual_checks": [
                "姓名/学号漏检",
                "手写/签名/人像/二维码",
                "脱敏后内容可读性",
            ],
        }
        try:
            if source.status != "READABLE":
                raise ValueError("SOURCE_NOT_READABLE_OR_UNSUPPORTED")
            if content.warnings:
                raise ValueError("INCOMPLETE_CONTENT_COVERAGE")
            target = output / (file_id + source.extension)
            if source.extension in {".png", ".jpg", ".jpeg"}:
                with Image.open(original) as image:
                    safe, report, ocr_text = raster(image, file_id, 1, "image")
                target = output / (file_id + ".png")
                safe.save(target, format="PNG")
                row["images"].append(report)
                content.text = ocr_text
                content.stats.update(
                    characters=len(ocr_text), image_quality=report["quality"]
                )
            elif source.extension == ".pdf":
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(original))
                pages = []
                try:
                    if len(pdf) > max_pdf_pages:
                        raise ValueError("PDF_PAGE_LIMIT_REQUIRES_SPLIT")
                    texts = []
                    for index in range(len(pdf)):
                        page = pdf[index]
                        bitmap = page.render(scale=min(2, 2200 / max(page.get_size())))
                        image = bitmap.to_pil().copy()
                        bitmap.close()
                        page.close()
                        safe, report, ocr_text = raster(
                            image, file_id, index + 1, "pdf_page"
                        )
                        pages.append(safe)
                        texts.append(ocr_text)
                        row["images"].append(report)
                    if not pages:
                        raise ValueError("EMPTY_PDF")
                    pages[0].save(
                        target, format="PDF", save_all=True, append_images=pages[1:]
                    )
                    row["metadata_removed"] = True
                    row["rasterized_pdf"] = True
                    if len(content.text.strip()) < 30:
                        content.text = "\n".join(texts)
                        content.stats["characters"] = len(content.text)
                    if row["images"] and all(
                        r["quality"] in {"blank", "suspected_empty_grid"}
                        for r in row["images"]
                    ):
                        content.stats["image_quality"] = "suspected_empty_grid"
                finally:
                    pdf.close()
                    for page_image in pages:
                        page_image.close()
            elif source.extension in {".docx", ".pptx", ".xlsx"}:
                with (
                    zipfile.ZipFile(original) as archive,
                    zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as result,
                ):
                    names = archive.namelist()
                    removed = {
                        name
                        for name in names
                        if name.startswith(("docProps/", "customXml/"))
                        or "comment" in name.lower()
                        or "/printerSettings/" in name
                        or name.endswith(".vml")
                    }
                    if any(
                        "/embeddings/" in name
                        or "vbaProject" in name
                        or (name.endswith(".bin") and name not in removed)
                        for name in names
                    ):
                        raise ValueError("EMBEDDED_OBJECT_REQUIRES_MANUAL_EXPORT")
                    if source.extension == ".xlsx" and "xl/workbook.xml" in names:
                        xml = etree.fromstring(
                            archive.read("xl/workbook.xml"), XML_PARSER
                        )
                        if any(
                            redactor.spans(n.get("name", ""))
                            for n in xml.xpath('//*[local-name()="sheet"]')
                        ):
                            raise ValueError(
                                "PRIVATE_SHEET_NAMES_REQUIRE_MANUAL_EXPORT"
                            )
                    ordinal = 0
                    for name in names:
                        if name in removed:
                            continue
                        data = archive.read(name)
                        if "/media/" in name and not name.endswith("/"):
                            ordinal += 1
                            with Image.open(io.BytesIO(data)) as image:
                                safe, report, _ = raster(
                                    image, file_id, ordinal, "embedded_image"
                                )
                            row["images"].append(report)
                            buffer = io.BytesIO()
                            fmt = (
                                "JPEG"
                                if Path(name).suffix.lower() in {".jpg", ".jpeg"}
                                else "PNG"
                            )
                            if Path(name).suffix.lower() not in {
                                ".jpg",
                                ".jpeg",
                                ".png",
                            }:
                                raise ValueError("UNSUPPORTED_EMBEDDED_IMAGE")
                            safe.save(buffer, format=fmt)
                            data = buffer.getvalue()
                        elif name.endswith(".rels"):
                            xml = etree.fromstring(data, XML_PARSER)
                            for node in list(xml):
                                rel_type = node.get("Type", "").lower()
                                if node.get("TargetMode") == "External" or any(
                                    token in rel_type
                                    for token in (
                                        "comment",
                                        "metadata",
                                        "customxml",
                                        "extended-properties",
                                        "custom-properties",
                                        "printersettings",
                                        "vmldrawing",
                                    )
                                ):
                                    xml.remove(node)
                            data = etree.tostring(
                                xml, xml_declaration=True, encoding="UTF-8"
                            )
                        elif name == "[Content_Types].xml":
                            xml = etree.fromstring(data, XML_PARSER)
                            for node in list(xml):
                                if node.get("PartName", "").lstrip("/") in removed:
                                    xml.remove(node)
                            data = etree.tostring(
                                xml, xml_declaration=True, encoding="UTF-8"
                            )
                        elif name.endswith(".xml"):
                            data = _xml_copy(data, redactor)
                        result.writestr(name, data)
                row["metadata_removed"] = True
            else:
                target = output / (file_id + ".txt")
                target.write_text(redactor.clean(content.text), encoding="utf-8")
            # A structured snippet is deliberately not a screenshot or a complete answer.
            if not row["images"] and content.text.strip():
                lines = (
                    content.headings
                    or [line for line in content.text.splitlines() if line.strip()][:4]
                )
                image = excerpt_image([redactor.clean(line) for line in lines])
                excerpt = output / f"{file_id}-excerpt.png"
                image.save(excerpt)
                candidates.append(
                    {
                        "file_id": file_id,
                        "ordinal": 1,
                        "kind": "structured_excerpt",
                        "path": str(excerpt),
                        "quality": "readable",
                        "score": 0.3,
                        "sha256": sha256_file(excerpt),
                    }
                )
            if any(
                any(w.startswith("OCR_FAILED") for w in r["warnings"])
                for r in row["images"]
            ):
                row["errors"].append("OCR_COVERAGE_FAILED")
            row["processed_file"] = str(target)
            row["sha256"] = sha256_file(target)
        except Exception as exc:  # noqa: BLE001 -- isolate each derivative and block failed coverage
            # No source text, contact details or local paths in error logs.
            code = (
                str(exc)
                if isinstance(exc, ValueError) and re.fullmatch("[A-Z_]+", str(exc))
                else type(exc).__name__
            )
            row["errors"].append(code)
        if row["errors"]:
            row["status"] = "BLOCKED"
        items.append(row)
    blocked_ids = {row["file_id"] for row in items if row["status"] == "BLOCKED"}
    return {
        "schema_version": "2.0",
        "items": items,
        "blocked_files": len(blocked_ids),
        "status": "BLOCKED" if blocked_ids else "NEEDS_REVIEW",
        "candidates": [c for c in candidates if c["file_id"] not in blocked_ids],
        "vision_calls": image_processor.calls,
        "disclaimer": "规则和 OCR 不能证明零隐私风险；全部衍生文件仅为本地草稿，需逐文件人工复核。",
    }
