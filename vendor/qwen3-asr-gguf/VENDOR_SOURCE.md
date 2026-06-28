# Vendor 依赖来源说明

## llama.cpp 运行时 (bin/*.dll)

- **来源**：[llama.cpp 官方 GitHub Releases](https://github.com/ggml-org/llama.cpp/releases)
- **当前版本**：b7798
- **下载链接**：`https://github.com/ggml-org/llama.cpp/releases/download/b7798/llama-b7798-bin-win-vulkan-x64.zip`
- **许可**：MIT
- **说明**：官方预编译 Windows Vulkan 版本，含 CPU 指令集自适配和 Vulkan GPU 加速。本项目原样集成，未修改任何二进制。
- **加载方式**：`qwen_asr_gguf/inference/llama.py` 通过 ctypes.CDLL 加载 `ggml.dll` / `ggml-base.dll` / `llama.dll`；其余 CPU 指令集变体和 Vulkan 后端由 `ggml_backend_load_all()` 自动发现。
- **校验**：各文件 SHA-256 见同级 `RUNTIME_INFO.json`

## Qwen3-ASR-GGUF Python 推理代码 (qwen_asr_gguf/inference/*.py)

- **来源**：[HaujetZhao/Qwen3-ASR-GGUF](https://github.com/HaujetZhao/Qwen3-ASR-GGUF) GitHub 源码仓库
- **上游 commit**：`e790e3b`（2026-03-28: "aligner 的精度要求不高，onnx 用 int4 精度，省些内存"）
- **说明**：作者原创的 Qwen3-ASR GGUF 推理包装，包含 ONNX Encoder 加载、GGUF Decoder llama.cpp ctypes 绑定、流式转录流水线等。
- **本项目定制**（直接修改源码，不再使用 monkey patch）：
  1. `inference/schema.py`：新增 `ASRProgress` 进度数据类
  2. `inference/asr.py`：`transcribe()`/`asr()` 新增 `progress_callback` 参数，在分片解码循环中回调分片进度
  3. `inference/audio.py`：修复 `load_audio_numpy`/`load_audio_ffmpeg` 中 `duration=0.0` 被误解释为"读 0 帧"的 bug（`is not None` → falsy 检查）
- **上游 bug 修复**：`inference/audio.py` — 已记录在上方第 3 项。新版上游已移除 `llama.py` 中对 `relpath` 的调用，Windows 跨盘 relpath 修复不再需要。

## Qwen3-ASR 模型文件

- **来源**：阿里 Qwen3-ASR 官方模型 + HaujetZhao 量化转换
- **说明**：模型文件不在仓库中，运行前通过 ModelScope 下载到用户数据目录 `~/Documents/NoisNote/models/`
- **下载清单**：
  - `qwen3_asr_encoder_frontend.int4.onnx`
  - `qwen3_asr_encoder_backend.int4.onnx`
  - `qwen3_asr_llm.q4_k.gguf`

## 升级指南

### 升级 llama.cpp DLL
1. 从 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下载新版本 `llama-bXXXX-bin-win-vulkan-x64.zip`
2. 解压替换 `vendor/qwen3-asr-gguf/qwen_asr_gguf/inference/bin/` 下的所有文件
3. 更新 `RUNTIME_INFO.json` 中的版本号和各文件 SHA-256
4. 运行转录验证

### 升级 Qwen3-ASR-GGUF Python 代码
1. 从上游 [HaujetZhao/Qwen3-ASR-GGUF](https://github.com/HaujetZhao/Qwen3-ASR-GGUF) 获取最新源码
2. 替换 `vendor/qwen3-asr-gguf/qwen_asr_gguf/` 下的 Python 文件（保留 bin/ DLL 不动）
3. 验证 monkey patch 仍能正确命中（检查目标函数签名）
4. 运行转录验证
