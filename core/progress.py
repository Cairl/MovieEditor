"""
Progress management for series mode batch processing.
Saves/loads progress to .movieeditor_progress.json in the input directory.
Tracks per-episode status: pending / running / completed / failed.
"""

import json
import os
from datetime import datetime

PROGRESS_FILE = ".movieeditor_progress.json"


class ProgressManager:
    def __init__(self, input_dir: str):
        self.input_dir = input_dir
        self.filepath = os.path.join(input_dir, PROGRESS_FILE)

    def load(self) -> dict | None:
        """Load existing progress file. Returns None if not found or on error."""
        if not os.path.exists(self.filepath):
            return None
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate old format: {"completed": [0, 1, 2]} → new episode-based format
            if "completed" in data and "episodes" not in data:
                completed_indices = set(data["completed"])
                total = len(data.get("input_paths", []))
                episodes = [
                    {"index": i, "status": "completed" if i in completed_indices else "pending"}
                    for i in range(total)
                ]
                data["episodes"] = episodes
                del data["completed"]
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, data: dict) -> None:
        """Persist data to the progress file."""
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def save(self, batch_id: str, input_paths: list[str], output_dir: str, episode_names: list[str], settings: dict | None = None) -> None:
        """Create a new progress file with all episodes as pending."""
        episodes = [{"index": i, "status": "pending"} for i in range(len(input_paths))]
        data = {
            "batch_id": batch_id,
            "input_dir": self.input_dir,
            "output_dir": output_dir,
            "input_paths": input_paths,
            "episode_names": episode_names,
            "episodes": episodes,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if settings is not None:
            data["settings"] = settings
        self._write(data)

    def _update_status(self, index: int, status: str) -> None:
        """Set the status of a specific episode."""
        data = self.load()
        if data is None:
            return
        for ep in data.get("episodes", []):
            if ep["index"] == index:
                ep["status"] = status
                break
        self._write(data)

    def mark_running(self, index: int) -> None:
        self._update_status(index, "running")

    def mark_completed(self, index: int) -> None:
        self._update_status(index, "completed")

    def mark_failed(self, index: int) -> None:
        self._update_status(index, "failed")

    def get_completed(self) -> list[int]:
        """Get list of completed episode indices."""
        data = self.load()
        if data is None:
            return []
        return [ep["index"] for ep in data.get("episodes", []) if ep["status"] == "completed"]

    def get_remaining(self) -> list[int]:
        """Get indices of episodes that are not completed."""
        data = self.load()
        if data is None:
            return []
        return [ep["index"] for ep in data.get("episodes", []) if ep["status"] != "completed"]

    def get_output_dir(self) -> str | None:
        """Return the stored output directory path."""
        data = self.load()
        if data is None:
            return None
        return data.get("output_dir")

    def get_total(self) -> int:
        """Return total episode count."""
        data = self.load()
        if data is None:
            return 0
        return len(data.get("episodes", []))

    def get_episode_names(self) -> list[str]:
        """Return stored episode display names."""
        data = self.load()
        if data is None:
            return []
        return data.get("episode_names", [])

    def get_settings(self) -> dict | None:
        """Return stored settings snapshot."""
        data = self.load()
        if data is None:
            return None
        return data.get("settings")

    def get_batch_id(self) -> str | None:
        """Return the stored batch timestamp."""
        data = self.load()
        if data is None:
            return None
        return data.get("batch_id")

    def get_input_paths(self) -> list[str]:
        """Return the stored input file paths."""
        data = self.load()
        if data is None:
            return []
        return data.get("input_paths", [])

    def clear(self) -> None:
        """Delete the progress file."""
        if os.path.exists(self.filepath):
            try:
                os.remove(self.filepath)
            except OSError:
                pass

    def has_progress(self) -> bool:
        """Check if a progress file exists."""
        return os.path.exists(self.filepath)
