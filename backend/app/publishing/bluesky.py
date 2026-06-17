"""BlueskyPublisher — AT Protocol via the `atproto` Python SDK.

Auth: App Password (not OAuth). The SDK's `Client.login(handle, password)`
issues a short-lived session; we don't cache it — fresh login per publish.
This trades a few hundred ms for not having to manage refresh of session
tokens that expire mid-job.

Posting:
- Text-only via `client.send_post(text)`.
- 1-4 images via `client.send_images(text, images=[(blob, alt), ...])`.
- Bluesky has no document/carousel construct, so anything past 4 images is
  truncated (the orchestrator pre-warns on this at approve time via
  `max_images=4`).
- Hashtags: unlike Mastodon/Instagram (which parse `#tags` from the text
  server-side) and LinkedIn (auto-links them), atproto renders `#tags` as plain
  grey text unless they're attached as `app.bsky.richtext.facet#tag` facets. We
  reparse the commentary through `client_utils.TextBuilder` (`_build_richtext`)
  so the tags the generator produced are real, clickable/searchable.

Char limit: 300 grapheme clusters, enforced server-side. We gate at the
orchestrator before calling in; if a draft body exceeds 300, the target
moves to `failed` with a clear error.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt
from app.models import BlueskyAccount, GeneratedAsset, Post
from app.models.base import Platform
from app.publishing.base import (
    PermanentPublishError,
    PublishResult,
    Publisher,
    TransientPublishError,
    register,
)
from app.rendering import storage

log = structlog.get_logger()

# Hard server-side cap on Bluesky posts (grapheme clusters; we approximate with
# Python string len which slightly overcounts emojis — safe direction).
BLUESKY_CHAR_LIMIT = 300

# Image cap per post.
BLUESKY_MAX_IMAGES = 4

# Hashtag token. On atproto a `#tag` is plain grey text unless it's attached as
# an `app.bsky.richtext.facet#tag` facet (byte-offset range). We parse the
# commentary the generator already produced (lowercase `#tags` at the end) and
# rebuild it through TextBuilder so the tags are real, clickable/searchable.
# `\w` (unicode) matches our generated tags; pure-numeric tokens are skipped so
# "#1" stays plain text rather than producing an invalid tag facet.
_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def _build_richtext(text: str) -> tuple[Any, bool]:
    """Return (TextBuilder, has_tags). When no real hashtag is present, has_tags
    is False and the caller should send the plain string (cheaper, and keeps the
    no-tag path byte-for-byte identical to before facets existed)."""
    from atproto import client_utils  # type: ignore[import-untyped]

    builder = client_utils.TextBuilder()
    pos = 0
    has_tags = False
    for m in _HASHTAG_RE.finditer(text):
        tag_value = m.group(1)
        if tag_value.isdigit():
            continue  # not a real hashtag — leave it in the surrounding text run
        if m.start() > pos:
            builder.text(text[pos : m.start()])
        builder.tag(m.group(0), tag_value)  # display "#ai", facet value "ai"
        pos = m.end()
        has_tags = True
    if has_tags and pos < len(text):
        builder.text(text[pos:])
    return builder, has_tags


async def _download_png(public_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        r = await client.get(public_url)
    if r.status_code != 200:
        raise PermanentPublishError(
            f"asset download failed: {r.status_code} {public_url}"
        )
    return r.content


def _build_external_urn(post_ref: Any) -> str:
    """Format the at:// URI Bluesky returns into a canonical external_urn.
    SDK returns a CreateRecordResponse with .uri = at://did/coll/rkey."""
    uri = getattr(post_ref, "uri", None) or str(post_ref)
    return uri


@register
class BlueskyPublisher(Publisher):
    platform = Platform.bluesky
    char_limit = BLUESKY_CHAR_LIMIT
    max_images = BLUESKY_MAX_IMAGES
    supports_documents = False

    async def publish(
        self,
        *,
        session: AsyncSession,  # noqa: ARG002 — kept for ABC parity
        post: Post,
        account: BlueskyAccount,
        commentary: str,
        assets: list[GeneratedAsset],
    ) -> PublishResult:
        # atproto SDK is sync. Push to a thread so we don't block the event loop.
        from atproto import Client  # type: ignore[import-untyped]

        handle = account.handle
        app_password = decrypt(account.app_password)

        # Truncate carousel down to platform cap — orchestrator already
        # warned the operator. Order preserved: slide 1, slide 2, ...
        attach = assets[: BLUESKY_MAX_IMAGES]
        image_blobs: list[tuple[bytes, str]] = []
        for a in attach:
            png = await _download_png(storage.public_url(a.image_path))
            # Alt text: post hook is the safest one-liner Bluesky a11y signal.
            alt = (post.hook or "Image")[:300]
            image_blobs.append((png, alt))

        # Promote `#tags` in the text to real Bluesky facets. Falls back to the
        # plain string when there are no tags (unchanged behavior).
        rich, has_tags = _build_richtext(commentary)
        text_arg: Any = rich if has_tags else commentary

        def _do_publish() -> tuple[str, dict[str, Any]]:
            client = Client()
            client.login(handle, app_password)
            try:
                if not image_blobs:
                    resp = client.send_post(text=text_arg)
                    raw = {"text": commentary, "images": 0, "faceted_tags": has_tags}
                else:
                    # send_images signature: text, images=[(bytes, alt), ...]
                    resp = client.send_images(
                        text=text_arg,
                        images=[png for png, _ in image_blobs],
                        image_alts=[alt for _, alt in image_blobs],
                    )
                    raw = {
                        "text": commentary,
                        "images": len(image_blobs),
                        "faceted_tags": has_tags,
                    }
                return _build_external_urn(resp), raw
            finally:
                # SDK does not expose explicit logout; sessions are short-lived.
                pass

        try:
            urn, raw = await asyncio.to_thread(_do_publish)
        except Exception as e:
            msg = str(e)
            # Heuristic classification: atproto SDK raises a single AtProtocolError
            # type for everything from auth failures to rate limits. We use message
            # substrings (best available signal until SDK gets typed errors).
            lowered = msg.lower()
            if "invalid" in lowered and ("password" in lowered or "credential" in lowered or "identifier" in lowered):
                raise PermanentPublishError(f"bluesky auth: {msg[:300]}") from e
            if "rate" in lowered or "429" in lowered or "timeout" in lowered:
                raise TransientPublishError(f"bluesky transient: {msg[:300]}") from e
            if "too long" in lowered or "exceeds" in lowered:
                raise PermanentPublishError(f"bluesky payload: {msg[:300]}") from e
            # Default: treat unknown as transient so the orchestrator retries once
            # — safer than swallowing a real outage as permanent.
            raise TransientPublishError(f"bluesky: {msg[:300]}") from e

        return PublishResult(external_urn=urn, raw_request=raw)


# --- Account loader ---


async def load_account(
    session: AsyncSession, post: Post  # noqa: ARG001
) -> BlueskyAccount:
    from sqlalchemy import select

    stmt = (
        select(BlueskyAccount)
        .order_by(BlueskyAccount.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise PermanentPublishError("no connected Bluesky account")
    return row
