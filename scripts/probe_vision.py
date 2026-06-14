"""One-off probe: does the configured MaaS endpoint accept image input?

Reads creds from eventbuddy.config.settings (no secrets printed). Steps:
  1. List models the endpoint serves (so we can see the exact Gemma id + any vision variant).
  2. Render a small PNG containing known text, base64 it, and ask the model to read it
     via the OpenAI multimodal `content` array.
  3. Report the reply, or the error verbatim.

Pick the model with VISION_MODEL=<id> (defaults to settings.llm_chat_model).
Run:  venv/bin/python scripts/probe_vision.py
"""
from __future__ import annotations

import base64
import io
import os
import sys

from openai import OpenAI

from eventbuddy.config import settings

TARGET = os.environ.get("VISION_MODEL", settings.llm_chat_model)
SECRET_TEXT = "VISION-OK-4271"


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    import struct
    import zlib

    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def solid_png(rgb: tuple[int, int, int], size: int = 96) -> bytes:
    """A solid-color RGB PNG, pure stdlib (no Pillow). The model can only name the
    color by actually decoding the pixels — so a correct answer proves real vision."""
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + bytes(rgb) * size  # filter byte 0 + pixels
    raw = row * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def main() -> int:
    if not settings.agentbase_llm_base_url or not settings.agentbase_llm_api_key:
        print("ABORT: agentbase_llm_base_url / agentbase_llm_api_key not set in .env")
        return 2

    print(f"base_url = {settings.agentbase_llm_base_url}")
    print(f"target model = {TARGET}\n")

    client = OpenAI(
        base_url=settings.agentbase_llm_base_url,
        api_key=settings.agentbase_llm_api_key,
    )

    # 1) What does the endpoint actually serve?
    print("--- models served ---")
    try:
        for m in client.models.list().data:
            print(f"  {m.id}")
    except Exception as e:  # noqa: BLE001
        print(f"  (models.list failed: {type(e).__name__}: {e})")
    print()

    # 2) Send a solid-color image and ask the model to name the color. A correct,
    #    image-specific answer proves the pixels actually reached and were decoded by
    #    the model (not silently dropped).
    color_name, rgb = "green", (16, 180, 64)
    data_uri = "data:image/png;base64," + base64.b64encode(solid_png(rgb)).decode()
    print(f"--- vision request (expecting '{color_name}') ---")
    try:
        resp = client.chat.completions.create(
            model=TARGET,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What is the dominant color of this image? Answer with one word.",
                        },
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        )
        reply = resp.choices[0].message.content
        print(f"reply: {reply!r}")
        ok = reply and color_name in reply.lower()
        print()
        if ok:
            print(f"RESULT: VISION WORKS — model correctly identified the image as {color_name}.")
        else:
            print("RESULT: endpoint accepted the image but the color answer was off — "
                  "inspect the reply above before concluding.")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {type(e).__name__}: {e}")
        print()
        print("RESULT: endpoint REJECTED the image request. Either this model id has no "
              "vision variant, or the MaaS deployment doesn't accept image content.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
