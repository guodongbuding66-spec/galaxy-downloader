# Galaxy Media Preview Helper · V1.5.1

媒体解析预览中心使用 `media-preview-server.ps1` 提供本机只读元数据服务。

## 默认地址

- Health: `http://127.0.0.1:17837/health`
- Inspect: `http://127.0.0.1:17837/inspect?url=...&browser=none`

正常情况下无需手动启动。请使用 `Launch-Modern-UI.cmd`，启动器会自动检测并拉起 Helper。

## 工作方式

Helper 调用同目录的 `yt-dlp.exe`：

```text
yt-dlp.exe --dump-single-json --skip-download --no-warnings --no-playlist <URL>
```

它只返回标题、缩略图、时长、分辨率、FPS、编码、HDR、格式和大小等元数据，不会因为“解析链接”而开始下载。

## 安全边界

- 仅绑定 `127.0.0.1`
- 浏览器 CORS 只允许 `http://127.0.0.1:17836` / `http://localhost:17836`
- `/inspect` 要求 `X-Galaxy-Preview: 1` 请求头
- 仅接受 HTTP / HTTPS URL
- 不启用 ShellExecute
- Cookie 浏览器参数采用白名单
- 45 秒解析超时
- 不处理 DRM 解密或绕过

## 显示“解析服务未启动”

1. 退出 Galaxy 新版窗口。
2. 重新双击 `Launch-Modern-UI.cmd`。
3. 浏览器打开 `http://127.0.0.1:17837/health`，应看到 JSON 状态。
4. 若仍失败，确认 Windows PowerShell 与 `yt-dlp.exe` 未被安全软件阻止。

直接 JPG / PNG / WebP / AVIF / GIF 图片的像素尺寸由浏览器读取，即使 Helper 暂时离线也可尝试解析。
