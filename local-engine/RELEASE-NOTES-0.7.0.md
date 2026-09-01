# Galaxy Local Engine 0.7.0

## Original-image and batch downloads stay local

Galaxy Local Engine 0.7.0 adds a dedicated loopback image-download bridge. When the website detects this version, original-image downloads and image-article batch archives are sent to the Local Engine instead of relaying the image bytes through Galaxy's public Cloudflare/Container services.

### What changed

- Direct original-image HTTP streaming from the source CDN to the user's `downloads` folder.
- WeChat `mmbiz.qpic.cn` derivative URLs try the `/0` original-size form before the parsed derivative URL.
- Source-aware Referer handling for WeChat, Xiaohongshu, Douyin, TikTok, Instagram and X image CDNs.
- WebP/AVIF images can be converted locally with the bundled FFmpeg:
  - JPEG when the source metadata indicates JPEG;
  - PNG otherwise;
  - the original modern format is retained if local FFmpeg conversion is unavailable.
- Multi-image posts/articles can be downloaded and packaged into ZIP locally, including `.txt` and `.md` article metadata.
- Markdown image references are rewritten to the filenames contained in the local ZIP.
- New `galaxy-downloader://open` action allows the website to prompt Windows to start the installed Local Engine without creating a fake download job.

### Local image bridge

The image bridge listens only on loopback:

```text
http://127.0.0.1:17837
```

It uses the same website-Origin allowlist model as the existing media bridge and exposes only:

- `GET /status`
- `POST /download-images`

Image source URLs are checked by the same fail-closed public HTTP(S) policy used by the Local Engine. Redirect targets are revalidated before following them.

### Local safety limits

The direct local path has high but finite safety limits so malformed or hostile responses cannot grow forever:

- maximum 300 images per submitted image job;
- maximum 2 GiB per individual image;
- maximum 20 GiB for one batch job;
- streamed writes use bounded chunks rather than loading the whole image into memory.

These are local machine limits, not Galaxy server relay limits.

### Server architecture

Small image previews may still use Galaxy's bounded public image relay. Original images, large assets and batch ZIP creation prefer the Local Engine, reducing Galaxy server bandwidth and memory exposure. Public proxy rate limits and byte limits remain enabled because those public endpoints can still be called directly.
