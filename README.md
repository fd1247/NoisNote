# 音频转录与总结工具

一个 Windows 桌面应用，用于录制系统声音、录制麦克风或导入本地音视频文件，通过本地 ASR 模型将音频转录为文字，并可调用 OpenAI 兼容的 LLM API 对转录内容生成会议纪要式总结。

## 核心功能

- 录制 Windows 系统声音（WASAPI Loopback）或麦克风声音
- 导入本地音视频文件（支持拖拽导入），视频自动提取音轨
- 本地 ASR 模型转录音频，支持真实进度回传
- 调用 LLM API 生成总结，支持 Markdown 渲染
- 历史记录管理：查看、重命名、文件夹中打开、删除、复制文本、导出 Markdown
- 模型管理：下载、删除、多源下载（ModelScope + GitHub）
- 自动转录 / 自动总结 开关
- 结构化日志，便于问题诊断

## 运行环境

| 要求 | 说明 |
|------|------|
| 操作系统 | Windows 10/11 64 位 |
| VC++ 运行时 | [Visual C++ Redistributable 2015-2022 (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)。Windows 10/11 通常已预装；若启动报"缺少 VCRUNTIME140.dll"，请下载安装。 |
| 内存 | 0.6B 模型约需 2 GB，1.7B 模型约需 5 GB |
| 磁盘 | 0.6B 模型约 570 MB，1.7B 模型约 1.4 GB；建议预留 5 GB 以上 |
| ffmpeg | 导入视频或非 WAV 音频时需要。运行 `python scripts/download_deps.py` 自动下载，或手动安装到 PATH。 |
| ASR 推理 | 默认 CPU 推理。有独显时可选择 GPU（DirectML）加速。 |

## 运行方式

### 方式一：源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/fd1247/NoisNote.git
cd NoisNote

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 下载第三方二进制依赖（llama.cpp DLL + ffmpeg）
python scripts/download_deps.py

# 4. 启动
python main.py
```

### 方式二：打包运行

1. 从 [GitHub Releases](https://github.com/fd1247/NoisNote/releases) 下载最新版本的 `NoisNote-{version}.zip`
2. 解压到任意目录
3. 确保已安装 [VC++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe)
4. 运行 `NoisNote.exe`

## 快速上手

### 首次启动

启动后自动进入录音页面。首次使用时应用会导入一段示例音频，方便快速体验完整流程。

### 录制音频

1. 在录音页面顶部选择录音源：**系统声音**（默认）或 **麦克风**
2. 如需指定设备，可在下方设备下拉框中选择
3. 点击 **开始录音** 按钮开始捕获音频
4. 录音过程中会显示时长和音量电平
5. 点击 **停止录音** 结束录制，音频自动保存并进入历史记录

### 导入本地文件

- 点击侧边栏 **导入本地音视频** 按钮选择文件
- 或将文件直接 **拖拽** 到应用窗口
- 支持格式：WAV、MP3、M4A、AAC、FLAC、OGG、WMA、MP4、MOV、MKV、AVI、WebM

### 查看转录结果

- 录制或导入完成后，如开启了自动转录，应用会自动开始转录
- 也可在记录详情页手动点击 **开始转录**
- 转录完成后，在 **转录文本** 标签页查看识别出的文字
- 点击 **复制** 按钮可将文本复制到剪贴板

### 生成总结

- 转录完成后，如开启了自动总结，应用会自动调用 LLM 生成总结
- 也可在 **总结内容** 标签页手动点击 **手动总结**
- 总结内容支持 Markdown 渲染，可直接复制使用

### 设置

点击侧边栏底部齿轮图标进入设置页面。

| 设置项 | 说明 |
|--------|------|
| ASR 模型 | 选择用于转录的本地模型 |
| 推理设备 | auto（自动）/ cpu / gpu |
| LLM 供应商 | OpenAI 兼容（默认）或 Anthropic |
| API Key | LLM 服务的 API 密钥 |
| 模型名称 | LLM 模型标识，如 `gpt-4o-mini` |
| Base URL | LLM API 地址 |
| 自动转录 | 录制/导入后自动开始转录 |
| 自动总结 | 转录完成后自动生成总结 |

### 模型管理

在 **模型** 页面可以下载、查看和删除 ASR 模型：

- **Qwen3-ASR-0.6B-GGUF**（推荐）：约 570 MB，速度更快，适合日常使用
- **Qwen3-ASR-1.7B-GGUF**：约 1.4 GB，识别精度更高

### 历史记录管理

- 左侧边栏显示所有历史记录，按时间倒序排列
- 点击记录查看详情（转录文本和总结内容）
- 鼠标移到记录项出现三点菜单，可 **重命名**、**在文件夹中打开**、**删除**

### 文件存储位置

所有用户数据默认保存在 `文档/NoisNote/` 目录下：

```
NoisNote/
├── data/          # 历史记录（每条一个文件夹）
│   ├── 20250627_143022/
│   │   ├── audio.wav           # 音频文件
│   │   ├── transcript.txt      # 转录文本
│   │   ├── summary.txt         # 总结内容
│   │   └── metadata.json       # 元数据
│   └── ...
├── models/        # ASR 模型文件
└── logs/          # 诊断日志
```

## LLM API 配置

应用调用 OpenAI 兼容的 Chat Completions 接口。例如：

| 配置项           | 值                        |
| :-------------- | :----------------------- |
| **LLM 服务商**   | OpenAI 兼容               |
| **LLM API Key** | ●●●●●●●●●●●●●●●          |
| **LLM 模型**     | deepseek-v4-flash        |
| **Base URL**    | https://api.deepseek.com |

需要填写服务商提供的 API Key 和模型名。API Key 存储在本地配置文件中，不会上传。

## 常见问题

### 未找到 loopback 设备

请确认系统有可用的扬声器或耳机输出设备，且处于启用状态。某些虚拟设备可能不支持 Loopback。

### 转录很慢

CPU 推理可能较慢，尤其是 1.7B 模型。可在设置中选择更快的 0.6B 模型，或在有独显时选择 GPU（DirectML）加速。

### 模型下载失败

模型从 ModelScope（优先）或 GitHub 下载。请检查网络环境、代理设置和磁盘空间。下载失败或取消后可重新在模型页面下载。

### 总结失败

请检查：API Key 是否正确、Base URL 是否正确、模型名是否被服务商支持、网络连接是否正常、API 账户余额或额度是否充足。

### 导入音频后没有自动转录

请在设置的"通用"页确认"自动转录"已开启。关闭时，需在记录详情中手动开始转录。

### 导入视频转录音频失败

请运行 `python scripts/download_deps.py` 下载内置 ffmpeg，或手动安装到系统 PATH。
