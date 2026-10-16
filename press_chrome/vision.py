"""Read-only image judgments and reversible image coordinate transforms."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid

from PIL import Image, UnidentifiedImageError

from . import client
from .vision_http import VisionError, post

MODEL = "jev-1.14.0"


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    width: int
    height: int
    resized_width: int
    resized_height: int
    upload_width: int
    upload_height: int
    pad_x: int
    pad_y: int

    def map_box(self, edges: dict) -> dict:
        def coordinate(name, extent, padding, original, resized):
            fraction = float(edges[name])
            if not math.isfinite(fraction) or not 0 <= fraction <= 1:
                raise VisionError("Invalid TypeSafe box fractions")
            return min(original, max(0, (fraction * extent - padding) * original / resized))
        left, right = [coordinate(k, self.upload_width, self.pad_x, self.width,
                                  self.resized_width) for k in ("left", "right")]
        top, bottom = [coordinate(k, self.upload_height, self.pad_y, self.height,
                                  self.resized_height) for k in ("top", "bottom")]
        if right < left or bottom < top:
            raise VisionError("Invalid TypeSafe box edges")
        return rectangle(left, top, right, bottom)


def rectangle(left, top, right, bottom):
    return dict(x=left, y=top, width=right-left, height=bottom-top,
                left=left, top=top, right=right, bottom=bottom)


def prepare_image(raw: bytes) -> PreparedImage:
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG"}:
                raise VisionError("Image must be PNG or JPEG")
            width, height = source.size
            scale = min(1, 1568 / max(width, height))
            rw, rh = max(1, round(width*scale)), max(1, round(height*scale))
            image = source.convert("RGB").resize((rw, rh), Image.Resampling.LANCZOS)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise VisionError(f"Cannot read image: {exc}") from None
    uw, uh = max(280, rw), max(280, rh)
    px, py = (uw-rw)//2, (uh-rh)//2
    padded = Image.new("RGB", (uw, uh), "white")
    padded.paste(image, (px, py))
    buffer = BytesIO()
    padded.save(buffer, format="PNG")
    data = buffer.getvalue()
    if len(data) > 16*1024*1024:
        raise VisionError("Prepared image exceeds TypeSafe's 16 MiB limit")
    return PreparedImage(data, width, height, rw, rh, uw, uh, px, py)


def request_model(image: PreparedImage, questions: dict) -> dict:
    reference = str(uuid.uuid4())
    payload = dict(model=MODEL, state={"screenshot": reference},
                   assets={reference: {"type": "image", "part": "img"}}, questions=questions)
    boundary = "chtabs-" + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\n'
            'Content-Type: application/json\r\n\r\n').encode() + json.dumps(payload).encode()
    body += (f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="img"; filename="screenshot.png"\r\n'
             'Content-Type: image/png\r\n\r\n').encode() + image.data
    body += f"\r\n--{boundary}--\r\n".encode()
    content_type = f"multipart/form-data; boundary={boundary}"
    if os.environ.get("HTTPS_PROXY") and os.environ.get("TYPESAFE_API_KEY"):
        return post(body, content_type)
    av = os.path.expanduser(os.environ.get("CHTABS_AV", "~/.local/bin/av"))
    worker = str(Path(__file__).with_name("vision_http.py"))
    try:
        completed = subprocess.run(
            [av, sys.executable, worker],
            input=json.dumps({"body": base64.b64encode(body).decode(), "content_type": content_type}),
            text=True, capture_output=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VisionError(f"Could not run Agent Vault: {type(exc).__name__}") from None
    try:
        result = json.loads(completed.stdout)
    except ValueError:
        raise VisionError(f"Agent Vault request failed (exit {completed.returncode}); no valid response") from None
    if completed.returncode or result.get("worker_error"):
        raise VisionError(result.get("worker_error") or f"Agent Vault exited {completed.returncode}")
    return result


def analyze(kind: str, text: str, *, tab_id: int | None = None,
            image_path: str | None = None, threshold: float = .5,
            save_screenshot: str | None = None) -> dict:
    metadata = None
    if image_path:
        raw = Path(image_path).read_bytes()
    else:
        capture = client.screenshot(tab_id)
        metadata = capture
        try:
            raw = base64.b64decode(capture["dataUrl"].split(",", 1)[1], validate=True)
        except (KeyError, ValueError, IndexError):
            raise VisionError("Invalid screenshot response from extension") from None
    image = prepare_image(raw)
    if save_screenshot:
        Path(save_screenshot).write_bytes(raw)
    question = text if kind == "ask" else f"Is there {text} in `screenshot`?"
    questions = {"presence": {"type": "noul", "instructions": question}}
    if kind == "box":
        questions["location"] = {"type": "box", "instructions": f"{text} in `screenshot`"}
    response = request_model(image, questions)
    try:
        noul = float(response["answers"]["presence"]["noul"])
        if not math.isfinite(noul) or not 0 <= noul <= 1:
            raise ValueError()
        result = dict(question=question, noul=noul, answer="yes" if noul >= threshold else "no",
                      model=response.get("model", MODEL), usage=response.get("usage"),
                      image={"width": image.width, "height": image.height})
        if kind == "box":
            result["box"] = None
            if noul >= threshold:
                location = response["answers"]["location"]
                pixels = image.map_box(location["box"])
                viewport = page = None
                if metadata:
                    dpr = float(metadata["devicePixelRatio"])
                    if not math.isfinite(dpr) or dpr <= 0:
                        raise ValueError()
                    viewport = rectangle(*(pixels[k]/dpr for k in ("left", "top", "right", "bottom")))
                    sx, sy = metadata["scrollX"], metadata["scrollY"]
                    page = rectangle(viewport["left"]+sx, viewport["top"]+sy,
                                     viewport["right"]+sx, viewport["bottom"]+sy)
                result["box"] = dict(fractions=location["box"], screenshot=pixels,
                                     viewport=viewport, page=page, confidence=location["confidence"])
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise VisionError("Invalid TypeSafe response or screenshot metadata") from None
