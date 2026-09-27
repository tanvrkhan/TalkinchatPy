"""TalkinChat upload helpers that delegate protocol details to the transport."""

import mimetypes
from pathlib import Path


async def upload_file(transport, path, room, mime_type=None):
    """Upload a local file through the verified TalkinChat adapter."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    detected = mime_type or mimetypes.guess_type(file_path.name)[0]
    return await transport.upload(
        file_path,
        room,
        detected or "application/octet-stream",
    )
