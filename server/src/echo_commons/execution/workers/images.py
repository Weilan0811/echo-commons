import asyncio
import json
from datetime import datetime

import httpx
from pydantic import ValidationError

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.assets.images import decode_image
from echo_commons.infrastructure.models.image_contracts import ImageTask
from echo_commons.infrastructure.models.images import ImageModelUnavailable


class ImageWorker:
    def __init__(self, generations, assets, active):
        self.generations, self.assets, self.active = generations, assets, active

    async def run_once(self):
        row = self.generations.claim(self.active)
        if row is None:
            return False
        generation_id = row["generation_id"]
        self.active.add(generation_id)
        try:
            await self.execute(row)
        finally:
            self.active.discard(generation_id)
        return True

    async def execute(self, row):
        service, generation_id = self.generations, row["generation_id"]
        gateway = service.gateway
        deadline = datetime.fromisoformat(row["deadline_utc"])
        task_id = row["provider_task_id"]
        urls = tuple(json.loads(row["result_urls_json"] or "[]"))
        parameters = json.loads(row["parameters_json"])
        if not task_id and not urls:
            try:
                async with asyncio.timeout(max(0.001, (deadline - utc_now()).total_seconds())):
                    submitted = await gateway.submit(parameters)
            except ImageModelUnavailable:
                service.fail(generation_id, "image_model_unavailable")
                return
            except TimeoutError:
                service.fail(generation_id, "submission_unknown")
                return
            except httpx.HTTPStatusError as error:
                service.fail(
                    generation_id,
                    "provider_authentication_failed"
                    if error.response.status_code in (401, 403)
                    else "provider_request_rejected",
                )
                return
            except (httpx.HTTPError, ValueError, ValidationError):
                service.fail(generation_id, "submission_unknown")
                return
            task_id, urls = submitted.task_id, submitted.urls
            service.update(
                generation_id,
                "saving" if urls else "generating",
                provider_task_id=task_id,
                result_urls=urls,
                usage=submitted.usage,
            )
        while utc_now() < deadline:
            try:
                async with asyncio.timeout(max(0.001, (deadline - utc_now()).total_seconds())):
                    task = (
                        ImageTask(status="completed", urls=urls)
                        if urls
                        else await gateway.query(task_id, parameters)
                    )
                    if task.status in ("failed", "cancelled"):
                        service.fail(generation_id, "provider_generation_failed")
                        return
                    if task.status == "completed":
                        if len(task.urls) != 1:
                            raise ValueError("Provider must return one image")
                        urls = task.urls
                        service.update(
                            generation_id, "saving", result_urls=urls, usage=task.usage or None
                        )
                        data = await gateway.download(urls[0])
                        image = await asyncio.to_thread(decode_image, data)
                        saving = asyncio.create_task(
                            asyncio.to_thread(
                                self.assets.save,
                                row["owner_player_id"],
                                row["purpose"],
                                image,
                                source="generated",
                                generated=True,
                                generation_id=generation_id,
                            )
                        )
                        try:
                            await asyncio.shield(saving)
                        except asyncio.CancelledError:
                            # 关闭时等文件登记完成，再释放在途任务标记。
                            await saving
                            raise
                        return
            except httpx.HTTPError:
                # 已有 task_id 的查询和下载可以重复，不重新申请生成。
                pass
            except (ValueError, ValidationError):
                service.fail(generation_id, "invalid_generation_result")
                return
            except TimeoutError:
                break
            await asyncio.sleep(
                min(
                    service.settings.image_poll_interval_seconds,
                    max(0, (deadline - utc_now()).total_seconds()),
                )
            )
        service.fail(generation_id, "generation_timeout")
