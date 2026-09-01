# Galaxy Local Engine

Galaxy Local Engine 是 Galaxy Downloader 的 Windows 本地下载引擎。它在用户电脑上运行 `yt-dlp + FFmpeg`，用于处理浏览器直连不稳定、需要登录 Cookie、存在反爬或 IP 绑定限制的平台。

> 普通用户请优先阅读安装包中的 **`使用说明.txt`**。

## 最快使用方法

1. 在 Galaxy Downloader 网站点击 **“下载 Galaxy Local Engine（官网线路）”**。
2. 下载 `GalaxyLocalEngine-Windows.zip`。
3. **完整解压 ZIP**，不要直接在压缩包中运行。
4. 把整个解压文件夹放在一个长期不移动的位置。
5. 双击 `install.cmd`。
6. 返回 Galaxy Downloader 网站，等待状态显示 **“本地引擎已连接”**。
7. 选择需要的 Edge / Chrome / Firefox 登录状态，然后点击 **“按当前方案本机下载”**。

## 0.14：统一任务中心与智能恢复

Local Engine 0.14 把当前下载、等待队列和本机历史整合到同一个 **任务中心**：

- 当前任务：查看进度、来源、画质和任务详情；
- 等待队列：支持暂停/继续、上移、下移、批量移到顶部和批量移除；
- 历史任务：搜索、状态筛选、打开文件、定位文件、复制脱敏来源；
- 失败任务：显示失败原因分类、恢复建议、原参数重试和智能重试。

失败分类包括网络异常、429 限流、浏览器 Cookie、登录验证、磁盘不足、区域限制、内容不可用、FFmpeg 后处理、解析器失效、403 访问拒绝和未知错误。

### 智能重试的边界

智能重试不是“所有失败都再试一次”。只有适合自动调整传输参数的失败才会启用：

- 网络超时/连接重置：弱网增强 + 2 个并发分片；
- 429 / 明确限流：弱网增强 + 1 个并发分片 + 5 Mbps；
- 未知瞬态失败：弱网增强 + 2 个并发分片。

需要登录、浏览器 Cookie 被占用、磁盘不足、区域限制、源内容下架或解析器失效等问题不会盲目智能重试，而是先提示需要处理的原因。

每次智能重试的网络覆盖参数只绑定到该任务，不会修改工作台全局设置，也不会影响已经排队的其他任务。

## 便携式原地安装

新版 Galaxy Local Engine 不再把程序复制到 `%LOCALAPPDATA%`。

**当前解压文件夹本身就是安装目录。**

例如：

```text
D:\GalaxyLocalEngine-Windows\GalaxyLocalEngine.exe
D:\GalaxyLocalEngine-Windows\yt-dlp.exe
D:\GalaxyLocalEngine-Windows\ffmpeg\bin\ffmpeg.exe
D:\GalaxyLocalEngine-Windows\downloads\
```

默认下载目录：

```text
<解压文件夹>\downloads
```

如果以后移动了整个文件夹，只需要在新位置重新运行一次 `install.cmd`，Windows 的 `galaxy-downloader://` 协议路径会自动刷新。

## 离线安装：FFmpeg 和 yt-dlp 已内置

正式 Release 的 ZIP 直接包含：

- `GalaxyLocalEngine.exe`
- `yt-dlp.exe`
- `ffmpeg/bin/ffmpeg.exe`
- `ffmpeg/bin/ffprobe.exe`
- `install.cmd`
- `install.ps1`
- `uninstall.cmd`
- `uninstall.ps1`
- `VERSION`
- `README.md`
- `使用说明.txt`

用户双击 `install.cmd` 时，**不再需要下载 FFmpeg，也不再需要从 GitHub 下载 yt-dlp**。

FFmpeg 和官方 `yt-dlp.exe` 会在 GitHub Actions 发布流程中提前下载，并使用发布方提供的 SHA-256 数据完成校验。校验通过后才会被放入最终安装 ZIP。

因此，即使用户电脑无法直接访问 GitHub，只要能够从 Galaxy Downloader 网站拿到完整 ZIP，就可以完成首次安装。

## 网站 ↔ 本地引擎通信

Galaxy Local Engine 同时提供仅绑定本机的 Local Bridge：

```text
Galaxy Downloader 网站
        ↓
http://127.0.0.1:17836
        ↓
Galaxy Local Engine
        ↓
yt-dlp + FFmpeg
```

网站可以检测本地引擎是否在线，并同步引擎版本、当前状态、下载进度、下载速度、ETA、已下载大小、等待队列、取消任务和打开下载文件夹。

Local Bridge 只绑定 `127.0.0.1`，不会暴露到局域网或公网。

健康检查：

```text
http://127.0.0.1:17836/health
```

## install.cmd 做什么

`install.cmd` 会调用 `install.ps1`，并完成：

1. 以当前解压文件夹作为程序目录；
2. 如果旧版 Galaxy Local Engine 正在运行，先自动关闭旧进程；
3. 检查内置 `yt-dlp.exe`；
4. 检查内置 `ffmpeg.exe` / `ffprobe.exe`；
5. 创建当前目录下的 `downloads` 文件夹；
6. 注册当前 Windows 用户的 `galaxy-downloader://` 协议；
7. 启动 Galaxy Local Engine。

不需要修改整台电脑的 PowerShell 执行策略，也通常不需要管理员权限。

## 浏览器 Cookie

网站可请求本地引擎使用 Edge、Chrome、Firefox 或不读取 Cookie。Cookie 由本机 yt-dlp 直接从本机浏览器配置读取，不会发送到 Galaxy 网站或 Galaxy 服务器。

对于普通媒体下载，本地引擎会先尝试无需 Cookie 的公开路径；只有公开方式失败时才读取用户选择的浏览器登录状态。浏览器 Cookie 数据库被占用时会给出明确错误分类，而不是自动重复失败。

