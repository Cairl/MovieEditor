"""
Progress management for series mode batch processing.
Saves/loads progress to .movieeditor_progress.json in the output directory.
"""

import json
import os
from datetime import datetime


PROGRESS_FILE = ".movieeditor_progress.json"


class ProgressManager:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.filepath = os.path.join(output_dir, PROGRESS_FILE)

    def load(self) -> dict | None:
        """Load existing progress file. Returns None if not found or on error."""
        if not os.path.exists(self.filepath):
            return None
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, data: dict) -> None:
        """Persist data to the progress file."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def save(self, batch_id: str, input_paths: list[str], completed: list[int], settings: dict) -> None:
        """Save progress to file."""
        self._write({
            "batch_id": batch_id,
            "input_paths": input_paths,
            "completed": completed,
            "output_dir": self.output_dir,
            "settings": settings,
        })

    def mark_completed(self, index: int) -> None:
        """Mark an episode index as completed and persist."""
        data = self.load()
        if data is None:
            return
        completed = data.get("completed", [])
        if index not in completed:
            completed.append(index)
        data["completed"] = completed
        self._write(data)

    def get_completed(self) -> list[int]:
        """Get list of completed episode indices."""
        data = self.load()
        if data is None:
            return []
        return data.get("completed", [])

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
