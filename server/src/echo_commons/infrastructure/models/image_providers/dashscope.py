from ..image_contracts import ImageSubmission


class DashScopeImages:
    def payload(self, config, request):
        if not config.model.startswith(("qwen-image-3.", "qwen-image-2.1")):
            raise ValueError("DashScope adapter supports Qwen Image 3.0 and 2.1 Images API")
        content = [{"image": image} for image in request.reference_images]
        content.append({"text": request.prompt})
        payload = {
            "model": config.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"size": f"{request.width}*{request.height}", "n": request.count},
        }
        if len(request.reference_images) > 3:
            raise ValueError("Qwen Image 3.0 accepts up to three reference images")
        return payload

    async def submit(self, client, config, request, headers):
        response = await client.post(
            f"{config.base_url}/services/aigc/multimodal-generation/generation",
            headers=headers,
            json=self.payload(config, request),
        )
        response.raise_for_status()
        body = response.json()
        return ImageSubmission(
            urls=tuple(
                item["image"]
                for choice in body["output"]["choices"]
                for item in choice["message"]["content"]
                if "image" in item
            ),
            usage=body.get("usage") or {},
        )
