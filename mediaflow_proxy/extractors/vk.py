import json
import re
from typing import Dict, Any, Optional

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
            "Accept-Encoding": "gzip, deflate, br",
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

        # -------------------------------
        # 1) Prefer DASH MPD ALWAYS
        # -------------------------------
        mpd = self._extract_mpd(js)
        if mpd:
            return {
                "destination_url": mpd,             # NO bytes here!
                "request_headers": headers,
                "mediaflow_endpoint": "mpd_manifest_proxy",
            }

        # -------------------------------
        # 2) Fallback to MP4
        # -------------------------------
        mp4 = self._extract_mp4(js)
        if mp4:
            return {
                "destination_url": mp4,             # Stremio will send range requests
                "request_headers": headers,
                "mediaflow_endpoint": "proxy_stream_endpoint",
            }

        raise ExtractorError("VK: no MPD or MP4 stream found")

    # ----------------------------------------------------------------------
    # Helpers
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
    # DASH MPD extractor (MAIN)
    # ----------------------------------------------------------------------

    def _extract_mpd(self, js: Any) -> Optional[str]:
        payload = []
        for item in js.get("payload", []):
            if isinstance(item, list):
                payload = item

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player", {})

            # Option 1: new VK format
            mpd = player.get("dash_manifest")
            if mpd:
                return mpd

            # Option 2: older cached structure
            cache = player.get("cache", {})
            mpd2 = cache.get("data", {}).get("dash")
            if mpd2:
                return mpd2

            # Option 3: params list
            params = player.get("params")
            if isinstance(params, list) and params:
                p = params[0]
                if "dash" in p:
                    return p["dash"]

        return None

    # ----------------------------------------------------------------------
    # MP4 fallback (Kodi ResolveURL compatible)
    # ----------------------------------------------------------------------

    def _extract_mp4(self, js: Any) -> Optional[str]:
        payload = []
        for it in js.get("payload", []):
            if isinstance(it, list):
                payload = it

        params = None
        cache  = None

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player", {})

            # Cached MP4 (best)
            cache = (
                player.get("cache", {})
                .get("data", {})
                .get("progressive")
            )

            # Params list
            p = player.get("params")
            if isinstance(p, list) and p:
                params = p[0]

        # Best quality
        if cache:
            return (
                cache.get("url1080") or
                cache.get("url720") or
                cache.get("url480") or
                cache.get("url360")
            )

        # Fallback
        if params:
            return (
                params.get("url1080") or
                params.get("url720") or
                params.get("url480") or
                params.get("url360")
            )

        return None
