# Galaxy Local Engine 0.15.0

Windows 便携式本地 yt-dlp + FFmpeg 下载引擎。

## 安装方式

1. 下载 `GalaxyLocalEngine-Windows.zip`。
2. 可用 `SHA256SUMS.txt` 校验 ZIP 完整性。
3. 完整解压 ZIP，不要直接在压缩包内运行。
4. 双击 `install.cmd`。
5. 程序直接安装在当前解压文件夹，不复制到 AppData。
6. FFmpeg 与 `yt-dlp.exe` 已内置，首次安装无需访问 GitHub，也无需另外下载依赖。
7. 下载的视频、音频、图片与文档默认保存在解压目录下的 `downloads` 文件夹。
8. 返回 SparkDownloader，等待显示 **“本地引擎已连接”** 后即可使用。

## 0.15.0

- 新增活动媒体下载“暂停当前”：通过正常下载取消边界停止 worker，保留 yt-dlp `.part` / 分片文件，而不是挂起 Windows 进程。
- 普通 yt-dlp 任务使用明确的 `--continue` / `continuedl=True`，继续时从源站允许的最近检查点恢复。
- 新增重启恢复：程序退出、异常中断或电脑重启后，未完成的 `running / pausing` 任务会变为 `interrupted`，只进入可恢复任务列表，不会自动开始下载。
- 新增本机持久化恢复状态 `state/resume-jobs.json`；完整源 URL / Job payload 只保存在本机，Bridge 只向网页暴露脱敏后的任务摘要。
- Local Bridge 升级到 protocol v5，新增 `POST /pause`、`POST /resume` 与 `POST /resume/discard`；控制操作统一回到 Tk 主线程执行。
- 桌面任务中心新增“暂停 / 中断”筛选、暂停当前、继续 / 重新开始、放弃恢复；网页本机下载卡同步增加 Pause Current 和 Recoverable Jobs。
- 对不具备可靠字节级续传能力的来源明确标记 `restart`；当前微信视频号路径会显示“重新开始”，不会伪装成从原百分比精确续传。
- 修复暂停时临时 queue hold 的边界：继续、放弃恢复、暂停过程中取消都会恢复暂停前的队列状态；用户本来就暂停的队列仍保持暂停。
- 显式 Cancel 仍是终止操作，会清除该任务的恢复入口；关闭 Local Engine 时会先保存恢复状态并等待活动媒体 worker 安全退出。
- 新增永久 Pause/Resume 生命周期门禁，并把关键断言嵌入 Local Engine `--self-test`；正式 PyInstaller EXE、真实桌面 UI 构建、安装/协议生命周期继续作为发布阻断条件。
- 网站、Local Engine、官方下载路由和 GitHub 备用下载地址精确绑定 `local-engine-v0.15.0`。

## 0.14.1

- 修复 Windows 桌面端启动时 `expected integer but got "UI"` 的 Tk 字体解析崩溃。
- 新增源码与 PyInstaller `--windowed` 成品 EXE 的真实 UI 构建 Smoke；异常弹窗、启动死锁或 UI 构建异常会阻止发布。
- 正式 Release workflow 在上传 ZIP 前再次执行成品 EXE UI Smoke，不再只依赖 `--self-test`。
- 网站、下载路由和 GitHub 备份地址精确绑定 `local-engine-v0.14.1`。

## 0.14.0

- 新增统一任务中心：当前下载、等待队列、成功历史、失败历史与取消任务进入同一桌面工作区。
- 任务中心支持搜索、状态筛选、队列暂停、上移/下移、批量移到顶部和批量移除。
- 失败历史细分源站限流、Cookie、登录验证、磁盘、区域限制、内容不可用、FFmpeg、解析器、网络、403 与未知错误。
- 新增智能重试：网络、429 与未知瞬态失败可生成一次更保守的单任务恢复配置，不修改全局网络设置。
- 下载历史继续执行 URL/token/cookie/session/password/secret 等隐私脱敏。

## 早期版本摘要

- **0.13.0**：网络重试、分片/限速、磁盘健康、完成提醒与隐私安全诊断日志。
- **0.12.0**：历史搜索/重试、完整队列管理器、文件命名与来源目录设置。
- **0.11.0**：持久化下载历史、任务详情、等待任务上移/下移、完成后暂停/继续队列。
- **0.10.0**：深色桌面工作台、高级媒体预设、片段/章节、字幕/音轨、SponsorBlock、aria2c 与稳定版更新检查。
- **0.9.0**：稳定媒体优先解析、腾讯元宝浏览器登录复用、本地 yt-dlp + FFmpeg 主下载路径。
- **0.8.0**：有界 FIFO 媒体下载队列、可选 Download Archive、稳定 Bridge 错误码与精确版本下载资产。
- **0.7.0**：本地原图下载、超大图片本机直连、WebP/AVIF 转换与多图 ZIP。
- **0.6.0**：网页文档解析与 Edge/Chrome CDP 动态渲染兜底。

安装包内包含 `使用说明.txt` 和 `README.md`。如果以后移动整个解压文件夹，只需在新位置重新运行一次 `install.cmd` 以刷新 Windows 协议路径。

发布流程会在打包阶段校验 FFmpeg 与官方 `yt-dlp.exe` 的 SHA-256，并把已验证的可执行文件直接放入 ZIP。用户端安装过程不依赖 GitHub。
