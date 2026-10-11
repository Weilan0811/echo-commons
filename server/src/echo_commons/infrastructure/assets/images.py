from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from echo_commons.modules.assets.domain import SPECS


def decode_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))
        if image.format not in {"WEBP", "PNG", "JPEG"} or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Only single-frame WebP, PNG and JPEG images are accepted")
        if image.width * image.height > 24_000_000:
            raise ValueError("Image exceeds 24 million pixels")
        image.load()
        return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("Image cannot be decoded") from error


def variants(image: Image.Image, purpose: str, *, generated: bool = False):
    stem, bounds, widths = SPECS[purpose]
    if generated:
        if image.width < bounds[0] or image.height < bounds[1]:
            raise ValueError("Generated image is smaller than the required size")
        if abs(image.width / image.height - bounds[0] / bounds[1]) > 0.005:
            raise ValueError("Generated image has an incorrect aspect ratio")
        image = image.resize(bounds, Image.Resampling.LANCZOS)
    else:
        image = image.copy()
        image.thumbnail(bounds, Image.Resampling.LANCZOS)
    result = []
    for variant, width in [("standard", image.width), *[(str(w), w) for w in widths]]:
        output = image.copy()
        if width < output.width:
            output.thumbnail(
                (width, round(output.height * width / output.width)), Image.Resampling.LANCZOS
            )
        buffer = BytesIO()
        output.save(buffer, format="WEBP", quality=90)
        filename = f"{stem}.webp" if variant == "standard" else f"{stem}-{variant}.webp"
        result.append((variant, filename, output.width, output.height, buffer.getvalue()))
    return result
