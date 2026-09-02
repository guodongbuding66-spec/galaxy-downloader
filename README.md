# SparkDownloader / Galaxy Local Engine

SparkDownloader 是在线视频、音频、图文、网页文档与 HLS 下载工具。网页负责统一解析、结果工作台和本机引擎连接；**Galaxy Local Engine** 负责 Windows 本机的 yt-dlp、FFmpeg、浏览器登录状态复用、任务队列、历史、诊断和文件落盘。

- 网站：<https://galaxy-downloader.guodongbuding66.workers.dev/zh>
- 仓库：<https://github.com/guodongbuding66-spec/galaxy-downloader>
- 当前网页要求的 Local Engine：**0.14.0**
- 精确 Release：**`local-engine-v0.14.0`**

> 项目只处理用户有权访问的内容，不绕过 DRM、付费墙、账号权限、地区限制或其他访问控制。

## 当前能力

### 视频 / 音频

- 视频、音频、图文统一解析与下载。
- 8K / 4K / 2K / 1080p / 720p 等画质选择，以及多档音频质量。
- 默认本机输出最终成品：最佳视频 + 最佳音频，必要时 FFmpeg 合并。
- 手动字幕、自动字幕、字幕语言、音轨语言。
- 可选封面 / 字幕内嵌。
- 视频片段下载，例如 `01:20–03:45`。
- 按章节拆分。
- SponsorBlock 8 类过滤。
- aria2c 与高速 / 课程 / 去赞助等预设。
- HLS / M3U8。
- Playlist / 合集 / 多 P / 选择部分下载。

### 平台

主要覆盖 YouTube、Bilibili、抖音、小红书、Instagram、TikTok、X、Telegram、Threads、微博、微信公众号、Vimeo、Dailymotion、Niconico、Reddit、Pinterest、Twitch、SoundCloud、Apple Podcasts、VK、OK.ru、Tumblr、Newgrounds、Streamable 等。

平台“支持”不代表任意 URL 在任意网络环境都能匿名下载。平台反爬、登录要求、地区限制、内容下架、上游 extractor 变化和云机房 IP 都可能影响实时结果。

## Galaxy Local Engine 0.14.0

网页与 GitHub 下载地址都固定到准确的 **0.14.0**，不会跟随 `releases/latest` 漂移到不匹配版本。

Release ZIP 内置：

- `GalaxyLocalEngine.exe`
- `yt-dlp.exe`
- FFmpeg / FFprobe
- 安装 / 卸载脚本
- 自定义协议注册

打包依赖执行 SHA256 校验，首次安装不要求再在线下载这些运行时依赖。

### 安装

1. 下载 `GalaxyLocalEngine-Windows.zip`。
2. 完整解压到长期使用目录，不要直接在 ZIP 内运行。
3. 双击 `install.cmd`。
4. 使用本机解析 / 下载时保持 `GalaxyLocalEngine.exe` 运行。
5. 默认成品保存在引擎目录下的 `downloads/`。

### 浏览器登录复用

Local Engine 可复用本机 Edge、Chrome、Firefox 的 Cookie / 登录状态。Cookie 只在本机读取，不上传到 SparkDownloader 服务器。

## 任务中心与队列

0.14.0 已将桌面端生命周期统一到任务中心：当前任务、等待任务、成功、失败、取消、搜索、状态筛选。

当前调度模型：

```text
1 active job + waiting queue
```

队列支持单项删除、清空、上移 / 下移、批量移顶部 / 底部、批量删除、当前任务完成后暂停、继续队列。

当前“并发 1 / 2 / 4 / 8 / 16”指**单个任务内部媒体分片并发**，不是多个任务同时运行。

## 下载历史与智能重试

下载历史支持持久化、搜索、状态筛选、打开文件、定位文件、复制脱敏 URL、清空和重新下载。

0.14.0 会区分网络、429、Cookie / 登录、磁盘、地区限制、内容失效、FFmpeg、解析器、403 和未知错误。429 可自动降为低分片 / 低速配置；普通网络问题使用弱网策略；登录、磁盘、地区限制不会无脑循环重试。

## 网络与文件管理

网络模式：标准 / 弱网增强 / 快速失败。单任务内部支持 1 / 2 / 4 / 8 / 16 分片和 1–100 Mbps 限速，默认不限速。

文件名支持：

- `标题 [ID]`
- `仅标题`
- `ID - 标题`

并可按 YouTube / Bilibili 等来源建立子目录。

> 0.14.0 仍以引擎 `downloads/` 为默认根目录。完整的多目录 / NAS / 移动硬盘目录管理器属于后续版本。

