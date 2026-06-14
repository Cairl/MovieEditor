# 控制台底层：键盘读取、光标控制、ANSI 常量、子进程管理
import io
import sys
import re
import ctypes
import msvcrt
import threading
import subprocess
from typing import Optional

if sys.platform == "win32":
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
CURSOR_HOME = '\033[H'

ACTIVE_CHILD_PROCESSES = set()
ACTIVE_CHILD_LOCK = threading.Lock()

# 鍏ㄥ眬閫€鍑烘爣蹇楋紝鐢?Ctrl+C 淇″彿澶勭悊鍣ㄨ�??
_shutdown_requested = threading.Event()

# 闈為樆濉為敭鐩樿鍙栵紙涓嶄娇鐢ㄧ嫭绔嬬嚎绋嬶級
def _console_has_input() -> bool:
    if sys.platform == 'win32':
        return msvcrt.kbhit()
    return False


def _console_read_key() -> tuple[Optional[bytes], bool]:
    if sys.platform == 'win32':
        if msvcrt.kbhit():
            key = msvcrt.getch()
            is_shift = bool(ctypes.windll.user32.GetKeyState(0x10) & 0x8000)
            return key, is_shift
    return None, False


def _check_console_ctrl() -> bool:
    if sys.platform == 'win32':
        try:
            handle = ctypes.windll.kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
            events = ctypes.c_ulong()
            if ctypes.windll.kernel32.PeekConsoleInputW(handle, None, 0, ctypes.byref(events)):
                if events.value > 0:
                    class KEY_EVENT_RECORD(ctypes.Structure):
                        _fields_ = [
                            ("bKeyDown", ctypes.c_long),
                            ("wRepeatCount", ctypes.c_short),
                            ("wVirtualKeyCode", ctypes.c_short),
                            ("wVirtualScanCode", ctypes.c_short),
                            ("uChar", ctypes.c_ubyte * 4),
                            ("dwControlKeyState", ctypes.c_long)
                        ]
                    class INPUT_RECORD(ctypes.Structure):
                        _fields_ = [
                            ("EventType", ctypes.c_short),
                            ("Event", KEY_EVENT_RECORD)
                        ]
                    record = INPUT_RECORD()
                    peeked = ctypes.c_ulong()
                    # Peek (non-destructive) first �� don't consume non-Ctrl+C events
                    if ctypes.windll.kernel32.PeekConsoleInputW(handle, ctypes.byref(record), 1, ctypes.byref(peeked)):
                        if peeked.value > 0 and record.EventType == 1:
                            vk = record.Event.wVirtualKeyCode
                            ctrl = record.Event.dwControlKeyState
                            if vk == 0x43 and (ctrl & 0x0008):  # Ctrl+C
                                # Consume only if it IS Ctrl+C
                                ctypes.windll.kernel32.ReadConsoleInputW(handle, ctypes.byref(record), 1, ctypes.byref(peeked))
                                return True
        except OSError:
            pass
    return False


MAX_DISPLAY_NAME_LEN = 40

TITLE_MARKER = "__TITLE__ "
CONTEXT_MARKER = "__CTX__ "

def _is_separator(text: str) -> bool:
    return len(text) > 0 and len(set(text)) == 1 and text[0] in ('\u2500', '-', '=')

UI_COLORS = {
    "reset": "[0m",
    "accent": "[38;2;137;180;250m",
    "title": "[38;2;249;226;175m",
    "muted": "[38;2;108;112;134m",
    "selected_row": "[48;2;69;71;90m",
    "green": "[38;2;166;227;161m",
}
UI_ICONS = {
    "focus": "\u276f",
}
MENU_LABEL_WIDTH = 28

def register_child_process(process: subprocess.Popen) -> None:
    with ACTIVE_CHILD_LOCK:
        ACTIVE_CHILD_PROCESSES.add(process)


def unregister_child_process(process: subprocess.Popen) -> None:
    with ACTIVE_CHILD_LOCK:
        ACTIVE_CHILD_PROCESSES.discard(process)


def terminate_active_children() -> None:
    with ACTIVE_CHILD_LOCK:
        processes = list(ACTIVE_CHILD_PROCESSES)
    for action in (subprocess.Popen.terminate, subprocess.Popen.kill):
        for process in processes:
            try:
                if process.poll() is None:
                    action(process)
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            except OSError:
                pass


def hide_cursor() -> None:
    print('\033[?25l', end='', flush=True)


def show_cursor() -> None:
    print('\033[?25h', end='', flush=True)
