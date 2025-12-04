import json
import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):
    """
    Improved VK extractor with:
    - HLS priority (MUCH more stable for Stremio)
    - MP4 fallback only if HLS missing
    - Correct MediaFlow endpoint selection
    - Handles new VK JSON payload structure
    """

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)

        # Step 1: Build al_video.php endpoint
        ajax_url = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        data = self._build_ajax_data(embed_url)

        # POST request to VK
        response = await self._make_request(
            ajax_url,
            method="POST",
            data=data,
            headers=headers
        )

        text = response.text
        if text.startswith("<!--"):
            text = text[4:]

        try:
            json_data = json.loads(text)
        except Exception:
            raise ExtractorError("VK: failed to parse JSON payload")

        stream = self._extract_stream(json_data)
        if not stream:
            raise ExtractorError("VK: no playable stream found")

        # AUTO-DETECT STREAM TYPE
        if ".m3u8" in stream:
            endpoint = "hls_manifest_proxy"
        elif ".mpd" in stream:
            endpoint = "mpd_manifest_proxy"
        else:
            # Direct MP4 (VK type=3) → must use /proxy/stream
            endpoint = "proxy_stream_endpoint"

        return {
            "destination_url": stream,
            "request_headers": headers,
            "mediaflow_endpoint": endpoint,
        }

    # ---------------------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        """Turn vk.com/videoXXXX_YYYY into vk.com/video_ext.php?oid=...&id=..."""
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            return url

        oid, vid = m.group(1), m.group(2)
        return f"https://vk.com/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str) -> Dict[str, str]:
        qs = re.search(r"\?(.*)", embed_url)
        parts = (
            dict(x.split("=") for x in qs.group(1).split("&"))
            if qs
            else {}
        )
        oid = parts.get("oid")
        vid = parts.get("id")

        if not oid or not vid:
            raise ExtractorError("VK: cannot extract oid/id from URL")

        return {
            "act": "show",
            "al": "1",
            "video": f"{oid}_{vid}",
        }

    def _extract_stream(self, json_data: Any) -> str | None:
        """
        Extracts the best stream following this order:

        1. HLS (MUCH more stable for Stremio)
        2. MP4 1080/720/480/360
        """

        payload = []
        for item in json_data.get("payload", []):
            if isinstance(item, list):
                payload = item

        params = None
        for item in payload:
            if isinstance(item, dict) and item.get("player"):
                p = item["player"].get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        # Prefer HLS -> Stremio stable
        if params.get("hls"):
            return params["hls"]

        # Then fallback to direct MP4
        return (
            params.get("url1080")
            or params.get("url720")
            or params.get("url480")
            or params.get("url360")
        )
