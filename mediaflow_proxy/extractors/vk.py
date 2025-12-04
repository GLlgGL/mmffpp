import json
import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

class VKExtractor(BaseExtractor):

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)
        ajax_url  = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        data = self._build_ajax_data(embed_url)

        response = await self._make_request(
            ajax_url, method="POST", data=data, headers=headers
        )

        text = response.text.lstrip("<!--")

        try:
            json_data = json.loads(text)
        except:
            raise ExtractorError("VK: invalid JSON payload")

        dash_url = self._extract_mpd(json_data)
        if not dash_url:
            raise ExtractorError("VK: no DASH MPD URL found")

        return {
            "destination_url": dash_url,
            "request_headers": headers,
            "mediaflow_endpoint": "mpd_manifest_proxy",
        }

    # ------------------------------------
    # Helpers
    # ------------------------------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url
        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            return url
        return f"https://vk.com/video_ext.php?oid={m.group(1)}&id={m.group(2)}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str):
        qs = re.search(r"\?(.*)", embed_url)
        parts = dict(x.split("=") for x in qs.group(1).split("&")) if qs else {}
        return {
            "act": "show",
            "al": "1",
            "video": f"{parts.get('oid')}_{parts.get('id')}",
        }

    def _extract_mpd(self, json_data: Any) -> str | None:
        """Extract DASH MPD URL (hls / hls_ondemand replaced by DASH now)."""

        payload = []
        for i in json_data.get("payload", []):
            if isinstance(i, list):
                payload = i

        for item in payload:
            if isinstance(item, dict) and "player" in item:
                params = item["player"].get("params", [{}])[0]

                # MPD URL is usually here
                dash_urls = [
                    params.get("dash"),
                    params.get("dash_live"),
                    params.get("manifest"),
                    params.get("manifest_url"),
                ]

                for d in dash_urls:
                    if d:
                        return d

        return None
