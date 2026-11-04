"""Offline image-quality regression fixtures, not a live site success claim."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local-engine'))

import image_download as downloader
import web_document
from home_depot_policy import install_home_depot_document_policy
from image_archive_policy import _metadata
from image_resolution import (
    dedupe_resolution_variants, home_depot_advertised_urls,
    home_depot_candidates, parse_srcset,
)

PRODUCT = 'https://www.homedepot.com/p/Example-Shed/700380885'
THUMB = 'https://images.thdstatic.com/productImages/fixture/svn/shed-64_100.jpg'


def image_bytes(width, height, fmt='JPEG'):
    output = io.BytesIO()
    Image.new('RGB', (width, height), (53, 111, 161)).save(output, format=fmt)
    return output.getvalue()


class Response(io.BytesIO):
    def __init__(self, body, url, mime='image/jpeg'):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Type': mime, 'Content-Length': str(len(body))}

    def geturl(self):
        return self.url


class FixtureOpener:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def open(self, request, timeout):
        url = request.full_url
        self.urls.append(url)
        value = self.responses.get(url, 404)
        if isinstance(value, int):
            raise HTTPError(url, value, 'Fixture refusal', {}, None)
        if callable(value):
            value = value()
        if isinstance(value, tuple):
            return Response(value[0], url, value[1])
        return Response(value, url)


class OriginalImageQualityTests(unittest.TestCase):
    def setUp(self):
        downloader._IMAGE_JOB_CANCEL.clear()

    def tearDown(self):
        downloader._IMAGE_JOB_CANCEL.clear()

    def download(self, directory, opener, source=THUMB):
        with patch.object(downloader, 'validated_public_http_url', side_effect=lambda value: value), patch.object(downloader, '_OPENER', opener):
            return downloader._download_one(source, directory, 'shed', PRODUCT)

    def test_actual_pixels_win_over_misleading_1000_filename(self):
        zoom, unsized, source = home_depot_candidates(THUMB)
        full = image_bytes(1600, 1100)
        opener = FixtureOpener({zoom: image_bytes(100, 100), unsized: full, source: image_bytes(100, 100)})
        with tempfile.TemporaryDirectory() as folder:
            path, size = self.download(Path(folder), opener)
            self.assertEqual(path.read_bytes(), full)
            self.assertEqual(size, len(full))
            self.assertEqual(list(Path(folder).iterdir()), [path])
        info = downloader.image_job_status()['lastImage']
        self.assertEqual((info['width'], info['height']), (1600, 1100))
        self.assertEqual(info['sha256'], hashlib.sha256(full).hexdigest())
        self.assertTrue(info['dimensionsVerified'])
        self.assertFalse(info['originalVerified'])
        self.assertEqual(opener.urls, [zoom, unsized, source])

    def test_missing_candidates_keep_exact_source_bytes(self):
        original = image_bytes(100, 100)
        opener = FixtureOpener({THUMB: original})
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.download(Path(folder), opener)
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(opener.urls[-1], THUMB)
        self.assertEqual(downloader.image_job_status()['lastImage']['width'], 100)

    def test_access_denial_stops_variant_requests(self):
        first = home_depot_candidates(THUMB)[0]
        opener = FixtureOpener({first: 403, THUMB: image_bytes(100, 100)})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(HTTPError):
                self.download(Path(folder), opener)
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertEqual(opener.urls, [first])

    def test_throttle_does_not_switch_cdn_variants(self):
        first = home_depot_candidates(THUMB)[0]
        opener = FixtureOpener({first: 429, THUMB: image_bytes(100, 100)})
        with tempfile.TemporaryDirectory() as folder, patch.object(downloader, 'MAX_DOWNLOAD_ATTEMPTS', 1):
            with self.assertRaises(HTTPError):
                self.download(Path(folder), opener)
        self.assertEqual(opener.urls, [first])

    def test_image_mime_does_not_accept_html_as_a_photo(self):
        url = 'https://cdn.example.test/photo.jpg'
        opener = FixtureOpener({url: b'<html><h1>Access Denied</h1></html>'})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                self.download(Path(folder), opener, url)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_truncated_jpeg_scan_is_not_accepted_from_header_dimensions(self):
        url = 'https://cdn.example.test/photo.jpg'
        complete = image_bytes(1200, 900)
        opener = FixtureOpener({url: complete[:-1000]})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                self.download(Path(folder), opener, url)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_bytes_determine_format_despite_wrong_mime_and_suffix(self):
        url = 'https://cdn.example.test/photo.jpg'
        png = image_bytes(720, 480, 'PNG')
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.download(Path(folder), FixtureOpener({url: (png, 'image/jpeg')}), url)
            self.assertEqual(path.suffix, '.png')
            self.assertEqual(path.read_bytes(), png)

    def test_cancel_cleans_previously_downloaded_candidates(self):
        zoom, unsized, _ = home_depot_candidates(THUMB)
        def cancelled_response():
            downloader._IMAGE_JOB_CANCEL.set()
            return image_bytes(100, 100)
        opener = FixtureOpener({zoom: image_bytes(1000, 700), unsized: cancelled_response})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(downloader.ImageJobCancelled):
                self.download(Path(folder), opener)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_bounded_candidates_preserve_signatures(self):
        signed = THUMB + '?signature=a%2Fb&crop=1,2'
        candidates = home_depot_candidates(signed)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[-1], signed)
        self.assertTrue(all(url.endswith('?signature=a%2Fb&crop=1,2') for url in candidates))
        self.assertFalse(any('_4000' in url or '_3000' in url for url in candidates))
        spoofed = THUMB.replace('images.thdstatic.com', 'images.thdstatic.com.evil.test')
        self.assertEqual(home_depot_candidates(spoofed), [spoofed])

    def test_explicit_high_resolution_metadata_is_retained(self):
        explicit = THUMB.replace('_100.jpg', '_2400.jpg')
        self.assertEqual(home_depot_candidates(explicit)[0], explicit)

    def test_deduplication_preserves_different_signed_crops(self):
        large = THUMB.replace('_100.jpg', '_1000.jpg')
        self.assertEqual(dedupe_resolution_variants([THUMB, large, large]), [large])
        self.assertEqual(len(dedupe_resolution_variants([THUMB + '?crop=1,2', large + '?crop=2,3'])), 2)

    def test_srcset_keeps_commas_and_ranks_width_and_density(self):
        value = 'https://cdn.test/a.jpg?crop=1,2 400w, https://cdn.test/b.jpg?sig=a,b 1600w, /small.jpg 100w'
        self.assertEqual(parse_srcset(value), ['https://cdn.test/b.jpg?sig=a,b', 'https://cdn.test/a.jpg?crop=1,2', '/small.jpg'])
        self.assertEqual(parse_srcset('/a.jpg 1x, /b.jpg 2x'), ['/b.jpg', '/a.jpg'])
        self.assertEqual(parse_srcset('/a.jpg -1w, /b.jpg 0w, /c.jpg nonsense'), [])

    def test_lazy_srcset_meta_and_json_merge_to_largest_asset(self):
        large = THUMB.replace('_100.jpg', '_1800.jpg')
        state = {'product': {'media': {'images': [{'url': large}]}}}
        html = f'''<meta property="og:title" content="Fixture shed">
            <meta name="description" content="Detailed shed product description for fixture validation.">
            <meta property="og:image" content="{THUMB}">
            <picture><source data-srcset="{THUMB} 100w, {THUMB.replace('_100.jpg', '_1000.jpg')} 1000w"></picture>
            <img src="{THUMB}" data-zoom-image="{large}">
            <script>window.__APOLLO_STATE__ = {json.dumps(state)};</script>'''
        result = web_document._document_payload(PRODUCT, html, PRODUCT, 'none')
        self.assertTrue(result['success'])
        self.assertEqual([item['downloadUrl'] for item in result['data']['images']], [large])

    def test_json_url_with_comma_is_not_truncated(self):
        url = 'https://cdn.test/image.jpg?crop=1,2&token=signed'
        self.assertEqual(web_document._absolute_url(url, PRODUCT), url)
        self.assertEqual(web_document._absolute_url(url.replace('&', '&amp;'), PRODUCT), url)

    def test_advertised_template_expands_only_explicit_sizes(self):
        template = THUMB.replace('_100.jpg', '_<SIZE>.jpg')
        urls = home_depot_advertised_urls(template, ['100', '600', '1800', 'NaN', '999999999'])
        self.assertEqual(urls, [THUMB.replace('_100.jpg', f'_{size}.jpg') for size in (1800, 600, 100)])
        html = '<meta property="og:title" content="Fixture"><script type="application/ld+json">' + json.dumps({'image': {'url': template, 'sizes': ['100', '1800']}}) + '</script>'
        parsed = web_document._document_payload(PRODUCT, html, PRODUCT, 'none')
        self.assertEqual(parsed['data']['images'][0]['downloadUrl'], urls[0])
        self.assertFalse(any('<SIZE>' in item['url'] for item in parsed['data']['images']))

    def test_late_metadata_upgrades_existing_asset_at_image_limit(self):
        parser = web_document._DocumentParser(PRODUCT)
        parser._add_image(THUMB, 'src')
        for index in range(web_document.MAX_IMAGES - 1):
            parser._add_image(f'https://cdn.test/{index}.jpg', 'src')
        large = THUMB.replace('_100.jpg', '_1800.jpg')
        parser._add_image(large, 'image')
        self.assertEqual(len(parser.images), web_document.MAX_IMAGES)
        self.assertEqual(parser.images[0], large)

    def test_access_denied_is_terminal_not_a_gallery(self):
        install_home_depot_document_policy()
        denied = '<title>Access Denied</title><h1>Access Denied</h1><p>Reference #18.1234</p>'
        with patch.object(web_document, '_fetch_html', return_value=(denied, PRODUCT)) as fetch:
            result = web_document.parse_web_document(PRODUCT)
        self.assertFalse(result['success'])
        self.assertEqual(result['code'], 'AUTH_REQUIRED')
        self.assertFalse(result['details']['retryAutomatically'])
        fetch.assert_called_once_with(PRODUCT, 'none')

    def test_sdk_captcha_reference_is_not_itself_a_displayed_challenge(self):
        install_home_depot_document_policy()
        html = f'<meta property="og:title" content="Fixture shed"><img src="{THUMB}"><script>const captcha = {{}};</script>'
        result = web_document._document_payload(PRODUCT, html, PRODUCT, 'none')
        self.assertTrue(result['success'])

    def test_archive_maps_deduped_sources_to_measured_files(self):
        large = THUMB.replace('_100.jpg', '_1000.jpg')
        measured = {'requestedUrl': large, 'localFile': 'actual.jpg', 'width': 1500, 'height': 1000, 'bytes': 1234, 'dimensionsVerified': True, 'originalVerified': False}
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / 'images.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('actual.jpg', b'fixture')
            result = _metadata({'images': [THUMB, large]}, archive_path, [measured])
        self.assertEqual(len(result['images']), 1)
        self.assertEqual(result['images'][0]['localFile'], 'actual.jpg')
        self.assertEqual(result['images'][0]['width'], 1500)
        self.assertFalse(result['images'][0]['originalVerified'])

    def test_wechat_original_zero_candidate_stays_first(self):
        source = 'https://mmbiz.qpic.cn/demo/640?wx_fmt=jpeg&tp=webp'
        self.assertIn('/0?', downloader._image_candidates(source)[0])

    def test_best_quality_job_preserves_webp_bytes_without_conversion(self):
        url = 'https://cdn.test/photo.webp'
        content = image_bytes(600, 400, 'WEBP')
        opener = FixtureOpener({url: (content, 'image/webp')})
        with tempfile.TemporaryDirectory() as folder, patch.object(downloader, '_download_dir', return_value=Path(folder)), patch.object(downloader, '_origin_referer', return_value=None), patch.object(downloader, 'validated_public_http_url', side_effect=lambda value: value), patch.object(downloader, '_OPENER', opener), patch.object(downloader, '_convert_modern_image') as convert:
            self.assertTrue(downloader._IMAGE_JOB_LOCK.acquire(blocking=False))
            downloader._run_image_job({'images': [url], 'title': 'Raw quality'})
            state = downloader.image_job_status()
            self.assertEqual(state['status'], 'Completed')
            path = Path(state['lastPath'])
            self.assertEqual(path.suffix, '.webp')
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(state['imageResults'][0]['sha256'], hashlib.sha256(content).hexdigest())
            convert.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
