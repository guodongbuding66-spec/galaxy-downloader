# Galaxy Local Engine 0.6.0

## New

- Adds a hybrid document-first parser for public webpages, product pages, image/text posts and public articles before falling back to the existing yt-dlp media parser.
- Supports extracting page title, description/caption, author, publication metadata, gallery images and direct embedded product/article video URLs from HTML, Open Graph, JSON-LD and common hydration JSON payloads.
- Adds browser-cookie fallback for document pages that reject anonymous access, reusing the Local Engine's explicit browser-login workflow.
- Adds first-class document parsing support for Amazon, eBay, AliExpress, Alibaba.com, Shopify storefronts, WeChat Official Account articles and generic public webpages when their media is exposed in the page response.
- Keeps Xiaohongshu's dedicated resolver authoritative and keeps normal Douyin video URLs on the existing video parser; Douyin `/note/` pages can use the document parser.

## Packaging

- The Windows executable now builds from `entrypoint.py`, which installs the hybrid document parser policy before launching the existing engine UI/bridge.
- `web_document.py` is compiled and bundled into the one-file Windows executable.
- yt-dlp and FFmpeg remain bundled as before.

## Notes

Some sites render media only after JavaScript execution or use account/device-specific anti-bot challenges. In those cases the parser will fall back to the existing media parser and browser-cookie path; browser-rendered CDP extraction remains a later compatibility layer rather than adding a large browser runtime to the package.