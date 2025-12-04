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
            js = json.loads(text)
        except:
            raise ExtractorError("VK: invalid JSON payload")

        # FIRST priority → DASH MPD URL
        mpd = self._extract_mpd(js)

        if mpd:
            # This goes to MediaFlow's DASH→HLS converter
            return {
                "destination_url": mpd,
                "request_headers": headers,
                "mediaflow_endpoint": "mpd_manifest_proxy",
            }

        # SECOND priority → MP4 fallback (works like Kodi ResolveURL)
        mp4 = self._extract_mp4(js)
        if mp4:
            return {
                "destination_url": mp4,
                "request_headers": headers,
                "mediaflow_endpoint": "proxy_stream_endpoint",
            }

        raise ExtractorError("VK: no MPD or MP4 found")

    # ----------------------------------------------------------------------
    # URL normalizer
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # DASH MPD extractor (MAIN REQUIRED FUNCTION)
    # ----------------------------------------------------------------------

    def _extract_mpd(self, js: Any) -> str | None:
        payload = []
        for item in js.get("payload", []):
            if isinstance(item, list):
                payload = item

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player", {})

            # 1) DIRECT MPD manifest (most common)
            mpd = player.get("dash_manifest")
            if mpd:
                return mpd

            # 2) Cached MPD inside nested structure
            cache = player.get("cache", {})
            mpd2 = cache.get("data", {}).get("dash")
            if mpd2:
                return mpd2

        return None

    # ----------------------------------------------------------------------
    # MP4 fallback (Kodi-style)
    # ----------------------------------------------------------------------

    def _extract_mp4(self, js: Any) -> str | None:
        payload = []
        for i in js.get("payload", []):
            if isinstance(i, list):
                payload = i

        params = None
        cache = None

        for item in payload:
            if isinstance(item, dict) and item.get("player"):
                player = item["player"]

                cache = (
                    player.get("cache", {})
                    .get("data", {})
                    .get("progressive")
                )

                p = player.get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        # Prefer cached MP4
        if cache:
            return (
                cache.get("url1080")
                or cache.get("url720")
                or cache.get("url480")
                or cache.get("url360")
            )

        if params:
            return (
                params.get("url1080")
                or params.get("url720")
                or params.get("url480")
                or params.get("url360")
            )

        return None
