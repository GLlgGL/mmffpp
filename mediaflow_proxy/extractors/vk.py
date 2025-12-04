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

        # -----------------------------------------------------
        # FIND THE CORRECT DASH MPD
        # -----------------------------------------------------
        mpd = self._find_mpd(js)
        if not mpd:
            raise ExtractorError("VK: No DASH MPD found in payload")

        # Validate MPD is not full-file type1/type3 URL
        if not self._is_valid_mpd_url(mpd):
            raise ExtractorError("VK: MPD is invalid (full file returned)")

        return {
            "destination_url": mpd,
            "request_headers": headers,
            "mediaflow_endpoint": "mpd_manifest_proxy",
        }

    # ---------------------------------------------------------
    # NORMALIZATION
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # MAIN MPD FINDER (works for all VK formats)
    # ---------------------------------------------------------

    def _find_mpd(self, js: Any) -> str | None:
        payload = []

        for i in js.get("payload", []):
            if isinstance(i, list):
                payload = i

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player")
            if not player:
                continue

            # 1) MOST COMMON
            if "dash_manifest" in player:
                return player["dash_manifest"]

            # 2) SOMETIMES inside params
            params = player.get("params")
            if isinstance(params, list) and params:
                dash = params[0].get("dash")
                if dash:
                    return dash

            # 3) CACHE (rare)
            cache = player.get("cache", {})
            dash = cache.get("data", {}).get("dash")
            if dash:
                return dash

        return None

    # ---------------------------------------------------------
    # Validate MPD URL (exclude full MP4 download URLs)
    # ---------------------------------------------------------

    def _is_valid_mpd_url(self, url: str) -> bool:
        forbidden = [
            "fromCache=1",
            "ch=",
            "appId=",
            "type=1",  # full-file
            "type=3",  # full-file HD
        ]
        return not any(f in url for f in forbidden)
