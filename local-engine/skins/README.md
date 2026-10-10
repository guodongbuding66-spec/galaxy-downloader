# Galaxy Skin Format v1

Galaxy Local Engine V1.4 支持可逆的 token-based 皮肤。皮肤文件扩展名建议使用 `.galaxyskin`，内容为 UTF-8 JSON。

## GitHub 分享

1. 将 `.galaxyskin` 提交到任意公开 GitHub 仓库。
2. 在 Galaxy → 皮肤 → 导入 / 分享 中粘贴 GitHub `blob` 链接或 `raw.githubusercontent.com` 地址。
3. Galaxy 会自动把标准 `github.com/.../blob/...` 转成 raw 地址并读取 JSON。

## 可配置字段

- `accent`：强调色
- `canvas`：应用背景色
- `surface`：面板色
- `text`：正文色
- `brand`：品牌点缀色
- `radius`：圆角 4–24 px
- `density`：`compact` / `standard` / `spacious`
- `surfaceOpacity`：面板透明度 0.62–1
- `blur`：玻璃模糊 0–36 px
- `fontScale`：字体缩放 0.90–1.16
- `sidebarWidth`：侧栏宽度 206–286 px
- `fontFamily`：`system` / `rounded` / `mono`
- `background`：背景类型、内容、透明度、模糊、缩放与位置

## 安全边界

V1 皮肤使用设计令牌，不执行主题包中的 JavaScript，也不导入任意 CSS。这样可以分享颜色、布局和背景，同时避免第三方皮肤直接注入脚本。
