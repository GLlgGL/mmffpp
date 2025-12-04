import json
import re
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):
    """
    VK extractor that prefers DASH (MPD → HLS via MediaFlow /mpd/*),
    with a fallback to progressive MP4 if no MPD is found.
    """

    def __init__(self, request_headers: dict):
        super().__init__(request_headers)
        # Tell MediaFlow which proxy endpoint to hit.
        # For DASH → HLS we use /mpd/manifest.m3u8 (mpd_manifest_proxy route).
        self.mediaflow_endpoint = "mpd_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        Main entry:
        1. Normalize any VK URL to video_ext.php form.
        2. Try to fetch it and see if we get an MPD (DASH XML).
        3. If MPD is present → return it for DASH→HLS conversion.
        4. If not, fall back to the older JSON/MP4 logic (al_video.php).
        """
        embed_url = self._normalize(url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        # -----------------------------
        # 1) TRY DIRECT MPD FROM video_ext.php
        # -----------------------------
        resp = await self._make_request(embed_url, method="GET", headers=headers)
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
        text = resp.text or ""

        # MPD is either signaled via content-type or via <MPD ...> root tag.
        if "application/dash+xml" in content_type or "<MPD" in text:
            # Use the final URL after redirects (vk6-x.vkuser.net/?...type=1...),
            # because BaseURL entries in MPD are relative to that.
            mpd_url = str(resp.url)
            return {
                "destination_url": mpd_url,
                "request_headers": headers,
                "mediaflow_endpoint": self.mediaflow_endpoint,
            }

        # -----------------------------
        # 2) FALLBACK: OLD JSON / MP4 LOGIC (al_video.php)
        # -----------------------------
        ajax_url = self._build_ajax_url(embed_url)
        ajax_data = self._build_ajax_data(embed_url)

        ajax_resp = await self._make_request(
            ajax_url, method="POST", data=ajax_data, headers=headers
        )
        text = ajax_resp.text.lstrip("<!--")

        try:
            json_data = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON payload (no MPD, no params)")

        # Try to extract progressive MP4 URLs (as ResolveURL does)
        mp4 = self._extract_progressive_mp4(json_data)
        if mp4:
            # For direct MP4, we want /stream endpoint instead of /mpd/*
            return {
                "destination_url": mp4,
                "request_headers": headers,
                "mediaflow_endpoint": "proxy_stream_endpoint",
            }

        # Fallback: HLS (if present)
        hls_url = self._extract_hls(json_data)
        if hls_url:
            # Let normal HLS path handle it via /hls/manifest.m3u8
            return {
                "destination_url": hls_url,
                "request_headers": headers,
                "mediaflow_endpoint": "hls_manifest_proxy",
            }

        raise ExtractorError("VK: no DASH MPD, no MP4 and no HLS URL found")

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------

    def _normalize(self, url: str) -> str:
        """
        Normalize various VK URL forms into a canonical video_ext.php URL.
        Examples:
            https://vk.com/video-12345_67890
            https://vkvideo.ru/video_ext.php?oid=...&id=...
        """
        parsed = urlparse(url)

        # If it's already video_ext.php, just keep it
        if "video_ext.php" in (parsed.path or ""):
            return url

        # Try query: ?oid=XXX&id=YYY
        qs = parse_qs(parsed.query)
        oid = qs.get("oid", [None])[0]
        vid = qs.get("id", [None])[0]
        if oid and vid:
            return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

        # Try to match /video-123_456 style
        m = re.search(r"video(-?\d+)_(\d+)", url)
        if m:
            oid = m.group(1)
            vid = m.group(2)
            return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

        # As a last resort, just return original
        return url

    def _build_ajax_url(self, embed_url: str) -> str:
        """
        Build al_video.php URL from the host we see in embed_url.
        """
        m = re.search(r"https?://([^/]+)", embed_url)
        host = m.group(1) if m else "vkvideo.ru"
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str) -> Dict[str, Any]:
        """
        Build POST form data for al_video.php based on the embed URL.
        """
        qs_match = re.search(r"\?(.*)", embed_url)
        parts = {}
        if qs_match:
            for x in qs_match.group(1).split("&"):
                if "=" in x:
                    k, v = x.split("=", 1)
                    parts[k] = v

        oid = parts.get("oid")
        vid = parts.get("id")

        data: Dict[str, Any] = {
            "act": "show",
            "al": 1,
        }
        if oid and vid:
            data["video"] = f"{oid}_{vid}"
        else:
            # fallback – leave it blank, VK may still respond but probably useless
            data["video"] = ""

        # You could add playlist-related fields here if needed,
        # similar to the ResolveURL code.
        return data

    def _extract_progressive_mp4(self, json_data: Any) -> str | None:
        """
        ResolveURL-like logic:
        From json_data['payload'] find 'player'->'params'[0] and pull url1080/url720/...
        """
        payload = []
        for item in json_data.get("payload", []):
            if isinstance(item, list):
                payload = item

        params = None
        for item in payload:
            if isinstance(item, dict) and item.get("player"):
                player = item["player"]
                p = player.get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        # Prefer highest quality
        return (
            params.get("url1080")
            or params.get("url720")
            or params.get("url480")
            or params.get("url360")
        )

    def _extract_hls(self, json_data: Any) -> str | None:
        """
        If VK only gives us HLS (hls or hls_ondemand/hls_live), pull that URL.
        """
        payload = []
        for item in json_data.get("payload", []):
            if isinstance(item, list):
                payload = item

        params = None
        for item in payload:
            if isinstance(item, dict) and item.get("player"):
                player = item["player"]
                p = player.get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        return (
            params.get("hls")
            or params.get("hls_ondemand")
            or params.get("hls_live")
        )
