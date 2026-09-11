from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import settings
from .database import Database
from .deepseek import DeepSeekProvider
from .models import PackageStatus
from .pipeline import WorkbenchPipeline

STATUS_LABELS = {
    "QUALITY_CHECK": "内容检查",
    "PRIVACY_SCAN": "隐私扫描与脱敏",
    "GENERATING_PREVIEWS": "生成授权样图",
    "PRICING": "计算价格草稿",
    "APPROVED": "已人工入库",
    "CREATED": "待处理",
    "COPYING_INPUTS": "复制原件",
    "PARSING_QUESTIONNAIRE": "解析问卷",
    "SCANNING_FILES": "扫描文件",
    "COMPARING": "对照声明",
    "BUILDING_PRODUCT": "生成产品档案",
    "GENERATING_CARD": "生成买家卡",
    "NEEDS_SELLER_CONFIRMATION": "需卖家确认",
    "NEEDS_MANUAL_REVIEW": "需人工复核",
    "REJECTED": "已拒绝",
    "FAILED": "失败",
    "INTERRUPTED": "已中断",
}


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class WorkbenchDesktop:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("课程学习资料商品化智能工作台")
        self.root.geometry("1280x820")
        self.root.minsize(980, 680)
        self.database = Database(settings.db_path)
        self.provider = DeepSeekProvider(settings)
        self.pipeline = WorkbenchPipeline(
            settings.data_root, self.database, self.provider
        )
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.active_package_id: str | None = None
        self.questionnaire_path = tk.StringVar()
        self.source_path = tk.StringVar()
        self.source_kind = tk.StringVar(value="folder")
        self.status_message = tk.StringVar(value="就绪")
        self.detail_status = tk.StringVar(value="未选择资料包")
        self.review_status = tk.StringVar(value=PackageStatus.NEEDS_MANUAL_REVIEW.value)
        self.reviewer = tk.StringVar()
        self.cloud_images = tk.BooleanVar(value=False)
        self.busy = False
        self.loaded_signature = None
        self.gate_message = tk.StringVar(
            value="所有输出先为本地草稿；人工确认后才能入库，不会自动发布。"
        )
        self.confirmations = {
            key: tk.BooleanVar(value=False)
            for key in (
                "privacy",
                "previews",
                "authorization",
                "price",
                "description",
                "warnings",
            )
        }
        self.report_choice = tk.StringVar(value="内容质量")
        self.question_choice = tk.StringVar()
        self.answer_value = tk.StringVar()
        self.preview_selection = tk.StringVar()
        self._configure_style()
        self._build_ui()
        self._refresh_packages()
        self._drain_events()
        self.root.after(1500, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_style(self) -> None:
        style = ttk.Style()
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure("Accent.TLabel", foreground="#315efb")
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="课程资料智能工作台", style="Title.TLabel").pack(
            side="left"
        )
        self.connection_button = ttk.Button(
            header, text="测试 DeepSeek 连接", command=self._check_connection
        )
        self.connection_button.pack(side="right")
        ttk.Label(header, text="本地桌面 · 无自动发布", style="Muted.TLabel").pack(
            side="right", padx=15
        )

        input_box = ttk.LabelFrame(outer, text="新建资料包", padding=12)
        input_box.pack(fill="x", pady=(0, 14))
        input_box.columnconfigure(1, weight=1)
        ttk.Label(input_box, text="卖家问卷（DOCX）").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=5
        )
        ttk.Entry(
            input_box, textvariable=self.questionnaire_path, state="readonly"
        ).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(input_box, text="选择问卷", command=self._choose_questionnaire).grid(
            row=0, column=2, padx=(8, 0), pady=5
        )

        source_type = ttk.Frame(input_box)
        source_type.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Radiobutton(
            source_type,
            text="资料文件夹",
            variable=self.source_kind,
            value="folder",
            command=self._clear_source,
        ).pack(side="left")
        ttk.Radiobutton(
            source_type,
            text="ZIP",
            variable=self.source_kind,
            value="zip",
            command=self._clear_source,
        ).pack(side="left", padx=(8, 0))
        ttk.Entry(input_box, textvariable=self.source_path, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=5
        )
        ttk.Button(input_box, text="选择资料", command=self._choose_source).grid(
            row=1, column=2, padx=(8, 0), pady=5
        )

        actions = ttk.Frame(input_box)
        ttk.Checkbutton(
            input_box,
            variable=self.cloud_images,
            text=f"本次允许图片发给 DeepSeek Vision（本地初筛仍可能漏检隐私，最多{settings.max_image_calls}张；默认仅本地 OCR）",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(actions, textvariable=self.status_message, style="Muted.TLabel").pack(
            side="left"
        )
        self.create_button = ttk.Button(
            actions, text="创建并开始处理", command=self._create_package
        )
        self.create_button.pack(side="right")

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)
        sidebar = ttk.Frame(body, padding=(0, 0, 12, 0))
        detail = ttk.Frame(body)
        body.add(sidebar, weight=1)
        body.add(detail, weight=3)

        sidebar_header = ttk.Frame(sidebar)
        sidebar_header.pack(fill="x", pady=(0, 8))
        ttk.Label(sidebar_header, text="资料包", style="Heading.TLabel").pack(
            side="left"
        )
        ttk.Button(sidebar_header, text="刷新", command=self._refresh_packages).pack(
            side="right"
        )
        self.package_tree = ttk.Treeview(
            sidebar, columns=("status",), show="tree headings", selectmode="browse"
        )
        self.package_tree.heading("#0", text="资料包 ID")
        self.package_tree.heading("status", text="状态")
        self.package_tree.column("#0", width=245, minwidth=205)
        self.package_tree.column("status", width=105, minwidth=90)
        self.package_tree.pack(fill="both", expand=True)
        self.package_tree.bind("<<TreeviewSelect>>", self._select_package)
        self.retry_button = ttk.Button(
            sidebar, text="重试 / 重新处理", command=self._retry_active
        )
        self.retry_button.pack(fill="x", pady=(8, 0))
        ttk.Button(sidebar, text="打开资料包文件夹", command=self._open_package).pack(
            fill="x", pady=5
        )

        detail_header = ttk.Frame(detail)
        detail_header.pack(fill="x", pady=(0, 8))
        ttk.Label(detail_header, text="人工审核", style="Heading.TLabel").pack(
            side="left"
        )
        ttk.Label(
            detail_header, textvariable=self.detail_status, style="Accent.TLabel"
        ).pack(side="right")
        gate = ttk.Label(
            detail,
            textvariable=self.gate_message,
            wraplength=670,
            foreground="#9a5b00",
            background="#fff4d6",
            padding=8,
        )
        gate.pack(fill="x", pady=(0, 8))

        self.tabs = ttk.Notebook(detail)
        self.tabs.pack(fill="both", expand=True)
        self.comparison_tab = ttk.Frame(self.tabs, padding=10)
        self.conflict_tab = ttk.Frame(self.tabs, padding=10)
        self.files_tab = ttk.Frame(self.tabs, padding=10)
        self.card_tab = ttk.Frame(self.tabs, padding=10)
        self.review_tab = ttk.Frame(self.tabs, padding=10)
        self.reports_tab = ttk.Frame(self.tabs, padding=10)
        self.preview_tab = ttk.Frame(self.tabs, padding=10)
        self.questions_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.comparison_tab, text="声明 / 检测")
        self.tabs.add(self.conflict_tab, text="冲突")
        self.tabs.add(self.files_tab, text="文件清单")
        self.tabs.add(self.card_tab, text="买家卡预览")
        self.tabs.add(self.reports_tab, text="检测报告")
        self.tabs.add(self.preview_tab, text="样图")
        self.tabs.add(self.questions_tab, text="补充核验")
        self.tabs.add(self.review_tab, text="人工结论")
        self._build_detail_tabs()

    def _build_detail_tabs(self) -> None:
        comparison_panes = ttk.Panedwindow(self.comparison_tab, orient="horizontal")
        comparison_panes.pack(fill="both", expand=True)
        declared_frame = ttk.LabelFrame(comparison_panes, text="卖家声明", padding=6)
        detected_frame = ttk.LabelFrame(comparison_panes, text="文件检测", padding=6)
        comparison_panes.add(declared_frame, weight=1)
        comparison_panes.add(detected_frame, weight=1)
        self.declared_tree = ttk.Treeview(
            declared_frame, columns=("value", "source"), show="headings"
        )
        for column, text, width in (("value", "内容", 260), ("source", "来源", 120)):
            self.declared_tree.heading(column, text=text)
            self.declared_tree.column(column, width=width)
        self.declared_tree.pack(fill="both", expand=True)
        self.detected_tree = ttk.Treeview(
            detected_frame, columns=("value",), show="tree headings"
        )
        self.detected_tree.heading("#0", text="检测项")
        self.detected_tree.heading("value", text="结果")
        self.detected_tree.column("#0", width=150)
        self.detected_tree.column("value", width=260)
        self.detected_tree.pack(fill="both", expand=True)

        self.conflict_text = tk.Text(
            self.conflict_tab,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            state="disabled",
        )
        self.conflict_text.pack(fill="both", expand=True)

        self.file_tree = ttk.Treeview(
            self.files_tab,
            columns=("format", "status", "size", "stats"),
            show="tree headings",
        )
        self.file_tree.heading("#0", text="相对路径")
        for column, text, width in (
            ("format", "格式", 70),
            ("status", "状态", 90),
            ("size", "大小", 90),
            ("stats", "基础统计", 360),
        ):
            self.file_tree.heading(column, text=text)
            self.file_tree.column(column, width=width)
        self.file_tree.column("#0", width=300)
        file_scroll = ttk.Scrollbar(
            self.files_tab, orient="vertical", command=self.file_tree.yview
        )
        self.file_tree.configure(yscrollcommand=file_scroll.set)
        self.file_tree.pack(side="left", fill="both", expand=True)
        file_scroll.pack(side="right", fill="y")

        self.card_text = tk.Text(
            self.card_tab,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            state="disabled",
        )
        self.card_text.pack(fill="both", expand=True)
        self.report_files = {
            "内容质量": "reports/quality_report.json",
            "隐私与脱敏": "reports/privacy_report.json",
            "价格建议": "reports/pricing_report.json",
            "重复与版本": "reports/version_comparison.json",
            "模型调用": "reports/model_calls.json",
            "完整审核": "reports/audit_report.md",
            "目录": "catalog.md",
        }
        selector = ttk.Combobox(
            self.reports_tab,
            textvariable=self.report_choice,
            values=list(self.report_files),
            state="readonly",
        )
        selector.pack(fill="x")
        selector.bind("<<ComboboxSelected>>", lambda _: self._show_report())
        self.report_text = tk.Text(
            self.reports_tab,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 10),
        )
        self.report_text.pack(fill="both", expand=True, pady=6)
        ttk.Label(
            self.preview_tab,
            text="仅展示部分内容；请核对授权、遮蔽区域和水印。原文件不受影响。",
            wraplength=650,
        ).pack(anchor="w")
        self.preview_combo = ttk.Combobox(
            self.preview_tab, textvariable=self.preview_selection, state="readonly"
        )
        self.preview_combo.pack(fill="x", pady=8)
        self.preview_combo.bind("<<ComboboxSelected>>", lambda _: self._show_preview())
        self.preview_label = ttk.Label(self.preview_tab)
        self.preview_label.pack(fill="both", expand=True)
        ttk.Label(
            self.questions_tab,
            text="可回答追问或修正字段。保存后需重新处理；旧回答保留来源与核验人，不覆盖原问卷。",
            wraplength=650,
        ).pack(anchor="w")
        self.question_combo = ttk.Combobox(
            self.questions_tab, textvariable=self.question_choice, state="readonly"
        )
        self.question_combo.pack(fill="x", pady=8)
        self.question_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._show_question()
        )
        self.question_text = tk.Text(
            self.questions_tab, height=5, wrap="word", state="disabled"
        )
        self.question_text.pack(fill="x", pady=5)
        ttk.Entry(self.questions_tab, textvariable=self.answer_value).pack(
            fill="x", pady=8
        )
        ttk.Label(
            self.questions_tab,
            text="核验人使用“人工结论”页的姓名。样图范围格式：F0001:1,F0002:2（必须在卖家授权内）。",
            wraplength=650,
        ).pack(anchor="w")
        ttk.Button(
            self.questions_tab, text="保存回答并重新处理", command=self._save_answer
        ).pack(anchor="e", pady=8)

        self.review_tab.columnconfigure(1, weight=1)
        ttk.Label(self.review_tab, text="审核结果").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Combobox(
            self.review_tab,
            textvariable=self.review_status,
            values=[
                PackageStatus.NEEDS_MANUAL_REVIEW.value,
                PackageStatus.NEEDS_SELLER_CONFIRMATION.value,
                PackageStatus.REJECTED.value,
                PackageStatus.APPROVED.value,
            ],
            state="readonly",
        ).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(self.review_tab, text="审核人").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(self.review_tab, textvariable=self.reviewer).grid(
            row=1, column=1, sticky="ew", pady=6
        )
        ttk.Label(self.review_tab, text="备注").grid(
            row=2, column=0, sticky="nw", padx=(0, 8), pady=6
        )
        self.review_note = tk.Text(
            self.review_tab, height=3, wrap="word", font=("Microsoft YaHei UI", 10)
        )
        self.review_note.grid(row=2, column=1, sticky="nsew", pady=6)
        self.review_tab.rowconfigure(2, weight=1)
        checks = ttk.Frame(self.review_tab)
        checks.grid(row=3, column=0, columnspan=2, sticky="ew")
        labels = {
            "privacy": "已逐文件检查隐私及脱敏副本",
            "previews": "已核对样图与水印",
            "authorization": "确认合法授权及展示范围",
            "price": "已核对价格和分成",
            "description": "描述无虚构/效果承诺",
            "warnings": "已处理黄色风险及未决事项",
        }
        for index, (key, label) in enumerate(labels.items()):
            ttk.Checkbutton(checks, text=label, variable=self.confirmations[key]).grid(
                row=index // 2, column=index % 2, sticky="w", pady=3
            )
        review_buttons = ttk.Frame(self.review_tab)
        review_buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.approve_button = ttk.Button(
            review_buttons,
            text="通过入库（仅本地）",
            state="disabled",
            command=lambda: self._save_review(approve=True),
        )
        self.approve_button.pack(side="left", padx=(0, 8))
        ttk.Button(review_buttons, text="保存人工结论", command=self._save_review).pack(
            side="left"
        )

    def _choose_questionnaire(self) -> None:
        path = filedialog.askopenfilename(
            title="选择卖家问卷", filetypes=[("Word 问卷", "*.docx")]
        )
        if path:
            self.questionnaire_path.set(path)

    def _clear_source(self) -> None:
        self.source_path.set("")

    def _choose_source(self) -> None:
        if self.source_kind.get() == "folder":
            path = filedialog.askdirectory(title="选择资料文件夹")
        else:
            path = filedialog.askopenfilename(
                title="选择资料 ZIP", filetypes=[("ZIP 资料包", "*.zip")]
            )
        if path:
            self.source_path.set(path)

    def _create_package(self) -> None:
        if self.busy:
            return
        questionnaire = Path(self.questionnaire_path.get())
        source = Path(self.source_path.get())
        if not questionnaire.is_file() or questionnaire.suffix.lower() != ".docx":
            messagebox.showwarning("缺少问卷", "请选择 DOCX 卖家问卷。")
            return
        if self.source_kind.get() == "folder" and not source.is_dir():
            messagebox.showwarning("缺少资料", "请选择有效的资料文件夹。")
            return
        if self.source_kind.get() == "zip" and (
            not source.is_file() or source.suffix.lower() != ".zip"
        ):
            messagebox.showwarning("缺少资料", "请选择有效的 ZIP 资料包。")
            return
        self.create_button.configure(state="disabled")
        self.busy = True
        source_is_zip, cloud = self.source_kind.get() == "zip", self.cloud_images.get()
        self.status_message.set("正在复制原件并创建任务……")

        def worker() -> None:
            try:
                package_id = self.pipeline.create_package(
                    questionnaire, source, materials_are_zip=source_is_zip
                )
                self.events.put(("created", package_id))
                self.pipeline.process(package_id, allow_cloud_images=cloud)
                self.events.put(("processed", package_id))
            except Exception as exc:  # noqa: BLE001 -- marshal worker errors back to the UI
                self.events.put(("error", f"{type(exc).__name__}: {exc!s}"))

        threading.Thread(target=worker, daemon=True, name="workbench-create").start()

    def _retry_active(self) -> None:
        if self.busy:
            messagebox.showinfo("处理中", "请等待当前任务完成。")
            return
        if not self.active_package_id:
            messagebox.showinfo("未选择", "请先选择一个资料包。")
            return
        package_id = self.active_package_id
        cloud = self.cloud_images.get()
        self.busy = True
        self.create_button.configure(state="disabled")
        self.status_message.set(f"正在重新处理 {package_id}……")

        def worker() -> None:
            try:
                self.pipeline.process(package_id, allow_cloud_images=cloud)
                self.events.put(("processed", package_id))
            except Exception as exc:  # noqa: BLE001 -- marshal worker errors back to the UI
                self.events.put(("error", f"{type(exc).__name__}: {exc!s}"))

        threading.Thread(target=worker, daemon=True, name="workbench-retry").start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "created":
                    self.active_package_id = str(payload)
                    self.status_message.set(f"已创建 {payload}，正在处理……")
                    self._refresh_packages()
                elif kind == "processed":
                    self.busy = False
                    self.status_message.set(f"{payload} 处理完成，等待人工审核。")
                    self.create_button.configure(state="normal")
                    self._refresh_packages()
                    self._load_package(str(payload))
                elif kind == "error":
                    self.busy = False
                    self.status_message.set("处理失败")
                    self.create_button.configure(state="normal")
                    messagebox.showerror("处理失败", str(payload))
                    self._refresh_packages()
                elif kind == "connection":
                    self.connection_button.configure(state="normal")
                    self.connection_running = False
                    result = payload
                    self.status_message.set(result["message"])
                    messagebox.showinfo(
                        "DeepSeek 连接测试",
                        result["message"] + "\n" + "\n".join(result.get("models", [])),
                    )
        except queue.Empty:
            pass
        self.root.after(400, self._drain_events)

    def _refresh_packages(self) -> None:
        selected = self.active_package_id
        for item in self.package_tree.get_children():
            self.package_tree.delete(item)
        for row in self.database.list_packages():
            self.package_tree.insert(
                "",
                "end",
                iid=row["id"],
                text=row["id"],
                values=(STATUS_LABELS.get(row["status"], row["status"]),),
            )
        if selected and self.package_tree.exists(selected):
            self.package_tree.selection_set(selected)
            self.package_tree.see(selected)

    def _tick(self):
        self._refresh_packages()
        self.root.after(1500, self._tick)

    def _select_package(self, _event=None) -> None:
        selection = self.package_tree.selection()
        if selection:
            self._load_package(selection[0])

    def _load_package(self, package_id: str) -> None:
        row = self.database.get_package(package_id)
        if not row:
            return
        self.active_package_id = package_id
        self.detail_status.set(
            f"{package_id} · {STATUS_LABELS.get(row['status'], row['status'])}"
        )
        signature = (package_id, row["updated_at"])
        if signature == self.loaded_signature:
            return
        previous_package = self.loaded_signature[0] if self.loaded_signature else None
        self.loaded_signature = signature
        if previous_package != package_id:
            self.review_note.delete("1.0", "end")
            for variable in self.confirmations.values():
                variable.set(False)
        package = Path(row["package_path"])
        questionnaire = (
            _load_json(package / "reports" / "questionnaire_report.json") or {}
        )
        inventory = _load_json(package / "reports" / "source_inventory.json") or {}
        comparison = _load_json(package / "reports" / "comparison_report.json") or {}
        product = _load_json(package / "product.json") or {}
        if row["status"] in {
            PackageStatus.NEEDS_MANUAL_REVIEW.value,
            PackageStatus.NEEDS_SELLER_CONFIRMATION.value,
            PackageStatus.REJECTED.value,
            PackageStatus.APPROVED.value,
        }:
            self.review_status.set(row["status"])
        gate = product.get("quality_gate", {})
        blocks = gate.get("hard_blocks", [])
        self.gate_message.set(
            "；".join(blocks[:3])
            if blocks
            else "无自动入库：请检查检测报告、脱敏副本及样图，再逐项人工确认。"
        )
        self.approve_button.configure(
            state="normal"
            if gate.get("approval_enabled") and not self.busy
            else "disabled"
        )
        run_id = gate.get("run_id")
        if getattr(self, "_review_run", None) != (package_id, run_id):
            for variable in self.confirmations.values():
                variable.set(False)
            self._review_run = (package_id, run_id)
        self.preview_items = product.get("preview", {}).get("items", [])
        self.preview_combo.configure(
            values=[item["path"] for item in self.preview_items]
        )
        self.preview_selection.set(
            self.preview_items[0]["path"] if self.preview_items else ""
        )
        self._show_preview()
        self.questions = product.get("questions", [])
        self.question_combo.configure(
            values=[q["id"] for q in self.questions]
            + [
                "field:" + key
                for key in questionnaire.get("fields", {})
                if "field:" + key not in {q["id"] for q in self.questions}
            ]
            + ["preview_scope", "pricing:list_price"]
        )
        self.question_choice.set(
            self.questions[0]["id"] if self.questions else "preview_scope"
        )
        self._show_question()
        self._render_declared(questionnaire)
        self._render_detected(inventory)
        self._render_conflicts(comparison)
        self._render_files(inventory)
        card_path = package / "buyer_card.md"
        self._set_text(
            self.card_text,
            card_path.read_text(encoding="utf-8")
            if card_path.exists()
            else "等待生成买家卡……",
        )
        self._show_report()

    def _render_declared(self, report: dict) -> None:
        for item in self.declared_tree.get_children():
            self.declared_tree.delete(item)
        for field in report.get("fields", {}).values():
            value = field.get("value")
            if isinstance(value, list):
                value = "、".join(str(item) for item in value)
            self.declared_tree.insert(
                "",
                "end",
                values=(
                    f"{field.get('label')}：{value or 'UNKNOWN'}",
                    field.get("provenance"),
                ),
            )

    def _render_detected(self, inventory: dict) -> None:
        for item in self.detected_tree.get_children():
            self.detected_tree.delete(item)
        rows = [
            ("文件总数", inventory.get("total_files", "等待扫描")),
            ("可打开", inventory.get("readable_files", "-")),
            ("不支持格式", inventory.get("unsupported_files", "-")),
            ("无法打开", inventory.get("failed_files", "-")),
            ("资料包 SHA-256", inventory.get("root_sha256", "-")),
        ]
        for label, value in rows:
            self.detected_tree.insert("", "end", text=label, values=(value,))

    def _render_conflicts(self, comparison: dict) -> None:
        conflicts = comparison.get("conflicts", [])
        if not conflicts:
            text = "规则扫描暂未发现冲突，仍需人工检查。"
        else:
            sections = []
            for index, conflict in enumerate(conflicts, 1):
                section = (
                    f"{index}. [{conflict.get('severity')}] {conflict.get('message')}"
                )
                if conflict.get("suggested_question"):
                    section += f"\n   建议追问：{conflict['suggested_question']}"
                sections.append(section)
            text = "\n\n".join(sections)
        self._set_text(self.conflict_text, text)

    def _render_files(self, inventory: dict) -> None:
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        for item in inventory.get("items", []):
            stats = json.dumps(item.get("stats", {}), ensure_ascii=False)
            if item.get("error"):
                stats += f" | {item['error']}"
            self.file_tree.insert(
                "",
                "end",
                text=item.get("relative_path"),
                values=(
                    item.get("extension"),
                    item.get("status"),
                    item.get("size_bytes"),
                    stats,
                ),
            )

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _current_path(self):
        row = (
            self.database.get_package(self.active_package_id)
            if self.active_package_id
            else None
        )
        return Path(row["package_path"]) if row else None

    def _check_connection(self):
        if self.busy:
            messagebox.showinfo("处理中", "请等当前任务完成后测试连接。")
            return
        self.connection_running = True
        self.connection_button.configure(state="disabled")
        self.status_message.set("正在验证 Key 与模型权限；不发送资料……")

        def worker():
            self.events.put(("connection", self.provider.check_connection()))

        threading.Thread(target=worker, daemon=True).start()

    def _open_package(self):
        package = self._current_path()
        if package:
            os.startfile(str(package))

    def _show_report(self):
        package = self._current_path()
        if package:
            path = package / self.report_files[self.report_choice.get()]
            if not path.exists():
                self._set_text(self.report_text, "等待生成报告。")
                return
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                text = self._format_report(self.report_choice.get(), json.loads(text))
            self._set_text(self.report_text, text)

    @staticmethod
    def _format_report(label, data):
        lines = [label, "完整 JSON 可在资料包文件夹内查看。", ""]
        types = {
            "FILLED_CONTENT": "已填写内容",
            "EMPTY_TEMPLATE": "空白模板",
            "ASSIGNMENT_INSTRUCTION": "任务/实验要求",
            "RAW_DATA": "原始数据",
            "NOTES": "笔记",
            "SLIDES": "课件",
            "CODE": "代码",
            "PARTIALLY_FILLED": "部分填写",
            "SUSPECTED_INCOMPLETE": "疑似不完整",
            "UNREADABLE": "无法打开",
            "UNKNOWN": "无法确定",
        }
        if label == "内容质量":
            lines += [
                f"有效内容文件（推断）：{data.get('effective_content_files', 0)}",
                str(data.get("note", "")),
            ]
            lines += [
                f"{types.get(kind, kind)}：{count}"
                for kind, count in data.get("counts", {}).items()
            ]
            lines += ["", "逐文件结果"]
            for row in data.get("items", []):
                lines += [
                    f"{row['file_id']} · {types.get(row['classification'], row['classification'])} · {row['risk']}",
                    "  原因：" + ("、".join(row["reasons"]) or "未触发明显异常规则"),
                    f"  字符：{row['stats'].get('characters', 0)}；非空单元格：{row['stats'].get('non_empty_cells', 0)}",
                ]
        elif label == "隐私与脱敏":
            lines += [
                f"阻断文件：{data.get('blocked_files', 0)}",
                data.get("disclaimer", ""),
            ]
            for row in data.get("items", []):
                lines += [
                    "",
                    f"{row['file_id']} · {row['status']}",
                    f"文字命中类型/次数：{row['findings']}",
                    f"已处理图片/页面：{len(row['images'])}；元数据清理：{row['metadata_removed']}",
                    "需处理问题："
                    + ("、".join(row["errors"]) or "仍需人工核对隐私漏检与可读性"),
                    "脱敏副本：" + str(row.get("processed_file") or "未生成"),
                ]
        elif label == "价格建议":
            lines += [
                "置信度：低（没有可比成交数据）",
                f"状态：{data.get('status')}",
                f"卖家最低到手：{data.get('seller_min_take_home', '待确认')} 元（内部）",
                f"理论最低成交：{data.get('theoretical_min_sale_price', '待确认')} 元",
                f"建议最低成交：{data.get('recommended_min_sale_price', '待确认')} 元",
                f"建议挂牌：{data.get('recommended_list_price', '待确认')} 元",
                f"卖家比例：{data.get('seller_share')}；带推荐人时平台比例：{data.get('platform_share_with_referral')}",
                "",
                *data.get("pricing_reasoning", []),
                "",
                "建议不是市场价，也不执行交易或分账。",
            ]
        elif label == "重复与版本":
            names = {
                "EXACT_DUPLICATE": "相同文件集合",
                "HIGH_OVERLAP": "高度重叠",
                "DIFFERENT_VERSION": "不同年份版本",
                "POSSIBLY_COMPLEMENTARY": "可能互补，需人工确认",
                "UNKNOWN": "无法确定",
            }
            lines += [
                f"{r['other_product_id']}：{names.get(r['classification'], r['classification'])}；共同文件 {r['exact_shared_files']}"
                for r in data.get("matches", [])
            ]
            if not data.get("matches"):
                lines.append("没有足够证据识别其他可比资料包。")
            lines.append(data.get("note", ""))
        elif label == "模型调用":
            lines += [
                data.get("text_scope", ""),
                f"本次图片外发授权：{data.get('cloud_images_consent')}",
            ]
            lines += [
                f"{r['model']}：{'成功' if r['ok'] else '失败，回退人工'}；{r.get('seconds', '-')} 秒"
                for r in data.get("calls", [])
            ]
        else:
            lines.append(json.dumps(data, ensure_ascii=False, indent=2))
        return "\n".join(lines)

    def _show_preview(self):
        package, relative = self._current_path(), self.preview_selection.get()
        if package and relative and (package / relative).is_file():
            from PIL import Image, ImageTk

            with Image.open(package / relative) as image:
                image = image.copy()
                image.thumbnail((650, 380))
                self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_photo, text="")
        else:
            self.preview_label.configure(
                image="",
                text="暂无可展示样图。请检查授权范围、图片质量和隐私覆盖；不会虚构样图。",
            )

    def _show_question(self):
        selected = self.question_choice.get()
        question = next(
            (q for q in getattr(self, "questions", []) if q["id"] == selected), {}
        )
        self._set_text(
            self.question_text,
            question.get(
                "question", "修正字段或指定授权内的样图范围；保存后重新处理。"
            ),
        )
        self.answer_value.set(question.get("answer", ""))

    def _save_answer(self):
        if not self.active_package_id or self.busy:
            return
        try:
            self.pipeline.answer_question(
                self.active_package_id,
                self.question_choice.get(),
                self.answer_value.get(),
                self.reviewer.get(),
            )
        except Exception as exc:  # noqa: BLE001 -- show safe local validation errors without closing UI
            messagebox.showerror("无法保存", str(exc))
            return
        self.loaded_signature = None
        self._retry_active()

    def _save_review(self, approve=False) -> None:
        if not self.active_package_id:
            messagebox.showinfo("未选择", "请先选择一个资料包。")
            return
        reviewer = self.reviewer.get().strip()
        if not reviewer:
            messagebox.showwarning("缺少审核人", "请填写审核人。")
            return
        note = self.review_note.get("1.0", "end").strip()
        try:
            self.pipeline.review(
                self.active_package_id,
                PackageStatus.APPROVED
                if approve
                else PackageStatus(self.review_status.get()),
                reviewer,
                note,
                confirmations={
                    key: variable.get() for key, variable in self.confirmations.items()
                },
            )
        except Exception as exc:  # noqa: BLE001 -- keep manual-review UI available on save failure
            messagebox.showerror("保存失败", str(exc))
            return
        self.status_message.set("人工结论已保存。")
        self._refresh_packages()
        self._load_package(self.active_package_id)

    def _close(self) -> None:
        if self.busy or getattr(self, "connection_running", False):
            messagebox.showinfo(
                "处理中", "请等待当前任务结束后关闭；强制退出会在下次启动时标记为中断。"
            )
            return
        self.provider.close()
        self.root.destroy()


def enable_dpi_awareness():
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass


def main() -> None:
    enable_dpi_awareness()
    root = tk.Tk()
    # One process owns the task database; a second instance must not mark active work interrupted.
    lock_file = (settings.root / "workbench.lock").open("a+b")
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        if not lock_file.read(1):
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            messagebox.showinfo("工作台已启动", "请使用已打开的工作台窗口。")
            root.destroy()
            lock_file.close()
            return
    WorkbenchDesktop(root)
    root.mainloop()
    lock_file.close()


if __name__ == "__main__":
    main()
