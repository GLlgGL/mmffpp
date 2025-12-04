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
    Correct VK extractor:
    1. GET video_ext.php WITHOUT FOLLOW REDIRECTS
    2. If Location → vkuser.net with ?type=1 → DASH MPD
    3. If Location → login.vk.com → fallback to al_video.php MP4
    """

    def __init__(self, request_headers: dict):
        super().__init__(request_headers)
        self.mediaflow_endpoint = "mpd_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed = self._normalize(url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
        }

        # -----------------------------------------------------------
        # 1) First request: NO REDIRECTS → read Location header
        # -----------------------------------------------------------
        resp = await self._make_request(
            embed,
            method="GET",
            headers=headers,
            follow_redirects=False,  # IMPORTANT
        )

        # --- Case A: Server returned redirect ---
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")

            # Login → fallback
            if "login.vk.com" in loc:
                return await self._fallback_mp4(embed, headers)

            # Redirect to MPD XML on vkuser.net
            if "vkuser.net" in loc:
                return {
                    "destination_url": loc,
                    "request_headers": headers,
                    "mediaflow_endpoint": "mpd_manifest_proxy",
                }

        # --- Case B: Server returned XML directly ---
        content_type = (resp.headers.get("content-type") or "").lower()
        text = resp.text or ""

        if "application/dash+xml" in content_type or "<MPD" in text:
            return {
                "destination_url": str(resp.url),
                "request_headers": headers,
                "mediaflow_endpoint": "mpd_manifest_proxy",
            }

        # --- Fallback ---
        return await self._fallback_mp4(embed, headers)

    # -----------------------------------------------------------
    # FALLBACK: old JSON → progressive MP4
    # -----------------------------------------------------------
    async def _fallback_mp4(self, embed_url, headers):
        ajax_url = self._build_ajax_url(embed_url)
        ajax_data = self._build_ajax_data(embed_url)

        resp = await self._make_request(
            ajax_url,
            method="POST",
            data=ajax_data,
            headers=headers
        )

        text = resp.text.lstrip("<!--")
        try:
            js = json.loads(text)
        except:
            raise ExtractorError("VK: fallback JSON invalid")

        mp4 = self._extract_progressive_mp4(js)
        if not mp4:
            raise ExtractorError("VK: no MP4 found in fallback")

        return {
            "destination_url": mp4,
            "request_headers": headers,
            "mediaflow_endpoint": "proxy_stream_endpoint",
        }

    # -----------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------

    def _normalize(self, url):
        parsed = urlparse(url)
        if "video_ext.php" in parsed.path:
            return url

        qs = parse_qs(parsed.query)
        oid = qs.get("oid", [None])[0]
        vid = qs.get("id", [None])[0]
        if oid and vid:
            return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if m:
            return f"https://vkvideo.ru/video_ext.php?oid={m.group(1)}&id={m.group(2)}"

        return url

    def _build_ajax_url(self, embed_url):
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url):
        qs = parse_qs(urlparse(embed_url).query)
        oid = qs.get("oid", [""])[0]
        vid = qs.get("id", [""])[0]
        return {"act": "show", "al": 1, "video": f"{oid}_{vid}"}

    def _extract_progressive_mp4(self, js):
        payload = []
        for item in js.get("payload", []):
            if isinstance(item, list):
                payload = item

        params = None
        for entry in payload:
            if isinstance(entry, dict) and entry.get("player"):
                p = entry["player"]["params"]
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        return (
            params.get("url1080")
            or params.get("url720")
            or params.get("url480")
            or params.get("url360")
        )
