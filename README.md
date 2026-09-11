# 课程资料本地智能工作台

直接在本文件夹运行的 Windows 桌面工具，不是网站，不启动浏览器、不监听端口，不包含注册、聊天、支付、自动分账或自动发布。

## 启动与 DeepSeek

在 `C:\Users\董伯言\Desktop\campus-material-platform` 内双击 **启动工作台.bat**，或运行：

```powershell
.\run_workbench.ps1
```

需要 Python 3.11 或更高版本。首次启动创建 `.venv` 并安装依赖；依赖清单没有变化时不重复联网安装。已有依赖可用 `-NoInstall`。关闭窗口即停止；处理中会提醒等待，强制退出的任务下次标为中断，可重新处理。

密钥只需在 `.env.local` 配置一次，所有任务、重试和三个模型共用，不会逐次要求申请。已有 `.env.local` 时不要覆盖它。新机器可参考 `.env.example`。

| 模型 | 调用范围 |
| --- | --- |
| `deepseek-v4-flash` | 问卷自由文本归类、摘要、目录/商品卡辅助文案、内部价格解释 |
| `deepseek-v4-flash-vision-exp` | 图片 OCR 辅助、隐私区域、质量和代表性判断；仅勾选本次图片外发授权后调用 |
| `deepseek-v4-pro` | 仅已检测出红色风险、信息冲突或复杂跨包比较时调用 |

本地 OCR 使用 RapidOCR，不需要 API Key；首次使用可能下载 OCR 权重，缓存到 `models/rapidocr/`，后续复用。确定性文字扫描、计算和报告在无 Key 时仍可运行。

桌面右上角“测试 DeepSeek 连接”只检查认证和模型权限，不发送资料。2026-08-26 已实际验证三个模型均可调用。历史 `ConnectError` 无足够信息追溯根因，不能保证未来网络永不出错；现在会区分认证、余额、限流、DNS、TLS和超时。保留证书校验，不自动关闭 TLS 或绕过代理。

可配置 `DEEPSEEK_TIMEOUT`（默认120秒）、`DEEPSEEK_PROXY`、`DEEPSEEK_TRUST_ENV`。配置修改后重启。空响应、格式错误和临时故障最多重试一次；401/402等配置问题直接反馈。

## 使用流程

1. 选择填写后的 DOCX 问卷，以及资料文件夹或 ZIP。
2. 点击“创建并开始处理”。不要把整个工作台根目录选为资料源。
3. 查看声明/检测双栏、冲突、文件清单和检测报告。
4. 在“补充核验”回答问题、修正字段或指定授权样图；填写核验人，保存后重新处理。
5. 查看脱敏副本、样图、目录、价格草稿和买家卡，逐文件人工检查。
6. 无阻断项后，勾选隐私、样图、授权、价格、描述及风险确认，填写审核依据，才可“通过入库”。这是本地状态，不会发布或发送文件。

授权不清晰时不生成样图。学术成果类内容需要人工选择范围，例如 `F0001:1,F0002:2`，编号/序号可在隐私报告中找到。选择必须在卖家授权内；自动理解仅支持“前N页”等明确约束，其他范围交人工确认。

“补充核验”中可用 `pricing:list_price` 修改挂牌价；低于重新计算的卖家到手底线会阻止入库。回答及价格修正持久保存为 `HUMAN_VERIFIED`，不会改写原问卷。

## 已接通的辅助流程

`问卷 → 文件扫描 → 本地 OCR/隐私扫描与副本脱敏 → 内容质量与声明对照 → 按需模型辅助 → 目录/定价/授权局部样图 → 买家卡 → 人工终审`

- 问卷按标题、别名、相邻回答、复选框提取；使用现有模板匿名填充测试，未知内容不交 AI 猜成事实。
- DOCX/XLSX/PPTX/PDF/PNG/JPG/文本/常见代码：记录哈希、格式、数量和实际内容统计。
- 区分已填写内容、空模板、要求说明、原始数据、笔记、课件、代码、部分填写、疑似不完整、不可读及未知。
- 对照数量、声明完整但缺失/空模板、资料类型、年份；红色风险阻止入库，单文件失败不中断其余文件。
- 文本隐私规则覆盖有标签的姓名/学号、手机号、邮箱、QQ/微信、地址等；检查 Office 正文、表格、页眉页脚、批注、修订及元数据。
- 原件只读且前后核对 SHA-256。Office 另存副本，清除批注、删除修订内容、作者元数据与外部链接；嵌入图片走图像处理。PDF 栅格化后生成不可逆遮挡副本，不保留原文字层。
- 图像支持本地 OCR、文字区域黑块、二维码检测、EXIF方向规范化、模糊/低分辨率/空白及简单空网格判断。Vision 只做判断，像素修改由程序执行。
- 目录区分总文件、有效内容、模板、要求、数据、代码等；样图只截取部分内容并加水印。最多5张，不足时不凑数。
- 定价按可配置的35%平台比例、10%推荐人比例计算底线；参考有效内容、完整性、来源、年份、目录、样图给出明确的试验区间。没有成交样本时始终低置信度，不是市场估价，不因成绩声明加价。
- 跨包通过文件哈希、实际文本分片相似度、课程/年份比较重复、重叠、不同版本和可能互补；不自动合并。
- 人工回答、结论同步更新档案、买家卡和审核报告。重新处理生成新一轮副本/样图并清空旧轮确认，避免误用旧审核。

