import json
import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):

     def __init__(self, request_headers: dict):
        super().__init__(request_headers)
        # if your base doesn’t set this, keep it; otherwise you can remove:
        self.mediaflow_endpoint = "proxy_stream_endpoint"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)
        ajax_url = self._build_ajax_url(embed_url)

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

        # ---- Only MP4 ----
        mp4 = self._extract_mp4(json_data)
        if not mp4:
            raise ExtractorError("VK: no mp4 stream found")

        return {
            "destination_url": mp4,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    # -------------------------------------------------------------------

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

    # -------------------------------------------------------------------

    def _extract_mp4(self, json_data: Any) -> str | None:
        """Extract MP4 (progressive or legacy). Always returns MP4 only."""

        payload = []
        for i in json_data.get("payload", []):
            if isinstance(i, list):
                payload = i

        params = None
        cache = None

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player")
            if not player:
                continue

            # NEW progressive mp4
            cache = (
                player.get("cache", {})
                      .get("data", {})
                      .get("progressive")
            )

            # fallback mp4 params
            p = player.get("params")
            if isinstance(p, list) and p:
                params = p[0]

        # 1) Progressive MP4 (best)
        if cache:
            return (
                cache.get("url1080")
                or cache.get("url720")
                or cache.get("url480")
                or cache.get("url360")
            )

        # 2) Old-style MP4 params
        if params:
            return (
                params.get("url1080")
                or params.get("url720")
                or params.get("url480")
                or params.get("url360")
            )

        return None
