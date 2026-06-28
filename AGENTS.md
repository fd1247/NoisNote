# AGENTS.md

This file provides guidance to Codex when working in this repository.

## 项目概述

音频转录与总结工具是一个面向 Windows 的 PySide6 / Qt Widgets 桌面应用。用于录制系统音频、录制麦克风或导入本地音视频文件，将输入保存为历史记录，再通过本地 ASR 模型转录文字，并可调用 OpenAI 兼容的 LLM API 生成总结。

```text
创建录音或导入音视频 -> 保存历史记录 -> ASR 转录 -> 可选 LLM 总结 -> 查看结果
```

## 技术栈

|   层级   |                        技术                        |
| -------- | -------------------------------------------------- |
| GUI      | PySide6 / Qt Widgets                               |
| 系统音频 | SoundCard (WASAPI Loopback)                        |
| ASR 推理 | Qwen3-ASR GGUF（ONNX + llama.cpp），本地模型推理     |
| LLM 总结 | OpenAI 兼容 API / Anthropic 兼容 API                |
| 音频处理 | ffmpeg / ffprobe                                   |
| 模型下载 | ModelScope（优先）+ GitHub（备用）                  |
| 日志     | JSON Lines，写入 `~/Documents/NoisNote/logs/` |
| 测试     | pytest，Qt 测试使用 `QT_QPA_PLATFORM=offscreen`     |
| 打包     | PyInstaller（onedir 模式）                          |

## 常用命令

```bash
# 启动应用
python main.py

# 运行常规单元测试
python -m pytest tests/test_qt_history.py tests/test_qt_models_gguf.py tests/test_qt_model_workers.py -q

# 运行 WASAPI 录音手动测试（需要 Windows 音频设备）
python tests/test_wasapi_record.py

# 安装依赖
pip install -r requirements.txt
```

## 项目结构

```text
main.py                                  # 应用入口
src/
  __init__.py                           # 包版本信息
  app/                                  # 应用核心
    application.py                      # QApplication 初始化、日志、异常钩子
    main_window.py                      # 主窗口骨架、UI 布局、Mixin 组装
    config.py                           # 默认配置、配置读写、模型清单
    version.py                          # 语义化版本号
    update.py                           # GitHub Releases 更新检查
    diagnostics.py                      # ASR 运行时诊断工具
  audio/                                # 音频录制模块
    recorder.py                         # AudioRecorder 录制引擎
    device_manager.py                   # DeviceManager WASAPI 设备管理
    types.py                            # CaptureMode、CaptureSettings 等数据类
    preprocess.py                       # 音视频探测、格式转换
  asr/                                  # ASR 转录引擎
    engine.py                           # TranscriptionEngine 高层封装
    runtime.py                          # Qwen3AsrGgufRuntime vendor 封装
    types.py                            # ASR 数据模型、进度类型
    utils.py                            # 转录文本清理
  llm/                                  # LLM 总结服务
    summarizer.py                       # Summarizer OpenAI 兼容 API 调用
  history/                              # 历史记录管理
    service.py                          # HistoryService CRUD 公开入口
    storage.py                          # 文件存储和元数据管理
    types.py                            # HistoryRecord、HistoryStatus
  model_registry/                       # 模型下载管理
    service.py                          # ModelService 模型目录与校验
    downloader.py                       # ModelDownloadManager 任务生命周期
    worker.py                           # ModelDownloadWorker 下载线程
    download.py                         # 下载源选择、文件下载、解压、校验
    types.py                            # ModelStatus、ModelCatalogEntry 等
  handlers/                             # MainWindow Mixin
    media_import.py                     # 文件导入和拖拽
    recording.py                        # 录音设备和流程
    processing.py                       # 处理状态和结果保存
    transcription.py                    # ASR 转录和重新转录
    summary.py                          # LLM 总结
    settings.py                         # 设置导航和配置保存
  workers/                              # 后台线程
    transcription.py                    # TranscriptionWorker
    summary.py                          # SummaryWorker
    preprocess.py                       # AudioPreprocessWorker
  ui/                                   # Qt 界面组件
    styles.py                           # 全局 Qt 样式表
    icons.py                            # 程序化 SVG 图标
    sidebar.py                          # 侧边栏构建
    recording.py                        # 录音页面
    content.py                          # 转录/总结内容标签页
    result.py                           # 结果状态辅助
    settings.py                         # 设置面板
    model_panel.py                      # 模型管理子页面
    widgets/                            # 可复用组件
      history_item.py                   # 历史记录列表项
      dialogs.py                        # 确认对话框
      update_dialog.py                  # 版本更新对话框
  utils/                                # 通用工具
    logging.py                          # JSON Lines 日志初始化、脱敏
    ffmpeg.py                           # ffmpeg/ffprobe 发现
vendor/qwen3-asr-gguf/                  # Qwen3-ASR-GGUF 第三方 Python 源码
  qwen_asr_gguf/inference/              # ASR 推理源码（上游 e790e3b + 3 处定制）
  qwen_asr_gguf/inference/bin/          # llama.cpp DLL（.gitignored, 由 download_deps.py 下载）
docs/                                   # 文档
  modules/                              # 各模块架构文档
  roadmap/                              # 路线图
  dev/                                  # 开发阶段文档
tests/                                  # 单元测试
scripts/                                # 构建和发布脚本
```

