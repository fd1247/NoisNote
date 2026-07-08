# 发布与更新指南

本文档说明音频转录与总结工具的版本管理、发布流程、构建流程、版本检查机制和用户更新方式。

## 版本号规范

项目遵循 [语义化版本规范 (SemVer)](https://semver.org/)：

```
major.minor.patch[-pre_release]
```

| 字段 | 说明 | 示例 |
|------|------|------|
| major | 主版本号，不兼容的 API 变更 | 1.0.0 -> 2.0.0 |
| minor | 次版本号，向后兼容的功能新增 | 1.0.0 -> 1.1.0 |
| patch | 修订号，向后兼容的问题修复 | 1.0.0 -> 1.0.1 |
| pre_release | 预发布标识（空字符串 = 正式版） | 1.0.0-beta、1.0.0-rc1 |

### 版本号定义位置

版本号集中定义在 `src/app/version.py`：

```python
APP_VERSION = VersionInfo(0, 1, 0, "")
```

发布时由 `scripts/release.py` 自动更新此文件。

### 版本号使用场景

| 场景 | 使用方式 |
|------|---------|
| 窗口标题 | `MainWindow.setWindowTitle()` 包含版本号 |
| 设置页面 | 显示"当前版本：0.1.0" |
| Qt 应用元数据 | `QApplication.setApplicationVersion()` |
| 启动日志 | 记录版本号到日志 |
| exe 文件属性 | 嵌入 Windows 版本信息（打包时） |
| GitHub Release tag | `v0.1.0` 格式 |
| zip 文件名 | `NoisNote-0.1.0.zip` |

## 发布流程

### 前置条件

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. 安装 [GitHub CLI (gh)](https://cli.github.com/) 并登录：
   ```bash
   gh auth login
   ```

3. 运行 `python scripts/download_deps.py` 下载 llama.cpp DLL 和 ffmpeg 到 `vendor/` 目录

### 完整发布步骤

```bash
python scripts/release.py --version 0.2.0
```

脚本自动执行：

```
1. 检查 Git 工作目录是否干净
2. 更新 src/app/version.py 和 file_version_info.txt 中的版本号
3. 提交版本号变更 (git commit)
4. 创建 Git tag (git tag v0.2.0)
5. 推送到 GitHub (git push)
6. 执行 scripts/build.py 生成发布产物
7. 生成 release notes 模板
8. 调用 gh CLI 创建 GitHub Release
9. 上传 zip 和 SHA256 校验文件
```

### 预览发布流程（dry-run）

```bash
python scripts/release.py --version 0.2.0 --dry-run
```

### 发布产物

| 产物 | 路径 | 说明 |
|------|------|------|
| 便携版目录 | `dist/NoisNote/` | 包含 exe 和所有依赖 |
| zip 压缩包 | `dist/NoisNote-{version}.zip` | 用户下载的分发包 |
| SHA256 校验文件 | `dist/NoisNote-{version}.zip.sha256` | 完整性校验 |

### 发布后检查

1. 访问 GitHub Releases 页面确认产物已上传
2. 下载 zip 文件，解压后测试启动
3. 确认版本号显示正确

## 构建流程

### 单独执行构建

```bash
python scripts/build.py
```

### 构建流程

```
build.py
  +-- 读取 src/app/version.py 获取版本号
  +-- 生成 file_version_info.txt（Windows exe 版本信息）
  +-- 调用 PyInstaller 执行 build.spec
  |     +-- 收集依赖（PySide6、numpy、scipy、onnxruntime、soundfile）
  |     +-- 收集资源（src/assets、src/ui/detail/assets、ffmpeg、vendor/qwen3-asr-gguf）
  |     +-- 生成 dist/NoisNote/ 目录
  +-- 创建 zip 压缩包
  +-- 生成 SHA256 校验文件
```

### 打包内容

| 内容 | 来源路径 | 打包后路径 |
|------|---------|-----------|
| 应用代码 | `src/` | `_internal/src/` |
| 应用资源 | `src/assets/` | `_internal/src/assets/` |
| 详情 WebView 资源 | `src/ui/detail/assets/` | `_internal/src/ui/detail/assets/` |
| ffmpeg | `vendor/ffmpeg/` | `_internal/src/vendor/ffmpeg/` |
| GGUF 推理工具 | `vendor/qwen3-asr-gguf/` | `_internal/vendor/qwen3-asr-gguf/` |
| PySide6 插件 | 自动收集 | `_internal/PySide6/` |
| numpy / scipy | 自动收集 | `_internal/numpy/`、`_internal/scipy/` |
| onnxruntime | 自动收集 | `_internal/onnxruntime/` |
| soundfile | 自动收集 | `_internal/soundfile/` |

`src/ui/detail/assets/vendor/` 中的 Markdown 渲染库会随详情 WebView 一起打包，应用运行时不依赖 CDN 或公网加载这些前端资源。

### 不包含的内容

- ASR 模型文件（用户通过应用内下载）
- 开发工具（pytest、pylint 等）
- 测试文件
- 用户数据目录（配置、历史记录、模型、日志、cookies）

### 打包体积参考

目标控制在 300 MB 以内（不含模型）。当前约 320 MB，主要来自 PySide6 Qt 库和 llama.cpp Vulkan DLL（~55 MB）。

## 版本检查机制

### 检查时机

| 时机 | 方式 | 是否阻塞 UI |
|------|------|------------|
| 应用启动 | 自动后台检查 | 不阻塞 |
| 设置页面 | 用户点击"检查更新"按钮 | 同步等待 |

### 版本检查逻辑

1. 请求 GitHub API：`https://api.github.com/repos/{owner}/{repo}/releases/latest`
2. 解析 `tag_name` 字段作为最新版本号
3. 使用 `VersionInfo.__lt__()` 比较当前版本和最新版本
4. 返回 `UpdateInfo` 对象

### 缓存机制

- 缓存有效期：1 小时
- 缓存期内重复检查直接返回缓存结果

### 错误处理

版本检查失败时静默处理，不影响应用正常使用。错误记录到日志。

## 用户更新方式

### 更新流程

1. 应用启动时自动检查新版本
2. 发现新版本 → 显示更新提示对话框
3. 点击"下载更新" → 跳转浏览器打开 GitHub Releases 页面
4. 下载 zip 文件 → 解压到原目录（覆盖安装）
5. 启动新版本

### 数据保留

覆盖安装时以下数据不会丢失（位于用户 Documents 目录，与安装目录独立）：

| 数据 | 路径 |
|------|------|
| 配置文件 | `%APPDATA%/NoisNote/config.json` |
| 历史记录 | `~/Documents/NoisNote/data/` |
| 模型文件 | `~/Documents/NoisNote/models/` |
| 日志文件 | `~/Documents/NoisNote/logs/` |

## 常见问题

### 发布脚本中途失败怎么办？

1. 检查 Git 状态：`git status`
2. 如版本号已更新但未提交，手动提交或回退
3. 如 tag 已创建但未推送，手动推送：`git push origin v0.2.0`
4. 如构建失败，修复后手动执行 `python scripts/build.py`
5. 手动创建 Release：`gh release create v0.2.0 dist/NoisNote-0.2.0.zip dist/NoisNote-0.2.0.zip.sha256`

### 如何创建预发布版本？

```bash
python scripts/release.py --version 0.2.0-beta
```

### 如何准备 ffmpeg 和 llama.cpp DLL？

运行 `python scripts/download_deps.py` 自动下载。脚本从 BtbN/FFmpeg-Builds 下载 ffmpeg，从 GitHub llama.cpp Releases 下载预编译 DLL，并校验 SHA-256。

### 打包后体积多大？

目标 300 MB 以内。实际体积取决于 PySide6 和依赖版本。
