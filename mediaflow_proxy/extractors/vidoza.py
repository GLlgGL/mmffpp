import re
from typing import Dict, Any
from urllib.parse import urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class VidozaExtractor(BaseExtractor):

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        parsed = urlparse(url)

        # Must be canonical embed/watch domain
        if not parsed.hostname or not parsed.hostname.endswith("vidoza.net"):
            raise ExtractorError("VIDOZA: Invalid domain")

        # Browser-like headers
        headers = self.base_headers.copy()
        headers.update({
            "referer": "https://vidoza.net/",
            "origin": "https://vidoza.net",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
        })

        # STEP 1 — Fetch the embed or watch page
        response = await this._make_request(
            url,
            headers=headers
        )
        html = response.text

        if not html:
            raise ExtractorError("VIDOZA: Empty HTML")

        # Capture cookies (some streams require this)
        cookies = response.cookies or {}

        # STEP 2 — Extract URL + label using ResolveURL pattern
        pattern = re.compile(
            r'''["'\s](?:file|src)["'\s:]*["'](?P<url>[^"']+)'''
            r'''(?:[^}\]]+)["']\s*res["'\s:]*["']?(?P<label>[^"']+)''',
            re.IGNORECASE
        )

        match = pattern.search(html)
        if not match:
            raise ExtractorError("VIDOZA: Unable to extract video + label from JS")

        mp4_url = match.group("url")
        label = match.group("label").strip()

        # Normalize URLs starting with //
        if mp4_url.startswith("//"):
            mp4_url = "https:" + mp4_url

        # STEP 3 — Attach cookies to headers
        if cookies:
            headers["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

        return {
            "destination_url": mp4_url,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
            "meta": {
                "label": label  # <—— WE RETURN THE LABEL HERE
            }
        }