## 网络设置与弱网恢复

工作台设置提供三种网络策略：

- 标准：10 次下载重试 / 10 次分片重试 / 5 次 extractor 重试；
- 弱网增强：20 / 20 / 8；
- 快速失败：5 / 5 / 3。

并发分片可选 `1 / 2 / 4 / 8 / 16`，速度上限可选不限速或 `1–100 Mbps`。默认仍为 **标准 + 4 分片 + 不限速**。

智能重试使用的是“单任务覆盖”，不会把这些工作台设置永久改掉。

## 诊断日志与隐私

诊断日志默认关闭。主动开启后写入：

```text
state\engine.log
```

日志会移除 URL 凭据、query、fragment，并再次清理常见 token、authorization、cookie、session、password 和 secret 字段。

0.14 进一步把同样的脱敏规则应用到下载历史中的失败详情，避免第三方 extractor 错误文本把敏感 URL 参数带入 `download-history.json`。

## yt-dlp 更新策略

Galaxy Local Engine 使用两层 yt-dlp：

1. **安装包内置的官方 `yt-dlp.exe`**：默认优先使用；
2. **内置 Python yt-dlp**：作为外部程序失败时的备用方案。

正常下载默认**不会**在线更新 `yt-dlp.exe`，因此用户电脑无法访问 GitHub 时不会在下载前等待更新超时。新的官方 yt-dlp 会随新版 Galaxy Local Engine Release 一起重新打包和校验。

高级用户只有显式设置 `GALAXY_YTDLP_AUTO_UPDATE=1` 时，外部 yt-dlp 才会按内部更新间隔尝试 nightly 更新；更新失败不会阻止继续使用已经打包的版本。

## 自定义协议兼容

仍保留自定义协议作为启动 / 兼容入口，例如：

```text
galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fvideo&video=1080&audio=best&include_audio=1&subtitle=1&subtitle_lang=zh-Hans&cover=1&browser=edge
```

如果已经有一个 Galaxy Local Engine 实例在运行，新实例收到协议任务后会把任务转发给正在运行的 Local Bridge，然后退出，避免重复打开多个下载窗口。

仅接受 `http://` 和 `https://` 公网来源 URL；localhost、私网、保留地址和带凭据的 URL 会被拒绝。

## 下载历史

下载历史只保存在本机 `state/download-history.json`。可在设置中关闭，或限制为 20 / 50 / 80 / 150 / 300 条。

历史中的来源链接会去掉未知 query、fragment 和 URL 凭据。YouTube 的 `v` / `list` / `index` 作为稳定媒体标识例外保留，以便安全重试。

主动重试会关闭该任务的 Download Archive 跳过行为，避免用户明确点击重试后仍因 archive 命中而被跳过。

## 升级

升级不需要先卸载：下载最新 ZIP，完整解压，把新版文件夹放到准备长期使用的位置，双击最新版 `install.cmd`，然后返回网站确认新版本已经连接。

如果希望继续使用原来的目录，也可以先关闭旧版，然后把新版 ZIP 内容完整覆盖到原目录，再运行 `install.cmd`。

## 官网下载线路与 GitHub 备用线路

网站主按钮使用 Galaxy Downloader 自己的下载接口，并精确绑定网站当前要求的 `local-engine-vX.Y.Z`。用户浏览器不需要直接访问 GitHub。

GitHub Release 页面仍作为备用镜像，方便开发者和能正常访问 GitHub 的用户直接获取原始 Release。

## 卸载

运行 `uninstall.cmd` 会关闭 Galaxy Local Engine 并移除 `galaxy-downloader://` 协议注册。当前便携文件夹和 `downloads` 中已下载的视频会保留；如果不再需要，直接删除整个解压文件夹即可。

## Release 包内容

正式 Release 的 `GalaxyLocalEngine-Windows.zip` 必须包含：

- `GalaxyLocalEngine.exe`
- `yt-dlp.exe`
- `ffmpeg/bin/ffmpeg.exe`
- `ffmpeg/bin/ffprobe.exe`
- `install.cmd`
- `install.ps1`
- `uninstall.cmd`
- `uninstall.ps1`
- `VERSION`
- `README.md`
- `使用说明.txt`

Release 同时提供 `SHA256SUMS.txt` 用于校验最终 ZIP。

## 版本与自动发布

`local-engine/VERSION` 是桌面引擎版本的唯一来源。修改该文件并推送到 `main` 会触发 Windows Release 工作流，发布 `local-engine-vX.Y.Z`。

## 构建

Windows CI 使用 Python 3.12、PyInstaller 和 yt-dlp 构建单文件 EXE，并运行 `--self-test`。随后 `prepare-bundle.ps1` 会下载并校验 FFmpeg 和官方 yt-dlp，再把它们加入最终 ZIP。

本地构建示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r local-engine\requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name GalaxyLocalEngine --collect-all yt_dlp --add-data "local-engine/VERSION;." local-engine\entrypoint.py
```

准备完整离线包：

```powershell
./local-engine/prepare-bundle.ps1 -PackageDir dist/package
```

## 安全边界

- Local Bridge 仅监听 `127.0.0.1`；
- 网站来源需要通过本地 Bridge 的 Origin 白名单；
- 自定义协议仅接受公网 `http(s)` URL；
- 浏览器 Cookie 留在本机；
- 视频和 FFmpeg 处理留在本机；
- 下载历史与诊断日志进行 URL / token 脱敏；
- FFmpeg 与官方 yt-dlp 在 Release 打包阶段进行 SHA-256 校验；
- 用户首次安装不依赖 GitHub；
- 正常下载默认不联网更新 yt-dlp；
- 不要求付费解析后端或订阅服务。
