# 通用媒体下载器

这是一个基于 [vinext](https://github.com/cloudflare/vinext) 运行的 Next.js App Router 兼容项目，支持从 Bilibili、YouTube、抖音、Instagram、小红书、TikTok、X、Telegram、Threads、微信公众号、微博、Niconico、Vimeo、Dailymotion、Streamable、Reddit、Newgrounds、Tumblr、Pinterest、VK、OK.ru、Twitch、SoundCloud 等平台解析和下载公开媒体内容。

## 功能特点

- 🎬 视频 / 音频 / 图文统一解析与下载
- 🎚️ **高级画质选择**：最佳画质、8K、4K、2K、1080p、720p、480p、360p 等预设；解析后端返回具体格式时优先展示真实可用格式
- 🎵 **音频质量选择**：最佳、320 / 256 / 192 / 128 / 64 kbps 预设
- 🖼️ **封面处理**：本机最终文件可按需内嵌封面；图文/封面原图可单独保存
- 💬 **字幕处理**：兼容手动字幕和自动字幕轨道，本机最终文件可按需内嵌字幕
- 🧾 **媒体信息导出**：可导出标题、平台、原始链接、时长、画质、字幕和封面等信息
- 🧠 **解析能力兼容层**：兼容 `qualityOptions`，也会识别常见 yt-dlp 风格的 `formats`、`subtitles`、`automatic_captions`
- 🛡️ **下载 / 播放代理**：外部媒体流经过受控 API 路径，支持 Range 播放并降低部分临时 CDN 链接直接访问失败的概率
- 🎞️ 默认本机媒体下载保存一个最终成品文件：优先最佳视频 + 最佳音频，需要时由 FFmpeg 合并
- 🎧 浏览器端 FFmpeg.wasm 音频提取、音视频合并作为兼容/辅助能力
- 📦 图文内容批量下载 / ZIP 打包
- 📺 HLS / M3U8 浏览器端分片下载
- 🧰 **Galaxy Local Engine 0.8.0**：Windows 本机 yt-dlp + FFmpeg、登录状态解析、原图下载、动态文档渲染、任务队列
- 🗂️ **最近解析记录**：解析成功的链接只保存在当前浏览器本地；它不代表文件已下载完成
- ♻️ **可选跳过已下载内容**：Local Engine 可用独立 download archive 跳过已完成媒体，默认关闭
- 🌍 多语言界面（简中、繁中、英文、日文、西班牙文、俄文）
- ✅ GitHub Actions 自动运行测试、Lint、生产构建、Windows 成品测试和 live smoke

> 清晰度、字幕、音轨和容器格式最终取决于目标平台本身以及所连接解析后端实际返回的能力。项目不会绕过 DRM、付费墙、登录权限或其他访问控制。

## Galaxy Local Engine 0.8.0

当前网页要求 **Galaxy Local Engine 0.8.0+**。网站主下载和 GitHub 备用线路都固定到准确的 `local-engine-v0.8.0` Release，不再跟随 `releases/latest`，避免网页升级后用户意外下载到不匹配的旧引擎。

### 安装

1. 下载 `GalaxyLocalEngine-Windows.zip`。
2. **完整解压**到长期使用的目录，不要直接在 ZIP 内运行。
3. 双击 `install.cmd`。
4. 使用本机解析/下载时保持 `GalaxyLocalEngine.exe` 运行。
5. 最终媒体和本机下载图片保存在解压目录的 `downloads` 文件夹。

Release ZIP 已内置经过校验的 `yt-dlp.exe`、FFmpeg 和 FFprobe，安装过程默认不依赖 GitHub 在线下载这些运行时依赖。

### 默认下载策略

- 默认只保存最终成品：最佳视频 + 最佳音频，需要时合并。
- 字幕与封面内嵌均为可选项。
- 默认不保留独立 thumbnail、info JSON、description、comments、playlist metadata 等 sidecar 文件。
- Local Engine 使用 `--ignore-config`，避免用户机器上的全局 yt-dlp 配置静默改变 Galaxy 输出策略。
- 合集支持“当前一项 / 整个合集 / 选择部分”。
- 当前任务执行时还能继续提交任务；Local Engine 使用有界 FIFO 队列，最多保留 25 个等待任务。
- 网页会显示队列长度 / 容量，队列满时明确阻止继续提交。

### 跳过已下载内容

“跳过已下载内容”默认**关闭**。开启后，Local Engine 使用：

```text
state/download-archive.txt
```

记录 yt-dlp 已完成的媒体 ID。这个状态文件不会写入 `downloads` 目录，也不会把浏览器“最近解析”误当成下载完成记录。

### Local Bridge 状态语义

网页通过 loopback Bridge 与常驻 Local Engine 通信。媒体提交现在返回稳定的 HTTP 状态和 `code`：

- `202 ACCEPTED`：立即开始。
- `202 QUEUED`：进入等待队列。
- `400 BAD_REQUEST`：任务参数或源 URL 无效。
- `409 QUEUE_FULL`：等待队列已满。
- `503 ENGINE_SHUTTING_DOWN`：Local Engine 正在退出。
- `504 ENGINE_HANDOFF_TIMEOUT`：桌面 UI 线程没有在规定时间内接收/拒绝任务。

网页保留 `code + status` 并对队列/生命周期错误做多语言提示，不再依赖解析英文错误字符串。

### 文档与原图

Local Engine 的图文/网页解析链路依次尝试：

1. 平台/文档专用解析；
2. 静态 HTML、metadata、JSON-LD、hydration 数据；
3. 明确需要登录时的认证重试；
4. 用户机器已安装的 Edge / Chrome CDP 动态渲染；
5. yt-dlp 媒体兜底。

公众号等富文本文章可保留可识别的标题、段落顺序、链接、列表、引用、代码块、表格和图片位置。原图下载支持本机直连、有限重试、取消、`.part` 清理、磁盘空间检查以及需要时的 WebP/AVIF 转换和 ZIP 打包。

## 高级下载逻辑

解析成功后，结果工作台提供统一下载设置：

1. **视频清晰度**
   - 如果解析器返回 `qualityOptions` / `formats`，界面优先展示真实格式、分辨率、FPS、容器和文件大小信息。
   - 如果没有返回格式表，则使用通用画质策略。
   - 本机下载会把所选画质约束交给 Local Engine；最终可用格式仍取决于平台和 yt-dlp 实际提取结果。
2. **音频质量**
   - 提供最佳、320、256、192、128、64 kbps 等选择。
   - 正常视频默认合并音频；关闭“合并音频”时才只保留视频轨。
3. **附加资源**
   - 字幕和封面默认关闭，需要时可嵌入最终文件。
   - 图文内容可保存原图、文本 / Markdown 或打包 ZIP。
4. **多集 / 多 P / 合集**
   - 高级选项优先读取当前选中分集的格式与字幕能力。
   - Bilibili 多 P 会保留当前 `p` 范围；其他合集可选择当前项、全部或指定项。
5. **本机任务控制**
   - 任务运行时显示速度、ETA、进度和已下载大小。
   - 可以取消当前任务、打开下载文件夹，并继续把后续任务加入等待队列。

## 开始使用

```bash
pnpm install
pnpm dev
```

在浏览器中打开 `http://localhost:3010`。

## 使用方法

1. 复制媒体、帖子、图文或 HLS 链接。
2. 粘贴到输入框并点击“解析”。
3. 在结果工作台预览内容并选择画质 / 音质 / 字幕 / 封面 / 合集范围。
4. 推荐使用 Galaxy Local Engine 下载最终成品；浏览器端处理保留为部分场景的兼容路径。
5. 需要时下载原图、文本、Markdown、ZIP 或使用音频处理工具。

### 常见链接格式

- **YouTube**: `https://youtu.be/...`、`https://www.youtube.com/watch?v=...`
- **Bilibili**: `https://www.bilibili.com/video/BV...`、`https://b23.tv/...`
- **抖音**: `https://www.douyin.com/...`、`https://v.douyin.com/...`
- **Instagram**: `https://www.instagram.com/reel/...`、`https://www.instagram.com/p/...`
- **小红书**: `https://www.xiaohongshu.com/explore/...`、`https://xhslink.com/...`
- **TikTok**: `https://www.tiktok.com/@.../video/...`
- **X**: `https://x.com/.../status/...`
- **Pinterest**: `https://www.pinterest.com/pin/...`
- **VK**: `https://vk.com/video...`
- **OK.ru**: `https://ok.ru/video/...`
- **Twitch**: Twitch clip / video URL
- **SoundCloud**: SoundCloud track URL

## 当前平台支持

- **YouTube**: 视频、音频；实际最高画质由解析后端 / yt-dlp 与视频本身决定
- **Bilibili**: 视频、音频、多 P / 合集、分享口令
- **Bilibili TV**: 音频
- **抖音**: 视频、图文、分享口令
- **Instagram**: Reels、帖子、图文 / carousel
- **小红书**: 视频、图文
- **TikTok**: 视频
- **X / Twitter**: 视频
- **Telegram**: 视频
- **Threads**: 视频、图文（支持程度取决于上游 extractor）
- **微信公众号**: 富文本文章、图片及可提取媒体
- **微博**: 视频、图文、多视频
- **Niconico**: 视频
- **Vimeo / Dailymotion / Streamable**: 视频
- **Reddit / Newgrounds / Tumblr**: 媒体内容
- **Pinterest**: 图片、视频
- **VK / OK.ru / Twitch**: 视频
- **SoundCloud**: 音频
- **Apple Podcasts**: 节目 / 单集音频
- **HLS / M3U8**: 播放列表解析与浏览器端下载

平台“支持”不代表任意 URL 在任意网络环境下一定可匿名下载。登录要求、平台反爬、地区限制、目标下架、上游 extractor 变化和云机房 IP 限制会影响实时结果。项目的 33-platform diagnostic 用于区分这些上游状态与 Local Engine 自身安装/运行故障。

## 技术栈

- vinext
- Next.js 16 App Router API 兼容层
- React 19
- Vite 8
- TypeScript 5
- Tailwind CSS
- shadcn/ui / Radix UI
- Fetch API
- FFmpeg.wasm
- JSZip
- Vitest
- Cloudflare Workers
- Python / yt-dlp / FFmpeg（Galaxy Local Engine）

## 测试与质量检查

```bash
pnpm test
pnpm lint
pnpm build
```

PR / 主分支还会额外执行：

- Local Engine URL / download / queue / archive / image / document policy tests
- 真实 loopback Bridge HTTP 语义测试
- Container Backend unit tests 与生产镜像启动
- Document / Container live smoke
- Windows source self-test、真实 Edge/Chrome CDP 测试
- PyInstaller `GalaxyLocalEngine.exe --self-test`
- 离线 yt-dlp / FFmpeg bundle 和安装 / 卸载 / 自定义协议生命周期测试
- 33-platform live diagnostic

## API 配置

部署时建议配置：

- `NEXT_PUBLIC_API_BASE_URL`: 公开解析 / 下载 API，例如 `https://downloader-api.bhwa233.com`
- `NEXT_PUBLIC_CONTAINER_API_BASE_URL`: Container Backend 公网地址；配置后网页播放优先使用专用 `/api/play`
- `NEXT_PUBLIC_SITE_URL`: 当前站点公开地址
- `SEO_INDEXABLE`: `true` / `false`

主要 API 入口：

- `GET /api/parse?url=...`：解析媒体信息
- `GET /api/download?url=stream_url`：代理已有媒体流 / 兼容下载路径
- `GET /api/download?url=source_url&type=video&quality=...`：按源链接请求视频 / 指定画质
- `GET /api/download?url=source_url&type=audio&quality=...`：按源链接请求音频
- `GET /api/play?url=source_url&type=video|audio`：Range-aware 播放代理
- `GET /api/image-proxy?...`：受控图片中转 / 原图兼容路径
- `GET /api/local-engine/download?version=0.8.0`：网站固定版本的 Local Engine Windows 包

如果解析后端返回更丰富的格式或字幕字段，前端会自动归一化并展示；如果后端没有提供某项能力，界面不会伪造不存在的字幕或格式文件。

## 本地开发

```bash
pnpm install
pnpm dev
```

生产构建：

```bash
pnpm build
pnpm start
```

## Cloudflare Workers 部署

默认使用 `vinext` 生成 `dist/` 构建产物。

本地直接部署：

```bash
pnpm deploy
```

如果 Cloudflare Builds 已经执行过 `pnpm build`：

```bash
pnpm deploy:ci
```

非生产分支预览：

```bash
pnpm deploy:preview
```

不要直接使用 `wrangler deploy` 替代上述 vinext 部署脚本。

## 安全边界

- Local Engine 的解析、下载、自定义协议、静态文档重定向和 CDP 请求使用统一的公网 HTTP(S) URL 校验策略。
- 本机 / 私网 / 保留地址、带凭据 URL、IPv6 zone identifier、混合公网/私网 DNS 结果和无法解析的主机在关键入口被拒绝。
- Next.js / Container 媒体和图片中转会校验重定向，并限制 Range 语法。
- Cloudflare 图片 / 媒体中转使用 Durable Object 做按客户端 IP 的固定窗口限流；图片响应还有大小上限。

这些应用层校验**不能宣称完全消除 DNS rebinding TOCTOU**：DNS 可能在验证和后续连接之间发生变化。生产部署仍应使用网络 / 容器 egress policy 阻止私网、link-local、云 metadata 地址，并用 Cloudflare/WAF/带宽配额做独立第二层保护。

## 负责任使用

本项目用于下载你有权保存、平台允许下载或公开授权的媒体。请遵守目标平台条款和当地法律。项目不设计用于绕过 DRM、付费内容、登录限制、验证码、地区限制或其他访问控制。
