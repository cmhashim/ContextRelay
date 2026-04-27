"""
ContextRelay Python SDK client.
"""

import json
import time
from typing import Any, Callable, Dict, Optional

import requests


MANAGED_URL = "https://api.contextrelay.dev/v1"


class ContextRelay:
    """
    Minimal client for the ContextRelay edge API.

    Args:
        base_url: Base URL of the Cloudflare Worker.
                  Defaults to the managed cloud instance.
        api_key:  API key for the managed cloud (cr_live_...).
                  Omit only for self-hosted open deployments.
        timeout:  HTTP timeout in seconds (default: 30).
    """

    def __init__(
        self,
        base_url: str = MANAGED_URL,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers: Dict[str, str] = {}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def push(
        self,
        data: str,
        channel: Optional[str] = None,
        encrypted: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Upload a payload to the edge and return a URL pointer.

        Args:
            data:      Any text, JSON string, or Markdown — up to 25 MB.
            channel:   Optional channel name. If set, subscribers to this
                       channel (via `.subscribe()`) receive the pointer
                       URL immediately over WebSocket.
            encrypted: If True, encrypt the payload locally with a fresh
                       Fernet key. The key is appended to the returned
                       URL as `#key=...` — never sent to the server.
            metadata:  Optional dict of lightweight headers (e.g.
                       `{"summary": "db schema", "size_kb": 50}`).
                       Readable via `.peek(url)` without downloading the
                       full payload. Stored as plaintext on the server
                       even when `encrypted=True` — do not put secrets
                       in metadata.

        Returns:
            If `encrypted=False`: the pointer URL, valid for 24 hours.
            If `encrypted=True`:  the pointer URL with `#key=<fernet_key>`
                                  appended.
        """
        if encrypted:
            try:
                from cryptography.fernet import Fernet
            except ImportError as e:
                raise ImportError(
                    "encrypted=True requires the 'cryptography' package. "
                    "Install with: pip install cryptography"
                ) from e

            key = Fernet.generate_key()
            payload_to_send = Fernet(key).encrypt(data.encode("utf-8")).decode("ascii")
            key_str: Optional[str] = key.decode("ascii")
        else:
            payload_to_send = data
            key_str = None

        body: Dict[str, Any] = {"data": payload_to_send}
        if channel is not None:
            body["channel"] = channel
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise TypeError("metadata must be a dict")
            body["metadata"] = metadata

        response = requests.post(
            f"{self.base_url}/push",
            json=body,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        base_url = response.json()["url"]

        if key_str is not None:
            return f"{base_url}#key={key_str}"
        return base_url

    def pull(self, url: str) -> str:
        """
        Retrieve a payload from a ContextRelay URL pointer.

        Unwraps the Phase-5 `{data, metadata}` storage envelope. Legacy
        raw entries (pre-Phase-5) are returned verbatim. If the URL
        carries a `#key=...` fragment, the fragment is stripped locally
        and the data is Fernet-decrypted after unwrapping.

        Raises:
            requests.HTTPError: If the URL has expired or does not exist.
            ValueError:         If a `#key=` fragment is present but the
                                ciphertext cannot be decrypted. Message:
                                "Failed to decrypt: Invalid or missing key".
        """
        if "#key=" in url:
            base_url, _, fragment = url.partition("#")
            key_str = fragment[len("key="):]
            if not key_str:
                raise ValueError("Failed to decrypt: Invalid or missing key")
        else:
            base_url = url
            key_str = None

        response = requests.get(base_url, headers=self._headers, timeout=self.timeout)
        response.raise_for_status()
        raw = response.text

        # Unwrap the Phase-5 envelope. Fall back to raw for legacy entries
        # or any body that doesn't parse as our wrapper shape.
        payload = raw
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if (
            isinstance(parsed, dict)
            and isinstance(parsed.get("data"), str)
            and isinstance(parsed.get("metadata", {}), dict)
        ):
            payload = parsed["data"]

        if key_str is None:
            return payload

        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as e:
            raise ImportError(
                "Decrypting a '#key=' URL requires the 'cryptography' "
                "package. Install with: pip install cryptography"
            ) from e

        try:
            plaintext = Fernet(key_str.encode("ascii")).decrypt(
                payload.encode("ascii")
            )
        except (InvalidToken, ValueError, TypeError) as e:
            raise ValueError(
                "Failed to decrypt: Invalid or missing key"
            ) from e

        return plaintext.decode("utf-8")

    def peek(self, url: str) -> Dict[str, Any]:
        """
        Fetch only the metadata header for a ContextRelay pointer URL.

        This hits `GET /peek/:id` and returns the small plaintext
        metadata object without downloading (or decrypting) the full
        payload. Use it to decide whether `.pull()` is worth the
        bandwidth or context window.

        Args:
            url: A ContextRelay pointer URL, with or without a `#key=`
                 fragment. Must contain `/pull/<uuid>`.

        Returns:
            The metadata dict. Empty dict `{}` if the producer did not
            attach metadata or if the entry is a pre-Phase-5 legacy raw
            payload.

        Raises:
            ValueError:         If the URL is not a ContextRelay pointer URL.
            requests.HTTPError: If the URL has expired or does not exist.
        """
        base_url = url.split("#", 1)[0]
        if "/pull/" not in base_url:
            raise ValueError(
                "Not a ContextRelay pointer URL — expected '/pull/<uuid>' in the path"
            )
        prefix, _, uuid = base_url.partition("/pull/")
        peek_url = f"{prefix}/peek/{uuid}"

        response = requests.get(peek_url, headers=self._headers, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, dict) else {}

    def subscribe(
        self,
        channel: str,
        callback: Callable[[str], None],
        max_reconnect_delay: float = 60.0,
    ) -> None:
        """
        Subscribe to a channel and invoke `callback(url)` for each pointer
        URL broadcast to that channel.

        Blocks forever. Auto-reconnects with exponential backoff
        (1s → 2s → 4s → ... capped at `max_reconnect_delay`).
        Ping/pong keepalive runs every 30s to detect silent drops.

        Run in a background thread for non-blocking use:

            import threading
            t = threading.Thread(target=hub.subscribe, args=(channel, cb),
                                 daemon=True)
            t.start()
        """
        try:
            from websocket import WebSocketApp  # type: ignore
        except ImportError as e:
            raise ImportError(
                "subscribe() requires websocket-client. "
                "Install with: pip install websocket-client"
            ) from e

        ws_url = self._ws_url(channel)
        delay = [1.0]

        def on_open(_ws):
            delay[0] = 1.0

        def on_message(_ws, raw):
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return
            if isinstance(msg, dict) and "url" in msg:
                try:
                    callback(self._rewrite_to_gateway(msg["url"]))
                except Exception:
                    pass

        while True:
            ws = WebSocketApp(
                ws_url,
                header=self._headers or None,
                on_open=on_open,
                on_message=on_message,
            )
            try:
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except KeyboardInterrupt:
                break
            time.sleep(delay[0])
            delay[0] = min(delay[0] * 2, max_reconnect_delay)

    def _rewrite_to_gateway(self, url: str) -> str:
        """Rewrite an edge URL to go through the configured gateway.

        When a WebSocket message arrives from the edge, it carries the edge's
        own workers.dev URL. If this client is pointed at a gateway (e.g.
        api.contextrelay.dev/v1), rewrite the URL so pull() goes through the
        gateway too — keeping all traffic metered and the workers.dev URL
        unexposed to callers.
        """
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        our = urlparse(self.base_url)

        # Already going through our host — nothing to rewrite.
        if parsed.netloc == our.netloc:
            return url

        # Edge URL has a different host. Rebuild using our host + path prefix.
        # e.g. base_url = "https://api.contextrelay.dev/v1"
        #      edge url  = "https://workers.dev/pull/{id}"
        #      result    = "https://api.contextrelay.dev/v1/pull/{id}"
        base_path = our.path.rstrip("/")   # "/v1"
        new_path = base_path + parsed.path  # "/v1/pull/{id}"
        return urlunparse((our.scheme, our.netloc, new_path, "", "", ""))

    def _ws_url(self, channel: str) -> str:
        if self.base_url.startswith("https://"):
            scheme = "wss://"
            host = self.base_url[len("https://"):]
        elif self.base_url.startswith("http://"):
            scheme = "ws://"
            host = self.base_url[len("http://"):]
        else:
            scheme = "wss://"
            host = self.base_url
        return f"{scheme}{host}/ws/{channel}"
