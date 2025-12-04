import json
import re
from typing import Dict, Any, Tuple

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):
    """
    VK extractor with sane priority:

    1. HLS (.m3u8)  → hls_manifest_proxy  (best for Stremio)
    2. MPD (.mpd)   → mpd_manifest_proxy  (if VK ever exposes real MPD URL)
    3. MP4 fallback → proxy_stream_endpoint (last resort)
    """

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        # Normalize any vk/video style URL to video_ext.php
        embed_url = self._normalize(url)

        # al_video.php endpoint (XMLHttpRequest API)
        ajax_url = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        data = self._build_ajax_data(embed_url)

        # VK responds with HTML-comment-wrapped JSON like: <!--{"payload":...}
        response = await self._make_request(
            ajax_url,
            method="POST",
            data=data,
            headers=headers,
        )

        text = response.text.lstrip("<!--")

        try:
            json_data = json.loads(text)
        except Exception as e:
            raise ExtractorError(f"VK: invalid JSON payload: {e}")

        # Extract player params (where URLs live)
        params = self._extract_params(json_data)
        if not params:
            raise ExtractorError("VK: could not find player params in payload")

        # Pick best stream + type
        stream_url, stream_type = self._select_stream(params)
        if not stream_url:
            raise ExtractorError("VK: no playable stream found")

        # Map stream type → mediaflow endpoint
        if stream_type == "hls":
            endpoint = "hls_manifest_proxy"
        elif stream_type == "mpd":
            endpoint = "mpd_manifest_proxy"
        else:
            # direct MP4 fallback
            endpoint = "proxy_stream_endpoint"

        return {
            "destination_url": stream_url,
            "request_headers": headers,
            "mediaflow_endpoint": endpoint,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        """
        Turn vk.com/video(-oid)_(id) into video_ext.php format if needed.
        """
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            return url

        oid, vid = m.group(1), m.group(2)
        return f"https://vk.com/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        """
        Build https://<host>/al_video.php?act=show
        """
        host_match = re.search(r"https?://([^/]+)", embed_url)
        if not host_match:
            raise ExtractorError("VK: cannot detect host from embed URL")

        host = host_match.group(1)
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str) -> Dict[str, str]:
        """
        Extract oid + id from video_ext.php query and build POST data.
        """
        qs = re.search(r"\?(.*)", embed_url)
        parts: Dict[str, str] = (
            dict(x.split("=", 1) for x in qs.group(1).split("&"))
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

    def _extract_params(self, json_data: Any) -> Dict[str, Any] | None:
        """
        VK wraps the interesting data in json_data["payload"][...]["player"]["params"][0]
        (structure varies a bit over time, so we walk defensively).
        """
        payload = []

        for item in json_data.get("payload", []):
            if isinstance(item, list):
                payload = item

        params: Dict[str, Any] | None = None

        for item in payload:
            if isinstance(item, dict) and item.get("player"):
                p = item["player"].get("params")
                # Sometimes a list with single dict
                if isinstance(p, list) and p:
                    params = p[0]
                elif isinstance(p, dict):
                    params = p

        return params

    def _select_stream(self, params: Dict[str, Any]) -> Tuple[str | None, str | None]:
        """
        Decide which stream to use and what type it is.

        Returns:
            (url, type) where type is "hls", "mpd", or "mp4"
        """

        # 1) Prefer HLS – this is what we see in your logs:
        #    https://vkvdXXX.okcdn.ru/video.m3u8?cmd=videoPlayerCdn&...
        hls_url = params.get("hls") or params.get("hls_live") or params.get("hls_manifest")
        if isinstance(hls_url, str) and "m3u8" in hls_url:
            return hls_url, "hls"

        # 2) Real MPD (only if it actually looks like a .mpd URL)
        #    We *do not* treat 'dash' like '?expires=...&type=3...' as MPD.
        dash_manifest = params.get("dash_manifest")
        if isinstance(dash_manifest, str) and dash_manifest.endswith(".mpd"):
            return dash_manifest, "mpd"

        dash_url = params.get("dash")
        if isinstance(dash_url, str) and ".mpd" in dash_url:
            return dash_url, "mpd"

        # If you ever want to synthesize MPD from HLS:
        # if isinstance(hls_url, str) and "video.m3u8" in hls_url:
        #     mpd_url = hls_url.replace("video.m3u8", "video.mpd")
        #     return mpd_url, "mpd"

        # 3) MP4 fallback (direct file)
        for key in ("url2160", "url1440", "url1080", "url720", "url480", "url360"):
            mp4 = params.get(key)
            if isinstance(mp4, str) and mp4.startswith("http"):
                return mp4, "mp4"

        return None, None
