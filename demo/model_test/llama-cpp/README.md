# Qwen3-ASR llama.cpp / GGUF 推理测试

本目录用于测试 Qwen3-ASR 的 llama.cpp / GGUF 推理路线。当前推荐优先使用 `HaujetZhao/Qwen3-ASR-GGUF` release 包路线，因为这条路线已经在本机完成 30 秒、30 分钟音频验证。

核心流程：

```text
audio -> ONNX audio encoder -> GGUF llama.cpp decoder -> transcript/result
```

注意：这不是“llama.cpp 直接加载官方 safetensors 模型”。Qwen3-ASR-GGUF 会把 Qwen3-ASR 拆成 ONNX Encoder 和 GGUF Decoder。

## 目录结构

```text
model_test/llama-cpp/
  qwen3_asr_gguf_release_demo.py       # 推荐使用：调用 Qwen3-ASR-GGUF release 包源码
  qwen3_asr_llama_cpp_0_6b_demo.py     # 早期实验：CapsWriter 风格 ONNX+GGUF 入口
  qwen3_asr_llama_cpp_1_7b_demo.py     # 早期实验：CapsWriter 风格 ONNX+GGUF 入口
  _qwen3_asr_llama_cpp_common.py       # 早期实验公共实现
  vendor/
    qwen3-asr-gguf/                   # 已迁移到顶层 vendor/qwen3-asr-gguf/，此处保留 zip 压缩包
    Qwen3-ASR-0.6B-gguf.zip            # 已下载模型压缩包
    Qwen3-ASR-1.7B-gguf.zip            # 可选：1.7B 模型压缩包
```

## 推荐脚本：Qwen3-ASR-GGUF Release Demo

运行 30 秒音频：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_gguf_release_demo.py" `
  --device cpu `
  --output-dir "model_test\llama-cpp\outputs\qwen3_asr_gguf_30s_cpu"
```

只验证模型初始化：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_gguf_release_demo.py" --init-only
```

GPU / DML：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_gguf_release_demo.py" `
  --device gpu `
  --output-dir "model_test\llama-cpp\outputs\qwen3_asr_gguf_30s_gpu"
```

运行 1.7B 模型：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_gguf_release_demo.py" `
  --model-size 1.7B `
  --device cpu `
  --output-dir "model_test\llama-cpp\outputs\qwen3_asr_gguf_1_7b_30s_cpu"
```

使用热词：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_gguf_release_demo.py" `
  --device cpu `
  --context "这是一段关于本地 ASR 和代码工具的会议音频。" `
  --hotwords "ModelScope,FunASR,Qwen3-ASR" `
  --hotword "function call"
```

验证时间戳对齐：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_gguf_release_demo.py" `
  --device cpu `
  --timestamp `
  --aligner-model-dir "$HOME\Documents\NoisNote\models\Qwen3-ForceAligner-0.6B-gguf" `
  --output-dir "model_test\llama-cpp\outputs\qwen3_asr_gguf_timestamp_cpu"
```

`--aligner-model-dir` 默认指向：

```text
%USERPROFILE%\Documents\NoisNote\models\Qwen3-ForceAligner-0.6B-gguf
```

时间戳验证成功标准：

- 命令返回 0。
- 输出目录包含 `transcript.txt`、`result.json`、`transcript.srt`、`timestamps.json`。
- `timestamps.json` 至少有 1 条记录。
- `result.json` 中 `alignment.items_count > 0` 且 `alignment.monotonic = true`。

常用参数：

- `--tool-dir`：Qwen3-ASR-GGUF 工具包目录，默认 `vendor/qwen3-asr-gguf`（项目仓库顶层）。
- `--model-size 0.6B|1.7B`：选择模型规格。默认 `0.6B`。也支持写成 `--model_size`。
- `--model-dir`：GGUF 模型目录。显式传入时优先级最高；不传时脚本会根据 `--model-size` 自动查找常见目录。
- `--audio`：待转录音频。
- `--context`：上下文提示，会放入 Qwen3-ASR-GGUF 的 system prompt。
- `--hotword`：热词，可重复传入。
- `--hotwords`：逗号分隔的热词列表。
- `--device cpu|gpu`：`cpu` 使用 CPU；`gpu` 启用 DirectML 加速 ONNX Encoder。
- `--timestamp`：启用时间戳对齐。当前只下载了 ASR 0.6B 模型，若要启用时间戳，需要额外准备 aligner 模型文件。
- `--chunk-size`：Qwen3-ASR-GGUF engine 内部 chunk 秒数。
- `--memory-num`：engine 内部记忆段数。
- `--preview-chars`：转录完成后控制台显示的预览长度。

热词并不是传统 ASR 的强制热词表，而是会和 `--context` 合并成提示词，再通过 `context` 传给 GGUF engine。例如：

```text
<用户 context>
请优先准确识别以下热词：ModelScope、FunASR、Qwen3-ASR、function call
```

这能提高命中概率，但不能保证一定按热词输出。

### 下载和放置 1.7B GGUF 模型

