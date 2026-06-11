from __future__ import annotations

import asyncio

from plextui.app import BrowseState, PlexTuiApp
from plextui.models import MediaItem
from plextui.player import StreamChoice


class Raw:
    TYPE = "movie"
    title = "Raw"


def test_picker_return_preserves_highlighted_media():
    asyncio.run(run_picker_return_check())


async def run_picker_return_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
        ]
        app.browsing_stack = [BrowseState("Movies", items)]
        app.picker_media_key = "2"
        app.picker_visible = True

        app.choose_stream(StreamChoice(0, "None"), "subtitle")
        await pilot.pause(0.2)

        assert app.query_one("#media-title").content == "Movies"
        assert app.query_one("#detail-content").content.splitlines()[0] == "Second"
