"""Upload boundary tests: bad input must never become a published resource."""
from io import BytesIO
import struct
import zlib

from PIL import Image
import pytest
from manager.images import Crop, normalize_background


def image_bytes(size=(600, 1000), fmt='PNG'):
    out = BytesIO()
    Image.new('RGB', size, (90, 130, 180)).save(out, fmt)
    return out.getvalue()


def test_normalizes_png_and_jpeg_to_portrait_grayscale():
    for fmt, mime in [('PNG', 'image/png'), ('JPEG', 'image/jpeg')]:
        result = normalize_background(image_bytes(fmt=fmt), Crop(mime_type=mime))
        image = Image.open(BytesIO(result))
        image.load()
        assert image.format == 'PNG'
        assert image.mode == 'L'
        assert image.size == (480, 800)
        assert len(result) <= 2097152


def test_crop_uses_source_pixels_then_resizes():
    image = Image.new('RGB', (960, 800), 'white')
    image.paste('black', (480, 0, 960, 800))
    out = BytesIO()
    image.save(out, 'PNG')
    result = normalize_background(out.getvalue(), Crop(480, 0, 480, 800))
    assert Image.open(BytesIO(result)).getextrema() == (0, 0)


def test_transparency_is_composited_on_white():
    out = BytesIO()
    Image.new('RGBA', (480, 800), (0, 0, 0, 0)).save(out, 'PNG')
    result = normalize_background(out.getvalue(), Crop())
    assert Image.open(BytesIO(result)).getextrema() == (255, 255)


def test_rejects_upload_larger_than_ten_mib():
    with pytest.raises(ValueError, match='10 MiB'):
        normalize_background(b'x' * (10 * 1024 * 1024 + 1), Crop())


def test_rejects_more_than_twenty_megapixels_before_decode():
    # Deliberately no IDAT: dimensions must be rejected before payload decoding.
    payload = struct.pack('>IIBBBBB', 5000, 4001, 8, 2, 0, 0, 0)
    chunk = b'IHDR' + payload
    header = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + chunk + struct.pack('>I', zlib.crc32(chunk))
    with pytest.raises(ValueError, match='20 MP'):
        normalize_background(header, Crop())


@pytest.mark.parametrize('source,mime', [(image_bytes(), 'image/jpeg'), (image_bytes(fmt='JPEG'), 'image/png'), (image_bytes(), 'text/plain'), (image_bytes(fmt='GIF'), 'image/gif')])
def test_rejects_false_or_unsupported_mime(source, mime):
    with pytest.raises(ValueError):
        normalize_background(source, Crop(mime_type=mime))


@pytest.mark.parametrize('source', [b'', b'not an image', image_bytes()[:60]])
def test_rejects_corrupt_images(source):
    with pytest.raises(ValueError):
        normalize_background(source, Crop())


@pytest.mark.parametrize('crop', [Crop(-1, 0, 480, 800), Crop(0, 0, 0, 1), Crop(0, 0, 2000, 800), Crop(0, 0, 1, None), Crop(float('nan'), 0, 480, 800)])
def test_rejects_invalid_crop(crop):
    with pytest.raises(ValueError):
        normalize_background(image_bytes(), crop)
