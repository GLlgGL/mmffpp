import re
from typing import Dict, Any
from urllib.parse import urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class VidozaExtractor(BaseExtractor):

    def __init__(self, request_headers: dict):
        super().__init__(request_headers)
        self.mediaflow_endpoint = "proxy_stream_endpoint"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        parsed = urlparse(url)

        # You want ONLY videzz.net — we keep your rule
        if not parsed.hostname or not parsed.hostname.endswith("videzz.net"):
            raise ExtractorError("VIDOZA: Invalid domain")

        # Browser-like headers (most important: Referer + UA)
        browser_headers = {
            "referer": "https://vidoza.net/",
            "origin": "https://vidoza.net",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
        }

        # STEP 1 — Fetch embed page
        response = await self._make_request(
            url,
            headers=browser_headers
        )
        html = response.text

        if not html:
            raise ExtractorError("VIDOZA: Empty embed page")

        # Save cookies (needed for some Vidoza servers)
        cookies = response.cookies or {}

        # STEP 2 — ResolveURL-style JS player extraction (NO FALLBACK)
        js_pattern = re.compile(
            r'''["'\s](?:file|src)["'\s:]*["'](?P<url>[^"']+)'''
            r'''(?:[^}\]]+)["']\s*res''',
            re.IGNORECASE
        )

        match = js_pattern.search(html)

        if not match:
            raise ExtractorError("VIDOZA: Unable to extract stream URL (JS source not found)")

        stream_url = match.group("url")

        # Normalize URLs starting with //
        if stream_url.startswith("//"):
            stream_url = "https:" + stream_url

        # STEP 3 — Build headers for MediaFlow stream requests
        stream_headers = self.base_headers.copy()
        stream_headers.update(browser_headers)

        # VERY IMPORTANT: Referer must match embed / watch domain
        stream_headers["referer"] = "https://vidoza.net/"

        # Add cookies if available
        if cookies:
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            stream_headers["cookie"] = cookie_header

        # STEP 4 — Return to MediaFlow Proxy (it will fetch all ranges)
        return {
            "destination_url": stream_url,
            "request_headers": stream_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }