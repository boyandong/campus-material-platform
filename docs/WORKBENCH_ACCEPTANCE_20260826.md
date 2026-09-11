# 本地工作台改造与验收记录

## 结论与边界

DeepSeek 三个模型的匿名实际调用通过。原有原生桌面框架上已接通资料处理及人工审核主流程，未恢复网站、登录、支付或自动发布。

这是一条带人工关口的辅助流程，不等于全自动匿名化、内容正确性审核或市场定价系统。复杂手写、人像/签名漏检、Office完整页面渲染、任意自然语言授权范围、旧文件格式仍需人工处理；不能把工具输出直接当作对外发布许可。

## 编码前的开源比较

对比 RapidOCR、pypdfium2、Presidio、Docling，选用前两者的库接口并编写本项目适配层。没有把第三方完整应用覆盖到工作目录，没有把参考项目代码冒充自研。理由、仓库和许可证见 [开源选型记录](OPEN_SOURCE_ADOPTION.md)。

## 改动清单

| 文件/模块 | 主要改动 |
| --- | --- |
| `workbench/config.py`、`deepseek.py` | 复用同一 Key/HTTP Client、分模型调用、连接测试、超时/代理参数、错误分类、一次重试、无敏感内容的调用记录 |
| `workbench/models.py` | schema 2.0、视觉响应校验、处理阶段与人工核验字段 |
| `workbench/parser.py` | 补齐真实问卷标签，优先实际回答，避免把解释文字或其他问题复选框当答案 |
| `workbench/content.py`（新） | Office表格/正文/页眉页脚/元数据、PDF、文本的结构及内容提取 |
| `workbench/quality.py`（新） | 内容类型、空模板、空表头、部分填写、异常少量、同包重复及红黄绿风险 |
| `workbench/privacy.py`（新） | 中文隐私规则、跨段落/单元格已知值清理、计数报告与公共文案清理 |
| `workbench/imaging.py`（新） | RapidOCR、图像质量、EXIF、文字黑块、二维码检测、可选Vision、局部水印 |
| `workbench/redaction.py`（新） | 不覆盖原件的Office副本清理、嵌入图片处理、PDF栅格副本、覆盖失败阻断 |
| `workbench/previews.py`（新） | 授权/范围校验、学术成果人工选图、少量局部样图草稿 |
| `workbench/pricing.py`（新） | Decimal底线/佣金/推荐人比例、客观因素与低置信度区间 |
| `workbench/duplicates.py`（新） | 跨资料包哈希、文本重叠、课程/年份及可能互补比较，不自动合并 |
| `workbench/pipeline.py` | 接通全部阶段、来源哈希、追问及人工回答、产物一致更新、入库硬阻断 |
| `workbench/scanner.py`、`comparison.py` | 格式/大小边界、单文件失败继续、类型/完整性/空模板/数量/年份冲突 |
| `workbench/storage.py`、`database.py` | Windows ZIP路径保护、原件清单、原子JSON写入、新阶段中断恢复 |
| `workbench/buyer_card.py` | 客观内容构成/目录/样图/已确认售价、敏感文本与风险承诺过滤、明确内部草稿状态 |
| `workbench/desktop.py` | 连接按钮、图像外发选择、报告与样图、人工补充核验、逐项确认、重复进程/并发/刷新修正、高DPI |
| `tests/test_phase2.py`（新）、`tests/test_workbench.py` | 匿名合成数据、真实模板结构、失败降级、审核与隐私回归；普通测试不调用云模型或下载OCR |
| `scripts/check_deepseek.py`（新） | 认证与三模型匿名诊断，推理需显式开关 |
| `scripts/smoke_desktop.py`（新） | 无API的原生桌面完整交互验收与截图 |
| `scripts/benchmark_local.py`（新） | 真实资料只读扫描，只保存汇总，无模型调用 |
| `requirements.txt`、`.env.example`、`.gitignore`、`run_workbench.ps1`、`README.md` | 依赖、一次配置、忽略模型/秘密、依赖不变免重复安装、使用及能力边界 |

SQLite未新增联系方式或问卷存储表；沿用任务及状态表。未修改 `.env.local` 中的现有 Key。旧站归档和真实原资料保持不变。

## 实际验证

- DeepSeek `/models`：HTTP200，Flash、Vision、Pro三个指定模型均可见。
- Flash匿名文本：返回通过本地Schema校验的结果。
- Vision匿名合成图片：返回通过本地Schema校验的结果。
- Pro匿名矛盾声明：返回通过本地Schema校验的结果；普通流程不无条件调用Pro。
- 本地RapidOCR：正确识别合成图中的中文姓名和学号；不使用真实隐私样本。
- 单元与集成回归：36项通过。覆盖实际空白模板/匿名填充、多选/UNKNOWN、空表头/空模板、Office表格与分段姓名、页眉和作者清理、嵌入图、PDF无原文字层、OCR失败/PDF上限阻断、授权/学术范围、价格份额及人工改价重算、重复比较、Windows ZIP路径、原件/产物哈希、人工更新与审批、HTTP错误及无密钥降级。
- 原生Tkinter桌面：实际调用创建操作，等待结果，保存人工回答并重跑，查看报告/样图，完成六项人工确认并入库；无回调错误。
- 窗口：1280×820截图检查；980×680检查审核按钮仍在窗口内；修复高DPI截图/窗口坐标不一致。
- 根目录启动脚本实测通过；修正 Windows PowerShell 5 对无BOM中文脚本的编码解析问题。依赖已安装时不会重复下载，实际打开原生桌面窗口。
- Python编译检查和Ruff静态检查通过。普通测试集不依赖实时网络。
- 真实资料只读基准：289文件，208可解析，60暂不支持，21解析失败；约45.88秒。全部原文件哈希未变。仅做基础扫描/质量规则，不做真实资料云端调用，也不声称已完成这些真实资料的脱敏。

诊断与匿名基准汇总保存在 `work/deepseek-diagnostics-20260826.json`、`work/local-benchmark-20260826.json`；原生验收截图在 `work/native-*-dpi.png`。`work/`是内部工作目录，不应作为买家输出。

## 仍需人工处理的情况

- 不支持或解析失败：重新导出为受支持格式；不能通过“我确认”绕过。
- 授权范围模糊：核实后选择明确文件及页/图序号，再重跑；不自动发送追问。
- 图片漏检或遮挡不正确：本轮不提供手动画框工具；在独立副本上修正后新建资料包。
- Word/PowerPoint需要原始排版截图：自行导出PDF后处理，或使用明确标注的结构摘录，不能伪装成原页。
- 成交数据不足：建议价始终低置信度；需实际试验再校准，不是已验证市场价格。
- 没有自动发布、自动交易、版权判决或完整内容正确性保证。最终是否可分享由有权审核者确认。
