"""Private stdin/stdout HTTP worker, also executable under Agent Vault."""
from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request


class VisionError(Exception):
    pass


def post(body: bytes, content_type: str) -> dict:
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key or not os.environ.get("HTTPS_PROXY"):
        raise VisionError("Agent Vault must provide HTTPS_PROXY and TYPESAFE_API_KEY")
    request = urllib.request.Request(
        "https://api.typesafe.ai/v1/systemone", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "TypeSafe-Danger-Zone-Images": "true", "Content-Type": content_type},
    )
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or
                                        os.environ.get("REQUESTS_CA_BUNDLE"))
    try:
        with urllib.request.urlopen(request, context=context, timeout=90) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").replace(key, "[redacted]")
        raise VisionError(f"TypeSafe HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise VisionError(f"TypeSafe request failed: {str(exc).replace(key, '[redacted]')}") from None


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        print(json.dumps(post(base64.b64decode(data["body"]), data["content_type"])))
    except (VisionError, ValueError, KeyError) as exc:
        print(json.dumps({"worker_error": str(exc)}))
        sys.exit(5)
