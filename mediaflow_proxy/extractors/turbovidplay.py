import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class TurboVidPlayExtractor(BaseExtractor):
    domains = [
        "turboviplay.com",
        "emturbovid.com",
        "tuborstb.co",
        "javggvideo.xyz",
        "stbturbo.xyz",
        "turbovidhls.com",
    ]

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        #
        # 1. Load embed
        #
        response = await self._make_request(url)
        html = response.text

        #
        # 2. Extract urlPlay or data-hash
        #
        m = re.search(r'(?:urlPlay|data-hash)\s*=\s*[\'"]([^\'"]+)', html)
        if not m:
            raise ExtractorError("TurboViPlay: No media URL found")

        media_url = m.group(1)

        # Normalize protocol
        if media_url.startswith("//"):
            media_url = "https:" + media_url
        elif media_url.startswith("/"):
            media_url = response.url.origin + media_url

        #
        # 3. Fetch the intermediate playlist (/data3/...uuid.m3u8)
        #
        data_resp = await self._make_request(media_url, headers={"Referer": url})
        playlist = data_resp.text

        #
        # 4. Extract the REAL playlist URL
        #
        m2 = re.search(r'https?://[^\'"\s]+\.m3u8', playlist)
        if not m2:
            raise ExtractorError("TurboViPlay: Unable to extract real playlist URL")

        real_m3u8 = m2.group(0)

        #
        # 5. Download real playlist to check type
        #
        final_resp = await self._make_request(real_m3u8, headers={"Referer": url})
        final_pl = final_resp.text

        # Detect if this is a media playlist (has #EXTINF segments)
        is_media_playlist = "#EXTINF" in final_pl

        #
        # 6. Set referer for final requests
        #
        self.base_headers["referer"] = url

        #
        # 7. Correct endpoint depending on playlist type
        #
        mediaflow_endpoint = (
            "hls_playlist_proxy" if is_media_playlist else "hls_manifest_proxy"
        )

        #
        # 8. Return final master/media playlist URL
        #
        return {
            "destination_url": real_m3u8,
            "request_headers": self.base_headers,
            "mediaflow_endpoint": mediaflow_endpoint,
        }