import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from echo_commons.app.composition import Application
from echo_commons.app.http import BUSINESS_RESPONSES, application_for
from echo_commons.infrastructure.models.images import ImageModelUnavailable
from echo_commons.modules.assets.contracts import (
    AssetView,
    CropRequest,
    GenerationRequest,
    GenerationView,
    StyleView,
)
from echo_commons.modules.assets.domain import GenerationPurpose, Purpose
from echo_commons.shared.management import Page, PageOptions

router = APIRouter(prefix="/api", tags=["assets"], responses=BUSINESS_RESPONSES)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/assets/generation-styles", response_model=list[StyleView])
def styles(application: ApplicationDependency):
    return application.image_generations.available_styles()


@router.post("/assets/images", status_code=201, response_model=AssetView)
async def upload(
    application: ApplicationDependency,
    player_id: Annotated[str, Form(min_length=1)],
    purpose: Annotated[GenerationPurpose, Form()],
    file: Annotated[UploadFile, File()],
):
    try:
        limit = (5 if purpose == "character_illustration" else 8) * 1024 * 1024
        data = await file.read(limit + 1)
        return await asyncio.to_thread(application.assets.upload, player_id, purpose, data)
    finally:
        await file.close()


@router.post("/assets/{asset_id}/avatar-crops", status_code=201, response_model=AssetView)
def crop(asset_id: str, body: CropRequest, application: ApplicationDependency):
    return application.assets.crop(asset_id, body)


@router.get("/assets", response_model=Page[AssetView])
def assets(
    player_id: str,
    application: ApplicationDependency,
    purpose: Purpose | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.assets.page(player_id, purpose, PageOptions(cursor=cursor, limit=limit))


@router.get("/assets/{asset_id}", response_model=AssetView)
def asset(asset_id: str, player_id: str, application: ApplicationDependency):
    return application.assets.get(asset_id, player_id)


@router.get("/assets/{asset_id}/images/{variant}", response_class=FileResponse)
def image(asset_id: str, variant: str, application: ApplicationDependency):
    return FileResponse(
        application.assets.file(asset_id, variant),
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/assets/{asset_id}", status_code=204)
def delete(asset_id: str, player_id: str, application: ApplicationDependency):
    application.assets.delete(asset_id, player_id)
    return Response(status_code=204)


@router.post("/image-generations", status_code=202, response_model=GenerationView)
def generate(body: GenerationRequest, application: ApplicationDependency):
    try:
        return application.image_generations.create(body)
    except ImageModelUnavailable as error:
        return JSONResponse(
            status_code=503, content={"error": {"code": error.code, "message": str(error)}}
        )


@router.get("/image-generations/{generation_id}", response_model=GenerationView)
def generation(generation_id: str, player_id: str, application: ApplicationDependency):
    return application.image_generations.get(generation_id, player_id)
