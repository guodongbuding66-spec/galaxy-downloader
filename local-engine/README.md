# Galaxy Local Engine

Galaxy Local Engine 是 Galaxy Downloader 的 Windows 本地下载引擎。它在用户电脑上运行 `yt-dlp + FFmpeg`，用于处理浏览器直连不稳定、需要登录 Cookie、存在反爬或 IP 绑定限制的平台。

> 普通用户请优先阅读安装包中的 **`使用说明.txt`**。

## 最快使用方法

1. 在 Galaxy Downloader 网站点击 **“下载 / 更新 Galaxy Local Engine”**。
2. 下载 `GalaxyLocalEngine-Windows.zip`。
3. **完整解压 ZIP**，不要直接在压缩包中运行。
4. 双击 `install.cmd`。
5. 等待安装器完成 FFmpeg、yt-dlp 和协议注册，并自动启动 Galaxy Local Engine。
6. 返回 Galaxy Downloader 网站，等待状态显示 **“本地引擎已连接”**。
7. 选择需要的 Edge / Chrome / Firefox 登录状态，然后点击 **“按当前方案本机下载”**。

默认下载目录：

```text
%USERPROFILE%\Downloads\Galaxy Downloader
```

默认安装目录：

```text
%LOCALAPPDATA%\GalaxyDownloader\LocalEngine
```

## 网站 ↔ 本地引擎通信

v0.3.x 起，Galaxy Local Engine 不再只依赖一次性的 `galaxy-downloader://` 自定义协议，而是同时提供仅绑定到本机的 Local Bridge：

```text
Galaxy Downloader 网站
        ↓
http://127.0.0.1:17836
        ↓
Galaxy Local Engine
        ↓
yt-dlp + FFmpeg
```

网站可以检测本地引擎是否在线，并同步：

- 引擎版本
- 当前状态
- 下载进度
- 下载速度
- ETA
- 已下载大小
- 取消任务
- 打开下载文件夹

Local Bridge 只绑定 `127.0.0.1`，不会暴露到局域网或公网。

健康检查：

```text
http://127.0.0.1:17836/health
```

## 安装器做什么

`install.cmd` 会调用 `install.ps1`，并完成：

1. 安装 / 覆盖升级 `GalaxyLocalEngine.exe`；
2. 如果旧版 Galaxy Local Engine 正在运行，先自动关闭旧进程；
3. 下载 FFmpeg essentials build；
4. 使用发布方提供的 SHA-256 校验 FFmpeg ZIP；
5. 下载官方 `yt-dlp.exe`；
6. 使用 yt-dlp 发布的 `SHA2-256SUMS` 校验二进制文件；
7. 注册当前 Windows 用户的 `galaxy-downloader://` 协议；
8. 启动 Galaxy Local Engine。

不需要修改整台电脑的 PowerShell 执行策略，也通常不需要管理员权限。

## 浏览器 Cookie

网站可请求本地引擎使用：

- Edge
- Chrome
- Firefox
- 不读取 Cookie

Cookie 由本机 yt-dlp 直接从本机浏览器配置读取，不会发送到 Galaxy 网站或 Galaxy 服务器。

这对 YouTube、Bilibili、小红书等需要与正常浏览器登录/IP 环境一致的平台尤其重要。

## yt-dlp 更新策略

Galaxy Local Engine 使用两层 yt-dlp：

1. **官方外部 `yt-dlp.exe`**：默认优先使用，安装时校验来源；
2. **内置 Python yt-dlp**：作为外部程序失败时的备用方案。

外部 yt-dlp 会定期检查官方 nightly 更新，以更快获得平台解析器修复。如果外部 yt-dlp 更新或执行失败，Galaxy 会自动尝试内置解析器。

## 自定义协议兼容

仍保留自定义协议作为启动 / 兼容入口，例如：

```text
galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fvideo&video=1080&audio=best&include_audio=1&subtitle=1&subtitle_lang=zh-Hans&cover=1&browser=edge
```

如果已经有一个 Galaxy Local Engine 实例在运行，新实例收到协议任务后会把任务转发给正在运行的 Local Bridge，然后退出，避免重复打开多个下载窗口。

仅接受 `http://` 和 `https://` 来源 URL。

## 升级

升级不需要先卸载：

1. 下载最新 `GalaxyLocalEngine-Windows.zip`；
2. 完整解压；
3. 双击最新版 `install.cmd`；
4. 安装器会自动停止旧进程并覆盖升级；
5. 返回网站确认新版本已经连接。

## 卸载

运行：

```text
uninstall.cmd
```

卸载器会移除本地引擎和 `galaxy-downloader://` 协议注册。

## Release 包内容

正式 Release 的 `GalaxyLocalEngine-Windows.zip` 应包含：

- `GalaxyLocalEngine.exe`
- `install.cmd`
- `install.ps1`
- `uninstall.cmd`
- `uninstall.ps1`
- `VERSION`
- `README.md`
- `使用说明.txt`

Release 同时提供 `SHA256SUMS.txt` 用于校验 ZIP。

## 版本与自动发布

`local-engine/VERSION` 是桌面引擎版本的唯一来源。修改该文件并推送到 `main` 会触发 Windows Release 工作流，发布：

```text
local-engine-vX.Y.Z
```

网站下载按钮使用：

```text
https://github.com/guodongbuding66-spec/galaxy-downloader/releases/latest/download/GalaxyLocalEngine-Windows.zip
```

因此始终指向 GitHub 当前 Latest Release，而不是固定旧版本。

## 构建

Windows CI 使用 Python 3.12、PyInstaller 和 yt-dlp 构建单文件 EXE，并运行 `--self-test`。

本地构建示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r local-engine\requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name GalaxyLocalEngine --collect-all yt_dlp --add-data "local-engine/VERSION;." local-engine\engine.py
```

## 安全边界

- Local Bridge 仅监听 `127.0.0.1`；
- 网站来源需要通过本地 Bridge 的 Origin 白名单；
- 自定义协议仅接受 `http(s)` URL；
- 浏览器 Cookie 留在本机；
- 视频和 FFmpeg 处理留在本机；
- FFmpeg 与官方 yt-dlp 下载都会进行 SHA-256 校验；
- 不要求付费解析后端或订阅服务。
