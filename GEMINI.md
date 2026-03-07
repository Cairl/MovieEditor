# MovieEditor Project Context

## Project Overview
MovieEditor is a Python-based interactive Terminal User Interface (TUI) tool for video processing, leveraging FFmpeg. It allows users to configure video encoding parameters, manage audio streams, and handle subtitles through an intuitive menu system with real-time FFmpeg command previews.

### Main Technologies
- **Language**: Python 3.12+
- **Core Engine**: FFmpeg (requires `ffmpeg` and `ffprobe` in system PATH)
- **GUI Components**: `tkinter` (for file selection dialogs)
- **Platform**: Windows-optimized (uses `msvcrt` for keyboard input)

### Key Features
- **Video Settings**: H.264/H.265 encoding, resolution scaling, time clipping, and cropping.
- **Audio Management**: Multi-stream selection and various codec supports (copy, aac, mp3, ac3, flac).
- **Subtitle Support**: Built-in stream management, external file import (.srt, .ass, etc.), and hard-burning.
- **Real-time Preview**: Live visualization of the generated FFmpeg command.

## Building and Running

### Prerequisites
1.  **Python 3.12+**: Ensure Python is installed and accessible via `python` or `python3`.
2.  **FFmpeg**: Must be installed and added to the system's `PATH`. Verify with `ffmpeg -version`.

### Execution
To start the application:
```bash
python movie_editor.py
```
You can also pass a file path directly:
```bash
python movie_editor.py "path/to/video.mp4"
```

### Supported Formats
- **Input**: .mp4, .mkv, .mov, .avi, .flv, .wmv
- **Subtitles**: .srt, .ass, .ssa, .vtt, .sup
- **Output**: Always outputs as MP4 with the prefix `[FF] `.

## Development Conventions

### Architecture
The project is primarily contained within `movie_editor.py`, structured into:
- **UI Rendering**: ANSI-based terminal styling and menu logic.
- **FFmpeg Interaction**: Media probing and command construction.
- **Input Handling**: Synchronous keyboard navigation using `msvcrt`.
- **Process Management**: Active tracking and cleanup of child processes (FFmpeg).

### Coding Standards
- **Encoding**: Uses UTF-8 for all standard I/O operations.
- **Safety**: Employs `atexit` and Windows console handlers to ensure FFmpeg processes are terminated on exit.
- **Performance**: Uses FFmpeg's `-progress pipe:1` for real-time tracking without excessive overhead.
- **Metadata**: Preserves original metadata and chapters while tagging outputs with `handler_name=@Cairl`.

### Key Commands for Development
- **Run**: `python movie_editor.py`
- **Lint/Format**: No explicit linter configured, but follow standard PEP 8 style.
- **Tests**: No automated tests currently exist; manual verification via the TUI is required.
