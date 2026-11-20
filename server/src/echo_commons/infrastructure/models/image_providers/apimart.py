from ..image_contracts import ImageSubmission, ImageTask


class APIMartImages:
    def payload(self, config, request):
        payload = {
            "model": config.model,
            "prompt": request.prompt,
            "n": request.count,
            "resolution": "1k",
            "size": f"{request.width}x{request.height}",
        }
        if request.reference_images:
            payload["image_urls"] = list(request.reference_images)
        return payload

    async def submit(self, client, config, request, headers):
        response = await client.post(
            f"{config.base_url}/images/generations",
            headers=headers,
            json=self.payload(config, request),
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 200 or len(body.get("data", [])) != 1:
            raise ValueError("Invalid APIMart submission")
        return ImageSubmission(task_id=body["data"][0]["task_id"])

    async def query(self, client, config, task_id, headers):
        response = await client.get(f"{config.base_url}/tasks/{task_id}", headers=headers)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 200 or body["data"]["id"] != task_id:
            raise ValueError("Invalid APIMart task identity")
        task = body["data"]
        urls = tuple(image["url"][0] for image in (task.get("result") or {}).get("images", []))
        return ImageTask(status=task["status"], urls=urls)
