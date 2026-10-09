import asyncio
import json
from datetime import datetime

import httpx
from pydantic import ValidationError

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.assets.images import decode_image
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
        if not task_id:
            try:
                async with asyncio.timeout(max(0.001, (deadline - utc_now()).total_seconds())):
                    task_id = await gateway.submit(json.loads(row["parameters_json"]))
            except ImageModelUnavailable:
                service.fail(generation_id, "image_model_unavailable")
                return
            except TimeoutError:
                service.fail(generation_id, "submission_unknown")
                return
            except (httpx.HTTPError, ValueError, ValidationError):
                service.fail(generation_id, "submission_unknown")
                return
            service.update(generation_id, "generating", provider_task_id=task_id)
        while utc_now() < deadline:
            try:
                async with asyncio.timeout(max(0.001, (deadline - utc_now()).total_seconds())):
                    task = await gateway.query(task_id)
                    if task.status in ("failed", "cancelled"):
                        service.fail(generation_id, "provider_generation_failed")
                        return
                    if task.status == "completed":
                        if task.result is None or len(task.result.images) != 1:
                            raise ValueError("Provider must return one image")
                        service.update(generation_id, "saving")
                        data = await gateway.download(task.result.images[0].url[0])
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
