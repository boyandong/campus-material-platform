"""Opt-in live checks using only synthetic text/images; never print credentials."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.config import settings
from workbench.deepseek import DeepSeekProvider
from workbench.imaging import chinese_font


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inference",
        action="store_true",
        help="Small paid synthetic Flash and conflict-review calls",
    )
    parser.add_argument(
        "--vision", action="store_true", help="Small paid synthetic image call"
    )
    parser.add_argument(
        "--report", type=Path, help="Optional sanitized JSON diagnostics output"
    )
    args = parser.parse_args()
    provider = DeepSeekProvider(settings)
    try:
        result = {"connection": provider.check_connection()}
        if args.inference:
            value, warning = provider.classify(
                {
                    "course_name": "合成测试课程",
                    "content_summary": "匿名测试：第一章数据结构概念，不含个人信息。",
                }
            )
            result["flash"] = {"ok": value is not None, "warning": warning}
            value, warning = provider.advanced_review(
                {
                    "trigger": "synthetic_information_conflict",
                    "seller_claim": "3份完整材料",
                    "detected_facts": "1份内容，2份空模板",
                    "synthetic": True,
                }
            )
            result["pro"] = {"ok": value is not None, "warning": warning}
        if args.vision:
            from PIL import Image, ImageDraw

            image = Image.new("RGB", (600, 300), "white")
            ImageDraw.Draw(image).text(
                (40, 80),
                "匿名合成测试：第一章 数据结构",
                font=chinese_font(28),
                fill="black",
            )
            value, warning = provider.assess_image(image)
            result["vision"] = {"ok": value is not None, "warning": warning}
        if args.report:
            from workbench.storage import write_json

            write_json(args.report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        provider.close()


if __name__ == "__main__":
    main()
