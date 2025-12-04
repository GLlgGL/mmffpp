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

        stream = self._extract_stream(json_data)
        if not stream:
            raise ExtractorError("VK: no playable stream found")

        # ------------------------------------------------------
        # FIXED STREAM TYPE DETECTION
        # ------------------------------------------------------

        # HLS always ends with:  /video.m3u8?....
        is_hls = "video.m3u8" in stream

        # MPD never ends with .mpd → detect by MPD parameters
        is_mpd = (
            "cmd=videoPlayerCdn" in stream
            or "clientType=" in stream and "id=" in stream
        )

        if is_hls:
            endpoint = "hls_manifest_proxy"
        elif is_mpd:
            endpoint = "mpd_manifest_proxy"
        else:
            # direct mp4 fallback
            endpoint = "proxy_stream_endpoint"

        return {
            "destination_url": stream,
            "request_headers": headers,
            "mediaflow_endpoint": endpoint,
        }

    # --------------------------------------------
    # Helpers
    # --------------------------------------------

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

    def _extract_stream(self, json_data: Any) -> str | None:
        payload = []
        for i in json_data.get("payload", []):
            if isinstance(i, list):
                payload = i

        params = None
        for item in payload:
            if isinstance(item, dict) and item.get("player"):
                p = item["player"].get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        # HLS first
        if params.get("hls"):
            return params["hls"]

        # videoPlayerCdn → MPD type
        if params.get("dash"):
            return params["dash"]

        # MP4 fallback
        return (
            params.get("url1080")
            or params.get("url720")
            or params.get("url480")
            or params.get("url360")
        )
