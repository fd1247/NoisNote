# 音频转录与总结工具

一个 Windows 桌面应用，用于录制系统声音、录制麦克风或导入本地音视频文件，通过本地 ASR 模型将音频转录为文字，并可调用 OpenAI 兼容的 LLM API 对转录内容生成会议纪要式总结。

## 核心功能

- 录制 Windows 系统声音（WASAPI Loopback）或麦克风声音
- 导入本地音视频文件（支持拖拽导入），视频自动提取音轨
- 从 YouTube / Bilibili 等公开视频链接导入，优先使用外部字幕，字幕不可用时下载音频
- 本地 ASR 模型转录音频，支持真实进度回传
- 任务管理：录音、转录、总结和链接导入统一显示任务状态；处理任务串行排队，可排序、取消、重试和移除
- 逐句时间轴：启用时间戳后可随音频回放高亮句子和 token，并可导出 SRT
- 调用 LLM API 生成总结，支持本地 WebView Markdown 渲染
- 历史记录管理：查看、重命名、文件夹中打开、删除、复制文本、导出转录/字幕/总结
- 模型管理：下载、查看、删除 ASR 模型和 ForceAligner 时间戳辅助模型
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
| yt-dlp | 从链接导入公开视频时需要。源码运行会随 `requirements.txt` 安装。 |
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

### 从链接导入

点击侧边栏 **从链接导入**，输入公开视频链接后应用会在后台解析链接。

- 优先下载外部字幕，生成转录文本和逐句时间轴
- 如果没有可用字幕，或字幕下载/解析失败，会自动降级为下载音频并标准化为 `audio.wav`
- 链接解析、字幕下载、音频下载和转码都在后台线程中执行，不会阻塞主界面
- 视频超过 2 小时，或无法确认时长时，会先弹窗确认

部分 YouTube / Bilibili 视频需要登录态或 cookies。请将 Netscape 格式 cookies 文件保存到用户数据目录：

```
文档/NoisNote/
├── bilibili_cookies.txt
└── youtube_cookies.txt
```

cookies 文件不要放在仓库目录，也不要提交到 Git。可使用浏览器扩展或 `yt-dlp --cookies-from-browser` 导出为 Netscape cookies 格式。

### 查看转录结果

- 录制或导入完成后，如开启了自动转录，应用会自动开始转录
- 也可在记录详情页手动点击 **开始转录**
- 转录完成后，在 **转录文本** 标签页查看识别出的文字；详情区域使用本地 WebView 渲染，WebEngine 不可用时会自动降级为 Qt 文本控件
- 如果在设置中启用时间戳并已下载 ForceAligner 辅助模型，可在 **逐句时间轴** 标签页查看分段结果，播放音频时会高亮当前句子和 token
- 点击 **复制** 按钮可将文本复制到剪贴板

### 生成总结

- 转录完成后，如开启了自动总结，应用会自动调用 LLM 生成总结
- 也可在 **总结内容** 标签页手动点击 **手动总结**
- 总结内容以 Markdown 保存和渲染，可直接复制源 Markdown 使用
- 为了保持详情页安全策略，HTML 内联样式不会生效；普通 Markdown 标题、列表、表格、链接、代码块等语法正常显示

### 任务管理

处理任务会在右侧的 **任务管理** 面板中按“处理中、排队中、已处理”展示。录音、导入本地文件、从链接导入、转录和总结的进度都会同步显示在这里。

- 转录、总结和链接导入按顺序执行；“排队中”最多可保留 20 项等待任务。可拖拽排队任务调整先后顺序。
- 对正在处理的任务点击取消后，会先显示“正在取消”；后台任务实际结束后才会转入已处理列表，并启动下一项。
- 已完成、失败或已取消的任务可重试或移除。仅总结任务重试时会直接重新总结，不会重新转录。
- 同一条记录已在处理中或排队中时，再次点击转录不会创建重复任务；如仍在排队，会合并新的处理选项。
- 如果模型或运行环境出现系统性错误，应用会说明原因和修复指引，并暂停剩余任务。修复后，在“排队中（数量）”右侧点击 **恢复队列** 即可继续；没有排队任务时不会显示该按钮。

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
| 时间戳 | 转录后生成逐句时间轴，需要下载 ForceAligner 辅助模型 |

### 模型管理

在 **模型** 页面可以下载、查看和删除 ASR 模型：

- **Qwen3-ASR-0.6B-GGUF**（推荐）：约 570 MB，速度更快，适合日常使用
- **Qwen3-ASR-1.7B-GGUF**：约 1.4 GB，识别精度更高
- **Qwen3-ForceAligner-0.6B-GGUF**：用于时间戳对齐，只有启用逐句时间轴时需要

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
│   │   ├── external_subtitle.srt # 链接导入的外部字幕（按需生成）
│   │   ├── transcript.txt      # 转录文本
│   │   ├── summary.md          # 总结内容（Markdown）
│   │   ├── timeline.json       # 逐句时间轴（按需生成）
│   │   ├── transcript.srt      # SRT 字幕导出（按需生成）
│   │   └── metadata.json       # 元数据
│   └── ...
├── models/        # ASR 模型文件
├── bilibili_cookies.txt # Bilibili 登录态（可选）
├── youtube_cookies.txt  # YouTube 登录态（可选）
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

### 任务队列暂停

这通常表示转录模型目录、模型文件、GGUF 运行工具、运行时依赖或模型配置不完整。请按弹窗提示修复模型或运行环境；如果仍有排队任务，修复后可在任务管理面板点击 **恢复队列**。单个普通转录失败不会暂停后续队列任务。

### 导入音频后没有自动转录

请在设置的"通用"页确认"自动转录"已开启。关闭时，需在记录详情中手动开始转录。

### 导入视频转录音频失败

请运行 `python scripts/download_deps.py` 下载内置 ffmpeg，或手动安装到系统 PATH。

### 从链接导入失败

请先确认网络可访问目标网站，并已安装 `yt-dlp`。如果提示需要登录或 cookies 无效，请把 Netscape 格式 cookies 分别保存为 `文档/NoisNote/bilibili_cookies.txt` 或 `文档/NoisNote/youtube_cookies.txt` 后重试。

YouTube 若提示 n challenge、格式不可用或只有图片格式，源码运行时请确保 Node.js 可用，并可访问 yt-dlp 所需的远程组件；也可尝试更新 yt-dlp：

```bash
python -m pip install -U "yt-dlp[default]"
```
