from ..image_contracts import ImageSubmission


class MiniMaxImages:
    def payload(self, config, request):
        if not config.model.startswith("MiniMax-H3-Image"):
            raise ValueError("MiniMax adapter supports H3 Image generations API")
        if request.reference_images:
            raise ValueError(
                "MiniMax image editing uses a separate API; this entry is text to image"
            )
        return {
            "model": config.model,
            "prompt": request.prompt,
            "n": request.count,
            "size": f"{request.width}x{request.height}",
            "response_format": "url",
        }

    async def submit(self, client, config, request, headers):
        response = await client.post(
            f"{config.base_url}/images/generations",
            headers=headers,
            json=self.payload(config, request),
        )
        response.raise_for_status()
        body = response.json()
        if (body.get("base_resp") or {}).get("status_code", 0) != 0 or body.get("error"):
            raise ValueError("MiniMax image generation failed")
        return ImageSubmission(
            urls=tuple(item["url"] for item in body["data"]), usage=body.get("usage") or {}
        )
