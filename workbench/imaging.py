"""RapidOCR adapter + deterministic raster redaction. No AI-generated pixels."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat

from .privacy import Redactor


class LocalOCR:
    def __init__(self, cache: Path):
        self.cache = cache
        self.engine = None
        self.error = None
        self.lock = threading.Lock()

    def read(self, image: Image.Image) -> list[dict]:
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            if self.engine is None:
                try:
                    from rapidocr import RapidOCR

                    self.cache.mkdir(parents=True, exist_ok=True)
                    self.engine = RapidOCR(
                        params={
                            "Global.model_root_dir": str(self.cache),
                            "Global.log_level": "error",
                            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                        }
                    )
                except Exception as exc:
                    self.error = type(exc).__name__
                    raise
            result = self.engine(np.asarray(image.convert("RGB")))
            if result.boxes is None:
                return []
            return [
                {
                    "text": text,
                    "box": np.asarray(box).tolist(),
                    "confidence": float(score),
                }
                for box, text, score in zip(result.boxes, result.txts, result.scores)
            ]


class ImageProcessor:
    def __init__(
        self, ocr, redactor: Redactor, provider=None, *, allow_cloud=False, max_calls=5
    ):
        self.ocr, self.redactor, self.provider = ocr, redactor, provider
        self.allow_cloud, self.max_calls, self.calls = allow_cloud, max_calls, 0

    def process(self, image: Image.Image) -> tuple[Image.Image, dict, str]:
        image = ImageOps.exif_transpose(image).convert("RGB")
        # Bounded raster; originals remain byte-for-byte unchanged.
        image.thumbnail((2800, 2800))
        image.info.clear()
        draw = ImageDraw.Draw(image)
        gray = image.convert("L")
        variance = ImageStat.Stat(gray).var[0]
        warnings, rows, text = [], [], ""
        quality = "blank" if variance < 2 else "readable"
        if min(image.size) < 200:
            quality = "low_resolution"
        try:
            import cv2

            sharpness = float(cv2.Laplacian(np.asarray(gray), cv2.CV_64F).var())
            if variance >= 2 and sharpness < 12:
                quality = "blurred"
        except ImportError:
            sharpness = None
        try:
            rows = self.ocr.read(image)
            text = "\n".join(row["text"] for row in rows)
            self.redactor.discover(text)
        except Exception as exc:  # noqa: BLE001 -- OCR coverage failure blocks approval
            warnings.append("OCR_FAILED:" + type(exc).__name__)
        grid = {"estimated_cells": 0, "occupied_cells": 0}
        try:
            import cv2

            binary = cv2.threshold(np.asarray(gray), 180, 255, cv2.THRESH_BINARY_INV)[1]
            horizontal = cv2.morphologyEx(
                binary,
                cv2.MORPH_OPEN,
                np.ones((1, max(30, image.width // 8)), np.uint8),
            )
            vertical = cv2.morphologyEx(
                binary,
                cv2.MORPH_OPEN,
                np.ones((max(30, image.height // 8), 1), np.uint8),
            )

            def centers(indices):
                groups = []
                for value in indices:
                    if not groups or value - groups[-1][-1] > 3:
                        groups.append([int(value)])
                    else:
                        groups[-1].append(int(value))
                return [sum(g) / len(g) for g in groups]

            ys = centers(
                np.flatnonzero((horizontal > 0).sum(axis=1) > image.width * 0.3)
            )
            xs = centers(
                np.flatnonzero((vertical > 0).sum(axis=0) > image.height * 0.3)
            )
            if 3 <= len(xs) <= 30 and 3 <= len(ys) <= 80:
                occupied = set()
                for row in rows:
                    points = np.asarray(row["box"])
                    cx, cy = points.mean(axis=0)
                    for x in range(len(xs) - 1):
                        for y in range(len(ys) - 1):
                            if xs[x] < cx < xs[x + 1] and ys[y] < cy < ys[y + 1]:
                                occupied.add((x, y))
                grid = {
                    "estimated_cells": (len(xs) - 1) * (len(ys) - 1),
                    "occupied_cells": len(occupied),
                }
                if grid["occupied_cells"] / grid["estimated_cells"] < 0.25:
                    quality = "suspected_empty_grid"
                    warnings.append("GRID_MOSTLY_EMPTY_INFERRED")
        except (ImportError, ValueError):
            pass
        spans = self.redactor.spans(text)
        offset, masked = 0, 0
        for row in rows:
            end = offset + len(row["text"])
            if any(start < end and stop > offset for start, stop, _ in spans):
                xs, ys = zip(*row["box"])
                box = (
                    max(0, min(xs) - 4),
                    max(0, min(ys) - 4),
                    min(image.width, max(xs) + 4),
                    min(image.height, max(ys) + 4),
                )
                draw.rectangle(box, fill="black")
                masked += 1
            if row["confidence"] < 0.65:
                warnings.append("LOW_OCR_CONFIDENCE")
            offset = end + 1
        # QR detection is local; signature/portrait/handwriting still require manual review.
        try:
            import cv2

            found, points = cv2.QRCodeDetector().detectMulti(np.asarray(image))
            if found and points is not None:
                for points_row in points:
                    xs, ys = points_row[:, 0], points_row[:, 1]
                    draw.rectangle(
                        (min(xs) - 6, min(ys) - 6, max(xs) + 6, max(ys) + 6),
                        fill="black",
                    )
                    masked += 1
        except Exception:  # noqa: BLE001 -- optional QR detector, manual check remains mandatory
            warnings.append("QR_SCAN_UNAVAILABLE")
        vision = None
        if self.allow_cloud and self.provider and self.calls < self.max_calls:
            self.calls += 1
            vision, warning = self.provider.assess_image(image)
            if warning:
                warnings.append(warning)
            if vision:
                for region in vision.privacy_regions:
                    x0, y0, x1, y1 = region.box
                    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                        warnings.append("INVALID_VISION_REGION")
                        continue
                    draw.rectangle(
                        (
                            max(0, x0 * image.width - 6),
                            max(0, y0 * image.height - 6),
                            min(image.width, x1 * image.width + 6),
                            min(image.height, y1 * image.height + 6),
                        ),
                        fill="black",
                    )
                    masked += 1
        return (
            image,
            {
                "quality": quality,
                "size": list(image.size),
                "sharpness": sharpness,
                "ocr_lines": len(rows),
                "masked_regions": masked,
                "grid": grid,
                "findings": self.redactor.findings(text),
                "warnings": sorted(set(warnings)),
                "vision": vision.model_dump(mode="json") if vision else None,
                "manual_review_required": True,
                "orientation": "EXIF_NORMALIZED; non-EXIF rotation requires manual review",
                "note": "OCR/视觉可能漏检人像、签名、手写和二维码；输出仅为脱敏草稿。",
            },
            self.redactor.clean(text),
        )


def chinese_font(size=24):
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def excerpt_image(lines: list[str]) -> Image.Image:
    """A labelled structured excerpt, never presented as a real Word page screenshot."""
    image = Image.new("RGB", (1000, 750), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (40, 25), "结构化文字摘录 · 非原页排版", font=chinese_font(26), fill="#333333"
    )
    y = 85
    for line in lines[:7]:
        for start in range(0, min(len(line), 100), 32):
            draw.text(
                (40, y), line[start : start + 32], font=chinese_font(24), fill="#222222"
            )
            y += 42
            if y > 650:
                return image
    return image


def preview_image(source: Path, target: Path) -> str:
    with Image.open(source) as image:
        image = image.convert("RGB")
        # Only a partial strip; never export a full report page as a preview.
        image = image.crop((0, 0, image.width, max(1, int(image.height * 0.38))))
        image.thumbnail((1000, 550))
    canvas = Image.new("RGB", (image.width, image.height + 64), "white")
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (12, image.height + 12),
        "学习参考预览 · 待人工确认",
        font=chinese_font(22),
        fill="#9b2929",
    )
    for y in range(45, image.height, 130):
        draw.text(
            (max(8, image.width // 4), y),
            "学习参考预览",
            font=chinese_font(30),
            fill="#bb7777",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG")
    return hashlib.sha256(target.read_bytes()).hexdigest()
