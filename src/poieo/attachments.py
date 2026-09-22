"""What a person attaches to a message: a picture, or a text file.

Checked where it arrives, because what gets past here is shown to a model and
kept on disk: a picture is told apart by its first bytes rather than its name,
a text file must read as UTF-8, and a name is one plain file name, never a
path. What passes becomes content blocks beside the message (see
`providers.base`), and the bytes are kept with the run they started.

Design: docs/web.md
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any

from .errors import SpecError

# The most one run may be handed, and the most one picture may weigh, in
# bytes. A model endpoint takes about 5 MB of image once it is base64, which
# is four thirds of the picture cap.
AT_MOST = 4
IMAGE_CAP = 3_750_000
TEXT_CAP = 200_000

# What a picture is, read from its first bytes rather than its name: a file
# called `.png` that holds words is not a picture, and saying it was would
# have the endpoint refuse the whole turn.
_PICTURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_TEXTS = {"text/plain", "text/markdown", "text/csv", "application/json"}
# One plain file name: no separators, no leading dot, nothing a path or a
# header could be made to trip over.
_NAME = re.compile(r"[^/\\.\x00-\x1f][^/\\\x00-\x1f]{0,99}")


def picture_type(head: bytes) -> str | None:
    """The picture's media type, from its first bytes, or None if it is not one."""
    for magic, media_type in _PICTURES:
        if head.startswith(magic):
            return media_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True, slots=True)
class Attachment:
    name: str
    media_type: str
    body: bytes


def _one(raw: Any) -> Attachment:
    if not isinstance(raw, dict):
        raise SpecError("an attachment is {name, media_type, data}")
    name, media_type, data = raw.get("name"), raw.get("media_type"), raw.get("data")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or ".." in name:
        raise SpecError(f"an attachment's name is one plain file name, not {name!r}")
    if not isinstance(media_type, str) or not (media_type.startswith("image/") or media_type in _TEXTS):
        raise SpecError(f"{name}: attachments are pictures and text files, not {media_type!r}")
    if not isinstance(data, str):
        raise SpecError(f"{name}: an attachment's data is base64")
    try:
        body = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise SpecError(f"{name}: an attachment's data is base64") from None
    if media_type.startswith("image/"):
        if len(body) > IMAGE_CAP:
            raise SpecError(f"{name} is too large to show ({len(body)} bytes; at most {IMAGE_CAP})")
        if picture_type(body[:16]) != media_type:
            raise SpecError(f"{name} is not a {media_type} picture")
        return Attachment(name, media_type, body)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise SpecError(f"{name}: a text attachment must be UTF-8") from None
    if len(text) > TEXT_CAP:
        raise SpecError(f"{name} is too large to read ({len(text)} characters; at most {TEXT_CAP})")
    return Attachment(name, media_type, body)


def checked_attachments(raw: Any) -> list[Attachment]:
    """The attachments a request carried, checked, or the reason they are not."""
    if not isinstance(raw, list):
        raise SpecError("attachments are a list of {name, media_type, data}")
    if len(raw) > AT_MOST:
        raise SpecError(f"a message takes at most {AT_MOST} attachments")
    taken = [_one(item) for item in raw]
    names = [one.name for one in taken]
    for name in names:
        if names.count(name) > 1:
            raise SpecError(f"{name} is attached twice")
    return taken


def attachment_blocks(attachments: list[Attachment]) -> list[dict[str, Any]]:
    """The attachments as content blocks: a picture as one, a text file as its words."""
    blocks: list[dict[str, Any]] = []
    for one in attachments:
        if one.media_type.startswith("image/"):
            data = base64.b64encode(one.body).decode("ascii")
            blocks.append({"type": "image", "media_type": one.media_type, "data": data})
        else:
            blocks.append({"type": "text", "text": f"Attached file {one.name}:\n{one.body.decode('utf-8')}"})
    return blocks
