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

        # Accept all domains ResolveURL supports
        if not parsed.hostname or not any(
            parsed.hostname.endswith(d)
            for d in ["vidoza.net", "vidoza.co", "videzz.net"]
        ):
            raise ExtractorError("VIDOZA: Invalid domain")

        # Browser-like headers
        browser_headers = {
            "referer": url,
            "origin": "https://videzz.net",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "accept-language": "en-US,en;q=0.9",
            "accept": "*/*",
        }

        # 1) Fetch embed page
        embed_res = await self._make_request(
            url,
            headers=browser_headers
        )
        embed_html = embed_res.text

        # Grab cookies (required for seek in many cases)
        cookies = embed_res.cookies or {}

        # 2) ResolveURL-style extraction of the JS player source
        regex = (
            r'''["'\s](?:file|src)["'\s:]*["'](?P<url>[^"']+)'''
            r'''(?:[^}\]]+)["']\s*res'''
        )
        match = re.search(regex, embed_html)

        if not match:
            raise ExtractorError("VIDOZA: Unable to extract stream URL (JS source not found)")

        # Signed, tokenized stream URL
        stream_url = match.group("url")

        # Normalize protocol-relative URLs
        if stream_url.startswith("//"):
            stream_url = "https:" + stream_url

        # 3) Prepare correct headers for MediaFlow proxy
        stream_headers = {
            **browser_headers,
            "referer": url,      # Required for Vidoza anti-leech
            "origin": "https://videzz.net",
        }

        # Forward cookies
        if cookies:
            stream_headers["cookie"] = "; ".join(
                f"{k}={v}" for k, v in cookies.items()
            )

        # 4) Return details for MediaFlow proxy
        return {
            "mediaflow_endpoint": self.mediaflow_endpoint,
            "destination_url": stream_url,
            "request_headers": stream_headers,
        }