Qwen3-ASR-GGUF 的 Models Release 提供已经转换好的模型压缩包。ASR 模型有 0.6B 和 1.7B，1.7B 精度更高但速度更慢。

下载 1.7B：

```powershell
$vendor = "model_test\llama-cpp\vendor"
$url = "https://github.com/HaujetZhao/Qwen3-ASR-GGUF/releases/download/models/Qwen3-ASR-1.7B-gguf.zip"

Invoke-WebRequest -Uri $url -OutFile "$vendor\Qwen3-ASR-1.7B-gguf.zip"
```

推荐解压到：

```powershell
New-Item -ItemType Directory -Force "$vendor\Qwen3-ASR-GGUF-1.7B" | Out-Null

Expand-Archive `
  -LiteralPath "$vendor\Qwen3-ASR-1.7B-gguf.zip" `
  -DestinationPath "$vendor\Qwen3-ASR-GGUF-1.7B" `
  -Force
```

解压后，模型目录里应该直接包含以下关键文件：

```text
qwen3_asr_encoder_frontend.int4.onnx
qwen3_asr_encoder_backend.int4.onnx
qwen3_asr_llm.q4_k.gguf
```

如果解压后多了一层目录，可以直接用 `--model-dir` 指向包含这三个文件的目录。

模型目录约定（默认从应用模型目录读取）：

```text
%USERPROFILE%\Documents\AudioRecorder\models\
  Qwen3-ASR-GGUF-0.6B/
    qwen3_asr_encoder_frontend.int4.onnx
    qwen3_asr_encoder_backend.int4.onnx
    qwen3_asr_llm.q4_k.gguf
  Qwen3-ASR-GGUF-1.7B/
    qwen3_asr_encoder_frontend.int4.onnx
    qwen3_asr_encoder_backend.int4.onnx
    qwen3_asr_llm.q4_k.gguf
```

不传 `--model-dir` 时，脚本会按 `--model-size` 自动查找应用模型目录。

输出文件：

```text
<output-dir>/
  transcript.txt
  result.json
```

`result.json` 包含：

- `run_parameters`：本次运行参数。
- `runtime`：请求设备、ONNX Encoder provider、llama.cpp decoder 说明。
- `timings.model_load_seconds`：模型加载耗时。
- `timings.transcribe_seconds`：转录耗时。
- `timings.total_seconds`：总耗时。
- `timings.chunk_transcribe_timings`：release engine 的内部流式 chunk 耗时未暴露，因此这里记录为单个整体转录阶段。
- `performance`：Qwen3-ASR-GGUF engine 返回的内部性能统计，例如 prefill、decode、encode 等耗时。
- `text`：完整转录文本。

脚本会静默第三方 engine 的逐 token 输出，只在完成后打印输出路径、总耗时和一小段预览。

## Windows 注意事项

Qwen3-ASR-GGUF 使用 `multiprocessing.Queue`，在 Windows 下会创建命名管道。Codex shell 沙箱里可能报：

```text
PermissionError: [WinError 5] 拒绝访问
```

这不是模型或 llama.cpp 的问题。请在普通 PowerShell / CMD 中运行，或使用非沙箱 runner。

官方 `transcribe.exe` 也能转录，但当前 release 在中文 Windows 控制台下可能因为打印 emoji 状态文本触发 `UnicodeEncodeError`。推荐使用本目录的 Python demo。

## 早期实验脚本：CapsWriter 风格 ONNX + GGUF

这两个脚本保留用于实验，但不是当前推荐路线：

```text
qwen3_asr_llama_cpp_0_6b_demo.py
qwen3_asr_llama_cpp_1_7b_demo.py
```

它们会额外做应用层 VAD 分段：

```text
audio -> fsmn-vad -> chunks -> ONNX audio encoder -> GGUF llama.cpp decoder
```

需要准备 CapsWriter 风格的 engine 目录和导出后的模型目录：

```text
model_test/llama-cpp/capswriter_qwen_asr_gguf/
model_test/llama-cpp/models/Qwen3-ASR-1.7B/
  qwen3_asr_encoder_frontend.onnx
  qwen3_asr_encoder_backend.onnx
  qwen3_asr_llm.gguf
```

VAD-only 测试：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_llama_cpp_1_7b_demo.py" `

  --vad-only `
  --target-chunk-seconds 15 `
  --max-chunk-seconds 20 `
  --output-dir "model_test\llama-cpp\outputs\vad_only_30s" `
  --keep-chunks
```

完整转录：

```powershell
python -B "model_test\llama-cpp\qwen3_asr_llama_cpp_1_7b_demo.py" `

  --engine-dir "D:\path\to\qwen_asr_gguf" `
  --model-dir "D:\path\to\Qwen3-ASR-1.7B" `
  --onnx-provider CPU `
  --llm-use-gpu `
  --output-dir "model_test\llama-cpp\outputs\capswriter_1_7b_30s"
```

该路线的 `result.json` 会包含 VAD、merge、chunk 切分、每个 chunk 转录、文本合并和总耗时。
