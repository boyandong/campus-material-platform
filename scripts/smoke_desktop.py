"""Native desktop acceptance with synthetic local inputs and NO API key/network."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docx import Document

from workbench import desktop
from workbench.config import Settings


def main():
    import tkinter as tk

    from PIL import ImageGrab

    sys.stdout.reconfigure(encoding="utf-8")
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="desktop-acceptance-", dir=work))
    source = target / "source"
    source.mkdir()
    (source / "课程笔记.txt").write_text(
        "第一章 数据结构\n" + "线性结构和树形结构是课程的基础内容。" * 30,
        encoding="utf-8",
    )
    document = Document()
    for line in [
        "课程名称：匿名演示课程",
        "学院：演示学院",
        "专业：演示专业",
        "年份：2026",
        "文件数量：1",
        "完整情况：部分资料",
        "资料类型：学习笔记",
        "预览授权：允许",
        "预览范围：仅脱敏部分预览",
        "最低到手价：20元",
    ]:
        document.add_paragraph(line)
    questionnaire = target / "questionnaire.docx"
    document.save(questionnaire)
    data = target / "data"
    data.mkdir()
    desktop.settings = Settings(
        target,
        data,
        target / "tasks.sqlite",
        None,
        "https://api.deepseek.com",
        "deepseek-v4-flash",
    )
    desktop.enable_dpi_awareness()
    root = tk.Tk()
    root.title("工作台匿名验收")
    app = desktop.WorkbenchDesktop(root)
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(
        kind.__name__
    )
    dialogs = []
    desktop.messagebox.showinfo = lambda *args, **kwargs: dialogs.append(args)
    desktop.messagebox.showwarning = lambda *args, **kwargs: errors.append(args)
    desktop.messagebox.showerror = lambda *args, **kwargs: errors.append(args)
    app.questionnaire_path.set(str(questionnaire))
    app.source_path.set(str(source))
    app._create_package()

    def finish():
        deadline = time.monotonic() + 45
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        assert not app.busy and not errors, errors

    finish()
    pid = app.active_package_id
    assert pid
    app.reviewer.set("Synthetic Reviewer")
    app.question_choice.set("field:year")
    app.answer_value.set("2025")
    app._save_answer()
    finish()
    product = json.loads((data / pid / "product.json").read_text(encoding="utf-8"))
    assert product["course"]["year"]["value"] == "2025"
    assert product["quality_gate"]["approval_enabled"], product["quality_gate"]
    for variable in app.confirmations.values():
        variable.set(True)
    app.review_note.insert(
        "1.0",
        "Synthetic acceptance: reviewed all derived text and preview; no personal information.",
    )
    app._save_review(approve=True)
    assert app.database.get_package(pid)["status"] == "APPROVED", errors
    root.geometry("1280x820+10+10")
    root.attributes("-topmost", True)
    root.update()
    for label, tab in [
        ("reports", app.reports_tab),
        ("preview", app.preview_tab),
        ("review", app.review_tab),
    ]:
        app.tabs.select(tab)
        root.update()
        box = (
            root.winfo_rootx(),
            root.winfo_rooty(),
            root.winfo_rootx() + root.winfo_width(),
            root.winfo_rooty() + root.winfo_height(),
        )
        ImageGrab.grab(bbox=box).save(target / (label + ".png"))
    root.geometry("980x680+10+10")
    root.update()
    # Geometry acceptance: review action remains inside its panel at minimum supported size.
    assert (
        app.approve_button.winfo_rooty() + app.approve_button.winfo_height()
        <= root.winfo_rooty() + root.winfo_height()
    )
    assert not errors, errors
    app._close()
    print(
        json.dumps(
            {
                "passed": True,
                "checks": [
                    "create via desktop",
                    "reprocess human answer",
                    "preview",
                    "manual approval",
                    "no callback errors",
                    "980x680 action visible",
                ],
                "artifacts": str(target),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