## 核心设计

### 数据目录

配置文件存储在系统 AppData 目录，用户数据存储在 Documents：

```text
%APPDATA%/NoisNote/
  config.json

~/Documents/NoisNote/
  data/                                  # 历史记录
  models/                                # ASR 模型
  logs/                                  # 日志
```

历史记录采用"一条记录一个文件夹"的结构。导入音频默认记录源文件路径，不复制源文件。导入视频在开始转录时才提取音轨。下载中的模型先写入 `.download-<name>` 临时目录，校验通过后再移动到最终目录。

### 配置结构

主要配置段：

- `selected_asr`：ASR 模型名、模型路径、推理设备
- `qwen3_asr_gguf`：GGUF runtime 工具目录、chunk、上下文和热词等运行参数
- `llm`：API Key、模型名、Base URL、供应商
- `audio`：录音模式、设备选择、自动转录/总结开关、预处理参数
- `models`：已下载模型记录

`config.py` 负责补齐新增默认字段，并通过 `_normalize_model_config` 迁移旧模型名。

### MainWindow Mixin 架构

MainWindow 通过 Python 多重继承组装功能，每个 Mixin 对应 `handlers/` 目录下的一个文件。Mixin 之间不应直接互相调用，公共逻辑提取到 MainWindow 自身。

### 后台任务

耗时任务不能在 UI 线程中执行：

- 转录：`TranscriptionWorker` (QThread)
- 总结：`SummaryWorker` (QThread)
- 音频预处理：`AudioPreprocessWorker` (QThread)
- 模型下载：`ModelDownloadWorker`，生命周期由 `ModelDownloadManager` 管理

后台线程不得直接操作 Qt 控件，只能通过 signal/slot 通知 UI。

### Vendor 依赖

Qwen3-ASR-GGUF 推理引擎以源码形式集成在 `vendor/qwen3-asr-gguf/` 中，运行时通过 `sys.path.insert` + `ctypes.CDLL` 动态加载。llama.cpp DLL 来自官方预编译的 `llama-b7798-bin-win-vulkan-x64.zip`，由 `scripts/download_deps.py` 下载到 `vendor/qwen3-asr-gguf/qwen_asr_gguf/inference/bin/`（该目录已 .gitignore）。项目对上游源码做了 3 处定制，详见 `vendor/qwen3-asr-gguf/VENDOR_SOURCE.md`。

### 模型管理

正式模型清单仅包含 `Qwen3-ASR-0.6B-GGUF` 和 `Qwen3-ASR-1.7B-GGUF`。以 `name` 作为主键，`alias` 仅用于兼容旧配置。新增模型需同步 `app/config.py`、`asr/runtime.py`、`model_registry/service.py` 和测试文件。

## 当前约束

- 目标运行环境是 Windows 10/11。录音模块依赖 WASAPI Loopback，不可移植到其他平台。
- 默认设备策略偏保守，`auto` 映射到 CPU。
- GPU 推理路径仅实现 DirectML（Windows），无 CUDA/CoreML 适配。
- 仅识别 `~/Documents/NoisNote/models/` 下的模型目录。
- 快捷键页面是预留入口，快捷键体系尚未完成。

## 开发规范

- 注释使用中文，文档使用中文，编码 UTF-8。
- 代码中不使用 emoji。
- 不要直接改动用户本地数据目录，除非用户明确要求。
- 不要提交 API Key、模型文件、录音文件、缓存和本地 IDE 配置。
- 变更历史记录、模型管理或配置结构时，需补充对应单元测试。
- UI 变更应保持浅色主界面和设置覆盖页的现有风格。
- 项目还未发布，不要做兼容性处理。旧代码要改就直接改成最合适的。

## 验证建议

代码改动后优先运行：

```bash
python -m pytest tests/test_qt_history.py tests/test_qt_models_gguf.py tests/test_qt_model_workers.py -q
```

默认不要在自动化验证中运行真实模型推理（Qwen3-ASR、CUDA、长音频转录、模型下载）。这些任务耗时长，应在用户终端手动执行。Codex 可协助分析 stdout、结果文件和日志，但不通过前台管道直接运行。

以下测试依赖本机设备或网络，默认只作为手动验收：

```bash
python tests/test_wasapi_record.py
```
