from typing import Literal

Purpose = Literal[
    "character_illustration", "character_avatar", "community_cover", "chat_background"
]
GenerationPurpose = Literal["character_illustration", "community_cover", "chat_background"]

SPECS = {
    "character_illustration": ("illustration", (1080, 1350), (540,)),
    "character_avatar": ("avatar", (512, 512), (256,)),
    "community_cover": ("cover", (1600, 600), (768, 1536)),
    "chat_background": ("background", (1920, 1080), ()),
}


def image_url(asset_id: str, variant: str = "standard") -> str:
    return f"/api/assets/{asset_id}/images/{variant}"
