"""Bounded PNG/JPEG input to a deterministic portrait grayscale PNG."""
from dataclasses import dataclass
from io import BytesIO
import struct
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_BACKGROUND = 2 * 1024 * 1024


@dataclass(frozen=True)
class Crop:
    """Source pixels after EXIF orientation; omitted size means centered cover.

    mime_type is the actual upload Content-Type and is required at the HTTP
    boundary. The PNG default supports server-owned normalized backgrounds.
    No filenames or paths are accepted by this interface.
    """
    x: int = 0
    y: int = 0
    width: int | None = None
    height: int | None = None
    mime_type: str = 'image/png'


def _open(source: bytes, mime_type: str) -> Image.Image:
    if not isinstance(source, bytes) or not source:
        raise ValueError('empty image')
    if len(source) > MAX_UPLOAD:
        raise ValueError('image exceeds 10 MiB')
    formats = {'image/png': 'PNG', 'image/jpeg': 'JPEG'}
    if mime_type not in formats:
        raise ValueError('only image/png and image/jpeg are supported')
    # Pillow may require later PNG chunks even to open a file. Check IHDR first.
    if source.startswith(b'\x89PNG\r\n\x1a\n') and len(source) >= 24:
        width, height = struct.unpack('>II', source[16:24])
        if width * height > MAX_PIXELS:
            raise ValueError('image exceeds 20 MP')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            image = Image.open(BytesIO(source))
            if image.format != formats[mime_type]:
                raise ValueError('MIME does not match the real image format')
            if image.width * image.height > MAX_PIXELS:
                raise ValueError('image exceeds 20 MP')
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('animated images are unsupported')
            image.verify()
            image = Image.open(BytesIO(source))
            image.load()
            return image
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
            raise ValueError('corrupt or oversized image') from error


def normalize_background(source: bytes, crop: Crop) -> bytes:
    image = ImageOps.exif_transpose(_open(source, crop.mime_type))
    rgba = image.convert('RGBA')
    image = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('L')
    if crop.width is None and crop.height is None:
        if crop.x != 0 or crop.y != 0:
            raise ValueError('automatic crop has no origin')
        image = ImageOps.fit(image, (480, 800), Image.Resampling.LANCZOS)
    else:
        values = (crop.x, crop.y, crop.width, crop.height)
        if any(type(value) is not int for value in values):
            raise ValueError('crop must use integer source pixels')
        x, y, width, height = values
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > image.width or y + height > image.height:
            raise ValueError('crop is outside image bounds')
        image = image.crop((x, y, x + width, y + height)).resize((480, 800), Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, 'PNG', optimize=False)
    result = out.getvalue()
    if len(result) > MAX_BACKGROUND:
        raise ValueError('normalized background exceeds 2 MiB')
    return result


def validate_background(source: bytes) -> None:
    """Store accepts already-normalized bytes, never silently edits a preview."""
    if len(source) > MAX_BACKGROUND:
        raise ValueError('background exceeds 2 MiB')
    image = _open(source, 'image/png')
    if image.size != (480, 800) or image.mode != 'L':
        raise ValueError('background must be a 480x800 grayscale PNG')
