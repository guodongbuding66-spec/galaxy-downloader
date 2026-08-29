# 通用媒体下载器

这是一个基于 [vinext](https://github.com/cloudflare/vinext) 运行的 Next.js App Router 兼容项目，支持从 Bilibili、YouTube、抖音、Instagram、小红书、TikTok、X、Telegram、Threads、微信公众号、微博、Niconico、Vimeo、Dailymotion、Streamable、Reddit、Newgrounds、Tumblr、Pinterest、VK、OK.ru、Twitch、SoundCloud 等平台解析和下载公开媒体内容。

## 功能特点

- 🎬 视频 / 音频 / 图文统一解析与下载
- 🎚️ **高级画质选择**：最佳画质、8K、4K、2K、1080p、720p、480p、360p 等预设；解析后端返回具体格式时优先展示真实可用格式
- 🎵 **音频质量选择**：最佳、320 / 256 / 192 / 128 / 64 kbps 预设
- 🖼️ **封面下载**：解析结果提供封面时可直接保存原始封面
- 💬 **字幕下载**：兼容解析器返回的手动字幕和自动字幕轨道，支持 VTT / SRT / ASS 等原始格式
- 🧾 **媒体信息导出**：一键导出标题、平台、原始链接、时长、画质、字幕和封面信息为 JSON
- 🧠 **解析能力兼容层**：兼容 `qualityOptions`，也会识别常见 yt-dlp 风格的 `formats`、`subtitles`、`automatic_captions`
- 🛡️ **下载代理**：外部媒体流统一经过 `/api/download`，降低 YouTube `googlevideo.com` 临时链接因 IP / 签名导致 403 的概率
- 🎞️ 高画质下载优先使用原始页面 URL + `type=video&quality=...` 重新向解析后端选择流，不再固定复用解析阶段返回的单一低清 CDN 地址
- 🎧 浏览器端 FFmpeg.wasm 音频提取、音视频合并
- 📦 图文内容批量下载 / ZIP 打包
- 📺 HLS / M3U8 浏览器端分片下载
- 💾 本地下载历史记录
- 🌍 多语言界面（简中、繁中、英文、日文、西班牙文、俄文）
- ✅ GitHub Actions 自动运行测试、Lint 与生产构建

> 清晰度、字幕、音轨和容器格式最终取决于目标平台本身以及所连接解析后端实际返回的能力。项目不会绕过 DRM、付费墙、登录权限或其他访问控制。

## 高级下载逻辑

解析成功后，结果卡片会保留原来的快速“下载视频 / 下载音频”按钮，同时增加高级下载区：

1. **视频清晰度**
   - 如果解析器返回 `qualityOptions` / `formats`，界面优先展示真实格式、分辨率、FPS、容器和文件大小信息。
   - 如果没有返回格式表，则提供通用画质预设。
   - “最佳画质”与普通视频下载会重新使用原始页面 URL 请求后端选择媒体流，而不是直接打开可能较低清晰度的临时 CDN URL。
2. **音频质量**
   - 提供最佳、320、256、192、128、64 kbps 预设，并通过统一下载 API 请求。
3. **附加资源**
   - 下载原始封面。
   - 解析器提供字幕轨道时选择语言并下载字幕。
   - 导出媒体信息 JSON。
   - 复制当前原始媒体链接。
4. **多集 / 多 P**
   - 高级选项会优先读取当前选中分集的格式与字幕能力。
   - Bilibili 多 P 会把当前 `p` 参数写回源链接后再请求下载。
5. **偏好记忆**
   - 最近选择的视频画质和音频质量保存在浏览器 Local Storage，下次继续使用。

## 开始使用

```bash
pnpm install
pnpm dev
```

在浏览器中打开 `http://localhost:3010`。

## 使用方法

1. 复制媒体链接。
2. 粘贴到输入框并点击“解析”。
3. 使用快速下载按钮，或在“高级下载选项”中选择画质 / 音质。
4. 需要时下载封面、字幕或媒体信息 JSON。
5. 等待浏览器保存文件。

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

- **YouTube**: 视频、音频；实际最高画质由解析后端与视频本身决定
- **Bilibili**: 视频、音频、多 P / 合集、分享口令
- **Bilibili TV**: 音频
- **抖音**: 视频、图文、分享口令
- **Instagram**: Reels、帖子、图文
- **小红书**: 视频、图文
- **TikTok**: 视频
- **X / Twitter**: 视频
- **Telegram**: 视频
- **Threads**: 视频、图文
- **微信公众号**: 文章视频、多视频
- **微博**: 视频、图文、多视频
- **Niconico**: 视频
- **Vimeo / Dailymotion / Streamable**: 视频
- **Reddit / Newgrounds / Tumblr**: 媒体内容
- **Pinterest**: 图片、视频
- **VK / OK.ru / Twitch**: 视频
- **SoundCloud**: 音频
- **Apple Podcasts**: 节目 / 单集音频
- **HLS / M3U8**: 播放列表解析与浏览器端下载

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

## 测试与质量检查

```bash
pnpm test
pnpm lint
pnpm build
```

`.github/workflows/ci.yml` 会在 `main` 与 `feature/**` 分支自动执行以上检查，防止功能修改直接破坏生产部署。

## API 配置

部署时建议配置：

- `NEXT_PUBLIC_API_BASE_URL`: 公开解析 / 下载 API，例如 `https://downloader-api.bhwa233.com`
- `NEXT_PUBLIC_SITE_URL`: 当前站点公开地址
- `SEO_INDEXABLE`: `true` / `false`

本项目使用的主要 API 入口：

- `GET /api/parse?url=...`：解析媒体信息
- `GET /api/download?url=stream_url`：代理已有媒体流
- `GET /api/download?url=source_url&type=video&quality=...`：按源链接请求视频 / 指定画质（兼容 Galaxy Downloader 历史统一下载接口）
- `GET /api/download?url=source_url&type=audio&quality=...`：按源链接请求音频
- `GET /api/play?...`：播放代理

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

## 负责任使用

本项目用于下载你有权保存、平台允许下载或公开授权的媒体。请遵守目标平台条款和当地法律。项目不设计用于绕过 DRM、付费内容、登录限制、验证码、地区限制或其他访问控制。
