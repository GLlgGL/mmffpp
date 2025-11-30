import re
from typing import Dict, Any
from urllib.parse import urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class VidozaExtractor(BaseExtractor):

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        parsed = urlparse(url)

        # Extract video ID whether it's embed or normal link
        m = re.search(r'(?:embed-)?([A-Za-z0-9]+)\.html?', parsed.path)
        if not m:
            raise ExtractorError("VIDOZA: Invalid Vidoza URL")
        video_id = m.group(1)

        # *** TARGET WATCH PAGE ON videzz.net ***
        watch_url = f"https://videzz.net/{video_id}.html"

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

        # Fetch WATCH PAGE (not embed)
        response = await self._make_request(
            watch_url,
            headers=headers,
            follow_redirects=True   # required
        )

        html = response.text
        if not html:
            raise ExtractorError("VIDOZA: Empty watch page HTML")

        cookies = response.cookies or {}

        # ResolveURL pattern extraction
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

        # Fix // prefix
        if mp4_url.startswith("//"):
            mp4_url = "https:" + mp4_url

        # Attach cookies for token auth
        if cookies:
            headers["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

        return {
            "destination_url": mp4_url,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
            "meta": {
                "label": label
            }
        }