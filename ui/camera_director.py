from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CameraBookmark:
    label: str
    category: str
    x: float
    y: float
    time: float


@dataclass
class CameraCue:
    label: str
    x: float
    y: float
    until: float


class CameraDirector:
    def __init__(self, focus_seconds: float = 3.5):
        self.focus_seconds = max(1.5, float(focus_seconds))
        self.bookmarks: list[CameraBookmark] = []
        self.current_cue: CameraCue | None = None
        self._last_timeline_signature: tuple[float, str] | None = None

    def reset(self) -> None:
        self.bookmarks.clear()
        self.current_cue = None
        self._last_timeline_signature = None

    def to_payload(self) -> list[dict[str, float | str]]:
        return [
            {
                "label": bookmark.label,
                "category": bookmark.category,
                "x": round(bookmark.x, 2),
                "y": round(bookmark.y, 2),
                "time": round(bookmark.time, 3),
            }
            for bookmark in self.bookmarks[-8:]
        ]

    def sync_from_summary(self, run_summary: dict, current_time: float, colony_center: tuple[float, float] | None) -> None:
        timeline = list((run_summary or {}).get("key_moments", []) or [])
        if not timeline or colony_center is None:
            return
        latest = timeline[-1]
        signature = (float(latest.get("time", 0.0) or 0.0), str(latest.get("summary", "")))
        if signature == self._last_timeline_signature:
            return
        self._last_timeline_signature = signature
        category = str(latest.get("category", "sim"))
        label = str(latest.get("summary", "Observer cue"))[:84]
        x, y = colony_center
        self.bookmarks.append(CameraBookmark(label=label, category=category, x=float(x), y=float(y), time=current_time))
        self.bookmarks = self.bookmarks[-10:]
        if category in {"crisis", "extinction", "faction", "migration", "birth", "scenario"}:
            self.current_cue = CameraCue(label=label, x=float(x), y=float(y), until=current_time + self.focus_seconds)

    def queue_latest_focus(self, current_time: float) -> str | None:
        if not self.bookmarks:
            return None
        bookmark = self.bookmarks[-1]
        self.current_cue = CameraCue(label=bookmark.label, x=bookmark.x, y=bookmark.y, until=current_time + self.focus_seconds)
        return bookmark.label

    def apply(self, camera, current_time: float, window_size: tuple[int, int], manual_override: bool = False) -> str | None:
        if self.current_cue is None or current_time > self.current_cue.until:
            self.current_cue = None
            return None
        if manual_override:
            return self.current_cue.label
            
        # Set targets for the camera to glide to
        camera.target_x = float(self.current_cue.x) - (float(window_size[0]) / (2.0 * max(0.01, float(camera.target_zoom))))
        camera.target_y = float(self.current_cue.y) - (float(window_size[1]) / (2.0 * max(0.01, float(camera.target_zoom))))
        camera.clamp_camera(window_size[0], window_size[1])
        return self.current_cue.label
