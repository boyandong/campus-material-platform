"""Conservative Chinese PII rules. Findings contain types/counts, never matched values."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

PATTERNS = {
    "PHONE": re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
    "EMAIL": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "ID_CARD": re.compile(r"(?<!\d)\d{17}[\dXx](?!\w)"),
    "STUDENT_ID": re.compile(
        r"(?:学号|学生编号|student\s*id)\s*[:：=|]?\s*([A-Za-z0-9-]{5,24})",
        re.IGNORECASE,
    ),
    "CONTACT": re.compile(
        r"(?:微信(?:号)?|QQ(?:号)?|WeChat|联系账号)\s*[:：=|]?\s*([A-Za-z0-9_@.\-]{5,80})",
        re.IGNORECASE,
    ),
    "NAME": re.compile(
        r"(?:姓名|学生姓名|作者|签名|Name)(?:\s*[:：=|]\s*|\s+)([\u4e00-\u9fff]{2,4}|[A-Za-z]+(?: [A-Za-z]+){0,2})",
        re.IGNORECASE,
    ),
    "ADDRESS": re.compile(
        r"(?:宿舍|住址|家庭地址|寝室|班级)\s*[:：=]\s*([^\n|，,；;]{2,60})"
    ),
    "LOCAL_PATH": re.compile(r"[A-Za-z]:[\\/][^\s\n，；]+"),
    "SECRET": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
}


class Redactor:
    def __init__(self, known_values: list[str] | None = None):
        self.known = {
            v.strip()
            for v in (known_values or [])
            if isinstance(v, str) and len(v.strip()) >= 2
        }

    def discover(self, text: str) -> None:
        for pattern in PATTERNS.values():
            for match in pattern.finditer(text):
                self.known.add(match.group(1) if match.lastindex else match.group())

    def spans(self, text: str) -> list[tuple[int, int, str]]:
        spans = [
            (m.start(), m.end(), kind)
            for kind, pattern in PATTERNS.items()
            for m in pattern.finditer(text)
        ]
        for value in self.known:
            spans.extend(
                (m.start(), m.end(), "KNOWN_PRIVATE_VALUE")
                for m in re.finditer(re.escape(value), text, re.IGNORECASE)
            )
        return sorted(set(spans))

    def clean(self, text: str) -> str:
        spans = self.spans(text)
        if not spans:
            return text
        merged = []
        for start, end, _ in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        for start, end in reversed(merged):
            text = text[:start] + "[已遮蔽]" + text[end:]
        return text

    def findings(self, text: str) -> dict[str, int]:
        return dict(Counter(kind for _, _, kind in self.spans(text)))

    def clean_object(self, value: Any):
        if isinstance(value, str):
            return self.clean(value)
        if isinstance(value, list):
            return [self.clean_object(item) for item in value]
        if isinstance(value, dict):
            return {key: self.clean_object(item) for key, item in value.items()}
        return value
