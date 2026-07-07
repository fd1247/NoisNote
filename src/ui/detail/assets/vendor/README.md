# Detail Viewer Vendor Assets

本目录存放详情 WebView 使用的第三方 Markdown 渲染资源。它们随应用本地打包，供
`../index.html` 直接以相对路径加载，不依赖 CDN 或运行时网络访问。

## 为什么放在 vendor 目录

- 这些文件不是 NoisNote 自研业务代码，而是第三方前端库或插件。
- 桌面应用需要离线运行，WebView 页面受 CSP 限制，不能从公网动态加载脚本。
- PyInstaller 打包时需要把这一整组静态资源作为详情视图私有资源收集。
- 第三方文件集中存放，便于后续升级、license 审查和替换。

## 文件清单

| 文件 | 用途 | 来源/版本线索 |
| ---- | ---- | ---- |
| `markdown-it.min.js` | Markdown 核心解析器。 | `markdown-it 14.1.0`，MIT，`https://github.com/markdown-it/markdown-it` |
| `markdownit.css` | Markdown 插件配套样式，覆盖任务列表、alert、脚注、目录等 class。 | 项目随渲染样式整理的本地 CSS，需与当前插件输出 class 保持一致。 |
| `markdown-it-container.min.js` | 支持自定义容器块；当前用于 `alert-*` 提示块。 | `markdown-it-container 3.0.0`，MIT，`https://github.com/markdown-it/markdown-it-container` |
| `markdown-it-task-lists.js` | 支持 GitHub 风格任务列表。 | `markdown-it-task-lists 2.1.0`，ISC，`https://github.com/revin/markdown-it-task-lists` |
| `markdown-it-sub.min.js` | 支持下标语法。 | `markdown-it-sub 1.0.0`，MIT，`https://github.com/markdown-it/markdown-it-sub` |
| `markdown-it-sup.min.js` | 支持上标语法。 | `markdown-it-sup 1.0.0`，MIT，`https://github.com/markdown-it/markdown-it-sup` |
| `markdown-it-emoji.min.js` | 支持 emoji shortcode。 | `markdown-it-emoji 1.4.0`，MIT，`https://github.com/markdown-it/markdown-it-emoji` |
| `markdown-it-footnote.min.js` | 支持脚注语法。 | `markdown-it-footnote` 浏览器构建；当前文件未保留完整版本 banner。 |
| `markdown-it-front-matter.js` | 解析 Markdown front matter 元数据块。 | `markdown-it-front-matter` 浏览器构建；当前文件未保留完整版本 banner。 |
| `markdown-it-imsize.min.js` | 支持 Markdown 图片尺寸扩展语法。 | `markdown-it-imsize` 浏览器构建；当前文件未保留完整版本 banner。 |
| `markdown-it-inject-linenumbers.js` | 给渲染结果注入行号信息，便于定位和同步。 | `markdown-it-inject-linenumbers 0.2.0`，MIT，`https://github.com/digitalmoksha/markdown-it-inject-linenumbers` |
| `markdownItAnchor.umd.js` | 给标题生成锚点链接。 | `markdown-it-anchor` UMD 构建；当前文件未保留完整版本 banner。 |
| `markdownItTocDoneRight.umd.js` | 根据标题生成目录。 | `markdown-it-toc-done-right` UMD 构建；当前文件未保留完整版本 banner。 |
| `markdown-it-implicit-figure.js` | 将独立图片渲染为 `figure` / `figcaption` 结构。 | `https://github.com/arve0/markdown-it-implicit-figures`，文件头记录上游提交 `c709117`。 |
| `markdown-it-mark.min.js` | 支持 `==highlight==` 高亮语法。 | `markdown-it-mark 4.0.0`，MIT，`https://github.com/markdown-it/markdown-it-mark` |

## 维护规则

1. 新增或升级 vendor 文件时，同步更新本 README 的来源、版本和 license 信息。
2. 优先使用带 license banner 的浏览器构建；如果上游构建不带 banner，需要在本 README 中补充来源说明。
3. 不要在 vendor 文件中混入 NoisNote 业务逻辑；项目自研逻辑放在 `../detail-viewer.js`。
4. 修改 vendor 文件后，至少运行：

```bash
python -m pytest tests/test_detail_webview_optional.py -q
```
