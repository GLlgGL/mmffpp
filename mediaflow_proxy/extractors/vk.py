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

        # Send POST request
        response = await self._make_request(
            ajax_url, method="POST", data=data, headers=headers
        )

        # Remove VK comment header: <!--{...}
        text = response.text.lstrip("<!--")

        # Parse JSON
        try:
            json_data = json.loads(text)
        except:
            raise ExtractorError("VK: invalid JSON payload")

        # Extract best playable stream
        stream = self._extract_stream(json_data)
        if not stream:
            raise ExtractorError("VK: no playable stream found")

        # ---------------------------------------------------------------------
        # CORRECT STREAM TYPE DETECTION
        # ---------------------------------------------------------------------
        s = stream.lower()

        # ❗ HLS is ALWAYS .m3u8
        is_hls = ".m3u8" in s

        # ❗ DASH (MPD) from VK ALWAYS uses these:
        #     cmd=videoPlayerCdn
        #     AND params['dash']
        is_mpd = ("cmd=videoplayercdn" in s) or ("dash" in s)

        # ❗ Direct MP4 always has bytes= or type= without m3u8/mpd
        is_mp4 = (
            ("bytes=" in s)
            or ("type=" in s and not is_hls and not is_mpd)
        )

        # Select correct MediaFlow endpoint
        if is_hls:
            endpoint = "hls_manifest_proxy"

        elif is_mpd:
            endpoint = "mpd_manifest_proxy"

        else:
            # fallback for direct MP4 or unknown types
            endpoint = "proxy_stream_endpoint"

        # Return extraction result
        return {
            "destination_url": stream,
            "request_headers": headers,
            "mediaflow_endpoint": endpoint,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        """Normalize vk.com/video123_456 → video_ext.php version."""
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

    def _build_ajax_data(self, embed_url: str):
        qs = re.search(r"\?(.*)", embed_url)
        parts = dict(x.split("=") for x in qs.group(1).split("&")) if qs else {}
        oid = parts.get("oid")
        vid = parts.get("id")
        return {
            "act": "show",
            "al": "1",
            "video": f"{oid}_{vid}",
        }

    def _extract_stream(self, json_data: Any) -> str | None:
        """
        Returns:
            HLS (.m3u8) if available
            DASH (params["dash"])
            or MP4 fallback (1080/720/480/360)
        """
        payload = []
        for item in json_data.get("payload", []):
            if isinstance(item, list):
                payload = item

        params = None
        for block in payload:
            if isinstance(block, dict) and block.get("player"):
                p = block["player"].get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        # Prefer HLS
        if params.get("hls"):
            return params["hls"]

        # Then DASH (MPD)
        if params.get("dash"):
            return params["dash"]

        # MP4 fallback
        return (
            params.get("url1080")
            or params.get("url720")
            or params.get("url480")
            or params.get("url360")
        )
