import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

from app.core.exceptions import InvalidSourceError, UpstreamError

MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
REQUEST_TIMEOUT_SECONDS = 20


async def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidSourceError("Only public HTTP and HTTPS URLs can be ingested")
    if parsed.username or parsed.password:
        raise InvalidSourceError("URLs containing credentials are not allowed")
    try:
        try:
            addresses = [ipaddress.ip_address(parsed.hostname)]
        except ValueError:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = [ipaddress.ip_address(record[4][0].split("%", 1)[0]) for record in records]
    except (OSError, ValueError) as exc:
        raise UpstreamError("The supplied URL hostname could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise InvalidSourceError("URLs must resolve only to public IP addresses")


async def extract_url(url: str) -> tuple[str, str]:
    current_url = url
    page_html = ""
    final_url = url
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "AIKnowledgeInbox/0.1"},
        ) as client:
            for redirect_count in range(MAX_REDIRECTS + 1):
                await _validate_public_url(current_url)
                async with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count == MAX_REDIRECTS:
                            raise UpstreamError("The supplied URL redirected too many times")
                        current_url = urljoin(str(response.url), location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in {"text/html", "application/xhtml+xml"}:
                        raise UpstreamError("The supplied URL did not return an HTML page")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                        raise UpstreamError("The webpage exceeds the 3 MB extraction limit")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise UpstreamError("The webpage exceeds the 3 MB extraction limit")
                    page_html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                    final_url = str(response.url)
                    break
    except httpx.HTTPError as exc:
        raise UpstreamError("Could not fetch the supplied URL") from exc
    except (TypeError, ValueError) as exc:
        raise UpstreamError("The webpage response could not be read") from exc
    content = trafilatura.extract(page_html, url=final_url, include_comments=False)
    if not content:
        raise UpstreamError("No readable page content was found at the supplied URL")
    title = trafilatura.extract_metadata(page_html)
    return (title.title if title and title.title else final_url, content)
