"""The recording backend — the fake that stands in for a real desktop."""

from __future__ import annotations

from padmap.backends import Event, RecordingBackend


def test_every_call_is_recorded_in_order() -> None:
    backend = RecordingBackend()
    backend.key_down(["ctrl", "c"])
    backend.key_up(["ctrl", "c"])
    backend.type_text("hi")
    backend.mouse_down("left")
    backend.mouse_up("left")
    backend.mouse_move(3, -2)
    backend.scroll(0, 1)
    backend.close()
    assert backend.log() == [
        "key_down ctrl+c",
        "key_up ctrl+c",
        "type hi",
        "mouse_down left",
        "mouse_up left",
        "mouse_move 3,-2",
        "scroll 0,1",
        "close",
    ]


def test_the_event_callback_sees_every_event() -> None:
    seen: list[Event] = []
    backend = RecordingBackend(on_event=seen.append)
    backend.mouse_move(1, 1)
    backend.close()
    assert [event.kind for event in seen] == ["mouse_move", "close"]


def test_event_renders_without_a_detail() -> None:
    assert str(Event("close")) == "close"
