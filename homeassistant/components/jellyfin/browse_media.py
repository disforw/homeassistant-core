"""Support for media browsing."""
from __future__ import annotations

import asyncio
from typing import Any

from jellyfin_apiclient_python import JellyfinClient

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType
from homeassistant.components.media_player.browse_media import BrowseMedia
from homeassistant.core import HomeAssistant

from .const import CONTENT_TYPE_MAP, MEDIA_CLASS_MAP, MEDIA_TYPE_NONE

CONTAINER_TYPES_SPECIFIC_MEDIA_CLASS: dict[str, str] = {
    MediaType.ALBUM: MediaClass.ALBUM,
    MediaType.ARTIST: MediaClass.ARTIST,
    MediaType.PLAYLIST: MediaClass.PLAYLIST,
    MediaType.SEASON: MediaClass.SEASON,
    MediaType.TVSHOW: MediaClass.TV_SHOW,
}

JF_EXPANDABLE_TYPES = ["CollectionFolder", "Series", "Season"]
JF_PLAYABLE_TYPES = ["Episode", "Movie"]
JF_SUPPORTED_LIBRARY_TYPES = ["movies", "tvshows"]

PLAYABLE_MEDIA_TYPES: list[str] = []


async def item_payload(
    hass: HomeAssistant,
    client: JellyfinClient,
    user_id: str,
    item: dict[str, Any],
) -> BrowseMedia:
    """Create response payload for a single media item."""
    title = item["Name"]
    thumbnail = str(client.jellyfin.artwork(item["Id"], "Primary", 600))

    return BrowseMedia(
        title=title,
        media_content_id=item["Id"],
        media_content_type=CONTENT_TYPE_MAP.get(item["Type"], MEDIA_TYPE_NONE),
        media_class=MEDIA_CLASS_MAP.get(item["Type"], MediaClass.DIRECTORY),
        can_play=bool(item["Type"] in JF_PLAYABLE_TYPES),
        can_expand=bool(item["Type"] in JF_EXPANDABLE_TYPES),
        children_media_class=None,
        thumbnail=thumbnail,
    )


async def build_root_response(
    hass: HomeAssistant, client: JellyfinClient, user_id: str
) -> BrowseMedia:
    """Create response payload for root folder."""
    folders = await hass.async_add_executor_job(client.jellyfin.get_media_folders)

    children = [
        await item_payload(hass, client, user_id, folder)
        for folder in folders["Items"]
        if folder["CollectionType"] in JF_SUPPORTED_LIBRARY_TYPES
    ]

    return BrowseMedia(
        media_content_id="",
        media_content_type="root",
        media_class=MediaClass.DIRECTORY,
        children_media_class=MediaClass.DIRECTORY,
        title="Jellyfin",
        can_play=False,
        can_expand=True,
        children=children,
    )


async def build_item_response(
    hass: HomeAssistant,
    client: JellyfinClient,
    user_id: str,
    media_content_type: str | None,
    media_content_id: str,
) -> BrowseMedia:
    """Create response payload for the provided media query."""
    title, media, thumbnail = await get_media_info(
        hass, client, user_id, media_content_type, media_content_id
    )

    if title is None or media is None:
        raise BrowseError(f"Media not found: {media_content_type} / {media_content_id}")

    can_play = bool(media_content_type in PLAYABLE_MEDIA_TYPES and media_content_id)
    children = await asyncio.gather(
        *(item_payload(hass, client, user_id, media_item) for media_item in media)
    )

    response = BrowseMedia(
        media_class=CONTAINER_TYPES_SPECIFIC_MEDIA_CLASS.get(
            str(media_content_type), MediaClass.DIRECTORY
        ),
        media_content_id=media_content_id,
        media_content_type=str(media_content_type),
        title=title,
        can_play=can_play,
        can_expand=True,
        children=children,
        thumbnail=thumbnail,
    )

    response.calculate_children_class()

    return response


def fetch_item(client: JellyfinClient, item_id: str) -> dict[str, Any] | None:
    """Fetch item from Jellyfin server."""
    result = client.jellyfin.get_item(item_id)

    if not result:
        return None

    item: dict[str, Any] = result
    return item


def fetch_items(
    client: JellyfinClient,
    params: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Fetch items from Jellyfin server."""
    result = client.jellyfin.user_items(params=params)

    if not result or "Items" not in result or len(result["Items"]) < 1:
        return None

    items: list[dict[str, Any]] = result["Items"]

    return [
        item
        for item in items
        if item["Type"] not in JF_EXPANDABLE_TYPES
        or (item["Type"] in JF_EXPANDABLE_TYPES and item.get("ChildCount", 1) > 0)
    ]


async def get_media_info(
    hass: HomeAssistant,
    client: JellyfinClient,
    user_id: str,
    media_content_type: str | None,
    media_content_id: str,
) -> tuple[str | None, list[dict[str, Any]] | None, str | None]:
    """Fetch media info."""
    thumbnail: str | None = None
    title: str | None = None
    media: list[dict[str, Any]] | None = None

    item = await hass.async_add_executor_job(fetch_item, client, media_content_id)

    if item is None:
        return None, None, None

    title = item["Name"]
    thumbnail = client.jellyfin.artwork(media_content_id, "Primary", 600)

    if item["Type"] in JF_EXPANDABLE_TYPES:
        media = await hass.async_add_executor_job(
            fetch_items, client, {"parentId": media_content_id, "fields": "childCount"}
        )

    return title, media, thumbnail
