# 开源选型与复用记录（2026-08-26）

编码前对照原始需求流程，检索并比较了以下官方仓库。保持现有 Tkinter 桌面和 Pipeline，不移入公共网站、账户或交易系统。

| 项目 | 许可 / 作用 | 本项目决定 |
| --- | --- | --- |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Apache-2.0；本地中英文 OCR，输出文字及坐标 | 采用 Python 库，新增本地 OCR 适配器；识别失败留人工审核 |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | Apache-2.0/BSD-3-Clause；PDFium 渲染 | 采用，PDF 页面栅格化用于 OCR、不可逆遮挡与局部样图 |
| [Presidio](https://github.com/data-privacy-stack/presidio) | MIT；检测、匿名化分离 | 参考模块边界，自行编写中文场景规则，不复制源码、不引入 NLP 服务栈 |
| [Docling](https://github.com/docling-project/docling) | MIT；通用文档结构与模型转换 | 暂不整套引入，已有 Office 库满足当前结构提取，避免重复转换与较大模型依赖 |

采用依赖形式复用，不把第三方整个应用覆盖到当前项目。适配器只转换其公开输出接口，不冒充自研 OCR。许可证随依赖 wheel 保留；分发打包程序时必须携带依赖许可证，包括 PDFium 的 BUILD_LICENSES。RapidOCR 模型来源及权利说明以其官方仓库为准。

参考文档：
- https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/usage/
- https://pypdfium2.readthedocs.io/en/stable/python_api.html
- https://www.python-httpx.org/environment_variables/

DeepSeek 初始诊断：历史记录只保留 ConnectError，无法追溯当时 DNS/代理/TLS 根因。2026-08-26 使用原配置 GET /models 返回 200，三个配置模型均可见；匿名 Flash 文本请求成功返回本地 Schema 合法 JSON。不能归因于未经复现的代理故障。补救为更合理的超时、可配置代理/环境读取、分类型错误、连接测试和一次重试，始终保留 TLS 校验。

本机实际采用并锁定：RapidOCR 3.9.2、ONNX Runtime 1.29.0、pypdfium2 5.12.1。本地缓存为 PP-OCRv6 的小型检测/识别模型和方向分类模型，约32MB；模型由RapidOCR官方加载逻辑获取，未训练新模型。分发时须保留依赖与模型各自许可证，而不是仅保留本项目说明。

后续匿名实际推理还验证了 Vision 图片与 Pro 冲突审核，均返回有效结构化结果。诊断脚本不会打印 Key、Authorization头、原始服务端错误正文或真实资料内容。