## 结果文件

每个包位于 `project_data/PRD-日期-随机号/`：

```text
original/questionnaire.docx          原问卷（内部）
original/materials/                 原资料（内部、只读）
processed/本轮编号/                 脱敏副本和候选图（内部草稿）
previews/本轮编号/                  授权范围内的局部水印样图
product.json                        全部结构化档案（内部）
catalog.md                          实际章节/内容构成目录草稿
buyer_card.json / buyer_card.md      买家卡，人工入库前不可对外发送
reports/questionnaire_report.json
reports/original_manifest.json
reports/source_inventory.json
reports/quality_report.json
reports/privacy_report.json
reports/comparison_report.json
reports/pricing_report.json
reports/preview_report.json
reports/version_comparison.json
reports/questions.json
reports/human_answers.json           有人工回答时生成
reports/model_calls.json             只有模型、结果、耗时及调用范围
reports/audit_log.jsonl / audit_report.md
```

重要字段保留值、原值、来源、置信度、来源引用及人工核验信息。分类和AI推断不会自动变成“已验证”。SQLite只存任务、阶段、路径及状态，不重复保存问卷和联系方式。

不要把整个资料包发给买家。原件、问卷、`product.json`、内部报告和所有候选图均为内部文件。买家卡只用白名单，屏蔽联系方式、最低到手价、内部说明和原始路径；历史评价只标为“卖家声明，未经核验”，不承诺成绩。价格仅在人工确认后出现在买家卡。

## 隐私与能力边界

- 文字模型会收到规则初筛后的有限问卷白名单和内容摘录（最多20文件、每文件1200字符）；这不是全量理解，也不能保证规则消除所有身份信息。图片单独逐次授权，默认不外发。无需云端辅助时可在本地配置中留空 API Key。
- OCR会漏检；人像、签名、手写、无标签姓名和特殊二维码不能保证识别。所有输出需要人工复核，不能将“未命中”解释为“无隐私”。
- 暂不支持 `.ms13`、旧版 Office、RAR、未知嵌入对象等；需人工导出受支持格式。单文件200MB、Office解压总量500MB、PDF默认60页、表格50万单元格等上限会明确阻断，不会截断后放行。
- DOCX/PPTX不做原生整页渲染。可用真实嵌入图片或明确标注的“结构化文字摘录”，不能把摘录当作原页截图。复杂排版、公式、隐藏对象和脱敏后的可读性需人工核对。
- 自动方向规范化仅可靠处理 EXIF；无方向标记的横置扫描、复杂表格、非矩形手写区域仍可能需手工处理。不保证深度版式理解或自动解释授权。
- 暂无手动画遮挡框工具。发现漏检时不要入库，应在独立副本上人工修正并新建包；原件及旧轮输出保留。
- 价格没有真实成交校准；相似度不是版权、同一版本或正确性的证明。红色阻断不能靠勾选复核绕过。
- 文件不是加密存储，请使用受保护的本机账户。清理旧轮输出或资料包应由运营者按最短必要留存期管理；工具不自动删除。

## 本地验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -q -p no:cacheprovider --basetemp .\work\pytest-local-new
.\.venv\Scripts\python.exe -X utf8 scripts\check_deepseek.py
```

每次测试建议使用新的 `--basetemp` 路径，避免旧只读样本或不同 Windows 用户产生权限冲突。可选 `scripts\check_deepseek.py --inference --vision` 会产生少量付费匿名测试请求。

`scripts/smoke_desktop.py` 只用匿名数据且不配 Key，验证原生窗口创建、补充回答、重新处理、样图与人工入库；会短暂打开测试窗口。`scripts/benchmark_local.py` 可只读扫描真实目录，只导出匿名汇总、不调用 AI。

开源选型见 [OPEN_SOURCE_ADOPTION.md](docs/OPEN_SOURCE_ADOPTION.md)；实测与改动清单见 [WORKBENCH_ACCEPTANCE_20260826.md](docs/WORKBENCH_ACCEPTANCE_20260826.md)。

## 保留与归档

`data/`、`docs/`、`marketing/`、原有分析脚本和原始资料保持不动。旧网站及其 Git 历史在 `archive/site-source-20260825.zip`，校验值在同目录 `.sha256`；活动 `site/` 已移除。工作台不依赖 Vinext、Next.js、React、D1、Wrangler、FastAPI或浏览器。
