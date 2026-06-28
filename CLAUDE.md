# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

音频转录与总结工具是一个面向 Windows 的 PySide6 / Qt Widgets 桌面应用。应用用于录制系统音频、录制麦克风或导入本地音视频文件，将输入保存为历史记录，再通过本地 ASR 模型转录文字，并可调用 OpenAI 兼容的 LLM API 生成总结。

主流程：创建录音或导入音视频 -> 保存历史记录 -> ASR 转录 -> 可选 LLM 总结 -> 查看结果和关联文件

## 常用命令

```bash
# 启动应用
python main.py

# 安装依赖
pip install -r requirements.txt

# 运行当前稳定的单元测试
python -m pytest tests/test_qt_history.py tests/test_qt_models_gguf.py tests/test_qt_model_workers.py -q

# 运行 WASAPI 录音手动测试（需要 Windows 音频设备）
python tests/test_wasapi_record.py

# 运行 GGUF demo 手动测试（需要本地模型和运行环境）
python -B model_test/llama-cpp/qwen3_asr_gguf_release_demo.py --init-only
```

## 静态分析

- **pylint**: 配置在 `.pylintrc`，已允许 PySide6 扩展并禁用 `no-name-in-module` 和 `no-member`
- **ruff**: 用于代码风格检查
- **mypy**: 用于类型检查

## 技术栈

| 层级 | 技术 |
|---|---|
| GUI | PySide6 / Qt Widgets |
| 系统音频捕获 | `pyaudiowpatch` (WASAPI loopback) |
| ASR 引擎 | Qwen3-ASR GGUF (llama-cpp 本地推理) |
| 模型下载 | ModelScope (主源)，保留备用下载源扩展 |
| LLM 总结 | `httpx` 调用 OpenAI 兼容 Chat Completions API |
| 音频处理 | `scipy`, `numpy`, `pydub`, `ffmpeg`/`ffprobe` |
| GPU 加速 | `onnxruntime-directml` |
| 日志 | 自定义 JSON Lines 结构化日志 |
| 测试 | `pytest`，Qt 测试使用 `QT_QPA_PLATFORM=offscreen` |

## 架构概览

### 入口和应用流

`main.py` -> `src.app.application.main()` -> 初始化日志 -> 创建 QApplication -> 实例化 MainWindow -> 进入 Qt 事件循环

### 模块分层

```
src/
├── qt_app.py                    # QApplication 初始化
├── qt_main_window.py            # 主窗口骨架、导航和历史记录操作
├── handlers/                    # MainWindow 的业务逻辑 mixin
│   ├── recording_handlers.py    # 录音设备/流程/状态
│   ├── import_handlers.py       # 本地音视频导入、拖拽导入
│   ├── processing_handlers.py   # 处理状态、结果保存、worker 清理
│   ├── transcription_handlers.py# ASR 转录和进度
│   ├── summary_handlers.py      # LLM 总结和进度
│   └── settings_handlers.py     # 设置导航、配置保存、模型下载回调
├── ui/                          # Qt 界面构造、控件和样式
├── services/                    # 外部服务封装
├── domain/                      # 领域数据结构
└── utils/                       # 通用工具
```

### 关键设计决策

1. **Handler Mixin 模式**: `MainWindow` 通过 mixin 组合不同业务逻辑（录音、导入、转录、总结、设置），每个 handler 负责独立的功能域。

2. **后台任务**: 耗时任务（转录、总结、模型下载）在 `QThread` 后台线程执行，通过 Qt signal/slot 通知 UI，绝不直接操作 Qt 控件。

3. **历史记录存储**: 每条记录是 `~/Documents/NoisNote/recordings/<record_id>/` 下的独立文件夹，包含 audio.wav、transcript.txt、summary.txt、export.md、metadata.json。

4. **模型管理**: 模型存储在 `~/Documents/NoisNote/models/`，以 GGUF zip 包形式下载。正式模型清单只包含 `Qwen3-ASR-0.6B-GGUF` 和 `Qwen3-ASR-1.7B-GGUF`。

5. **配置结构**: 配置文件 `~/Documents/NoisNote/config.json`，主要配置段：`funasr`（ASR 配置）、`qwen3_asr_gguf`（GGUF 运行参数）、`llm`（API 配置）、`audio`（录音和自动化开关）、`models`（模型清单）。

## 当前约束

- **平台**: 仅支持 Windows 10/11，WASAPI loopback 依赖 Windows 音频子系统
- **设备策略**: 默认设备策略偏保守，`auto` 会映射到 CPU
- **模型识别**: 应用只识别 `~/Documents/NoisNote/models/` 下的模型目录
- **快捷键**: 快捷键页是预留入口，快捷键体系尚未完成
- **旧代码**: Flet 界面代码已清理，当前只维护 PySide6 实现

## 测试说明

- Qt 测试使用 `QT_QPA_PLATFORM=offscreen` 环境变量
- **核心稳定测试**: `test_qt_history.py`, `test_qt_models_gguf.py`, `test_qt_model_workers.py`
- **手动测试**: `test_wasapi_record.py`（需要真实音频设备）、模型 demo（需要本地模型）
- 真实模型推理和长时间音频转录不要在自动验证中运行

## 开发规范

- 代码注释和文档使用中文，编码 UTF-8
- 代码中不使用 emoji
- 不要直接改动用户本地数据目录，除非用户明确要求迁移或清理
- 不要提交 API Key、模型文件、录音文件、缓存和本地 IDE 配置
- 变更历史记录、模型管理或配置结构时，需要补充对应单元测试
- 项目还未发布，不要做兼容性处理；如果旧代码要改，直接改成最合适的
- 最终发布给用户的config.json配置，不要包含应用内固定的参数