## 下载 Archive

“跳过已经下载过的内容”是**可选项，默认关闭**。开启后使用：

```text
state/download-archive.txt
```

记录 yt-dlp 已完成媒体 ID；关闭时允许重新下载同一内容。

## 图文 / 文档

图文能力包括原图本机直下、WebP / AVIF 转换、多图 ZIP、失败重试、`.part` 清理、磁盘检查和 CBZ。ZIP / CBZ 可生成 `metadata.json`，保留作者、发布时间、来源、原图 URL 与本地文件映射。

微信公众号等富文本页面可保留标题、段落、链接、列表、引用、代码、表格与图片位置，并支持 Markdown / 文本。

动态页面解析链路：

1. 平台 / 文档专用解析；
2. 静态 HTML、metadata、JSON-LD、hydration；
3. 登录重试；
4. 本机 Edge / Chrome CDP；
5. yt-dlp fallback。

## 磁盘、提醒与诊断

- 下载目录剩余空间与低空间阈值提醒。
- 可选 Windows 系统声音与任务栏闪烁。
- 本地日志、搜索、复制、清空、打开目录、容量限制。
- URL / token / cookie / password 等字段脱敏。

## 安全边界

- Local Bridge 只监听 `127.0.0.1`。
- 浏览器 Cookie 留在本机。
- 公网 URL 执行安全校验。
- FFmpeg / yt-dlp 发布依赖执行 SHA256 校验。
- GitHub Actions 第三方 Action 固定 immutable commit SHA。
- CI 包含 CodeQL 与依赖 / 安全审计。

## Local Bridge 状态语义

- `202 ACCEPTED`：立即开始。
- `202 QUEUED`：进入等待队列。
- `400 BAD_REQUEST`：参数或 URL 无效。
- `409 QUEUE_FULL`：等待队列已满。
- `503 ENGINE_SHUTTING_DOWN`：引擎正在退出。
- `504 ENGINE_HANDOFF_TIMEOUT`：桌面 UI 未在规定时间接收 / 拒绝任务。

## 当前工程缺口

### P0

- Dailymotion HLS 受 CDN / HTTP 指纹策略影响，必须持续通过真实媒体 Smoke 验证。
- Vimeo 需要持续监控偶发控制面 timeout。
- `main` 需要强制 required checks / Ruleset 或 Branch Protection。
- 发布流程目标：

```text
PR
  -> Preview / Staging
  -> real-media smoke
  -> required checks green
  -> Merge
  -> Production
  -> post-deploy smoke
  -> alert / rollback on failure
```

### P1

- 真正的活动任务 Pause / Resume / 重启恢复。
- 批量 URL 工作台与 TXT / CSV 导入。
- 多任务同时下载 Scheduler。
- 完整自定义下载目录。
- 一键安全自升级与失败回滚。

### P2

- macOS / Linux。
- 桌面 GUI 自动化、高 DPI、小分辨率回归。
- Web / Desktop 任务中心进一步统一。

## 开发与测试

```bash
pnpm install
pnpm dev
```

默认开发端口：`http://localhost:3010`。

```bash
pnpm test
pnpm lint
pnpm build
```

自动化覆盖包括 TypeScript / Vitest、ESLint、生产构建、Local Engine policy tests、loopback Bridge、queue / archive / history / image / document、Container Backend、Windows EXE、Edge / Chrome CDP、安装 / 卸载 / 自定义协议、33-platform diagnostic、live smoke、CodeQL 与 dependency audit。

## 生产真实媒体 Smoke

`scripts/local-parser-production-smoke.py` 不只检查“解析成功”，还会继续读取实际媒体字节。HLS 会沿 playlist 继续进入子 playlist / segment，直到读取非文本媒体内容。

固定回归样本包括 Vimeo、Dailymotion、Apple Podcasts。出现“metadata 成功但媒体 CDN 失败”时应判定为失败。

## 主要 API

- `GET /api/parse?url=...`
- `GET /api/download?...`
- `GET /api/play?...`
- `GET /api/image-proxy?...`
- `GET /api/local-engine/download?version=0.14.0`

网页端 Local Engine 版本唯一来源位于 `src/lib/local-engine.ts`：

```ts
export const LOCAL_ENGINE_REQUIRED_VERSION = '0.14.0'
export const LOCAL_ENGINE_RELEASE_TAG = `local-engine-v${LOCAL_ENGINE_REQUIRED_VERSION}`
```

发布新版本时，README、`local-engine/VERSION`、网页要求版本、Release tag 与下载路由必须保持一致。
