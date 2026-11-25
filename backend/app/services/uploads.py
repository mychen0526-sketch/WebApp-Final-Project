"""Image uploads from the browser (post pictures, canvas exports, templates).

The format is decided from the file's bytes, not from the client's Content-Type (an HTML file
labelled image/png is rejected), and the size cap is enforced while reading, so an oversized
upload is never held in memory in full.
"""
from fastapi import UploadFile

from ..errors import Unprocessable
from .webfetch import sniff_image

EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg"}
CHUNK = 64 * 1024


async def read_image(file: UploadFile, max_bytes: int) -> tuple[bytes, str, str]:
    """Returns (data, content_type, extension) or raises 422."""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise Unprocessable(f"圖片大小需介於 1 byte 到 {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise Unprocessable(f"圖片大小需介於 1 byte 到 {max_bytes // (1024 * 1024)} MB")
    content_type = sniff_image(data)
    if content_type not in EXTENSIONS:
        raise Unprocessable("只接受 PNG 或 JPEG 圖片（依檔案內容判斷）")
    return data, content_type, EXTENSIONS[content_type]
