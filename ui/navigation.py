# 导航键读取、可选索引计算
import time
import msvcrt
from typing import Optional

from ui.console import _console_read_key, _check_console_ctrl, ANSI_ESCAPE, TITLE_MARKER, CONTEXT_MARKER, _is_separator, _shutdown_requested

def read_navigation_key() -> str:
    while True:
        # 检查并消耗控制台 Ctrl+C 事件（防止它触发 Python 的 KeyboardInterrupt）
        _check_console_ctrl()

        # 响应外部退出信号
        if _shutdown_requested.is_set():
            return 'BACKSPACE'

        # 非阻塞读取
        key, is_shift = _console_read_key()
        if key is None:
            # 没有按键，短暂等待后重试
            time.sleep(0.01)
            continue

        # 忽略 Ctrl+C
        if key == b'\x03':
            continue

        if key in (b'\xe0', b'\x00'):
            # 扩展键，需要再读一个字节
            ext, _ = _console_read_key()
            if ext is None:
                continue
            if ext == b'H':
                return 'SHIFT_UP' if is_shift else 'UP'
            if ext == b'P':
                return 'SHIFT_DOWN' if is_shift else 'DOWN'
            if ext == b'K':
                return 'SHIFT_LEFT' if is_shift else 'LEFT'
            if ext == b'M':
                return 'SHIFT_RIGHT' if is_shift else 'RIGHT'
        elif key in (b'\r', b'\n'):
            return 'ENTER'
        elif key == b'\x08':
            return 'BACKSPACE'


def clear_keyboard_buffer() -> None:
    try:
        while msvcrt.kbhit():
            try:
                msvcrt.getch()
            except OSError:
                break
    except OSError:
        pass




def get_selectable_indices(lines: list[str]) -> list[int]:
    selectable = []
    for i, line in enumerate(lines):
        plain = ANSI_ESCAPE.sub('', line)
        stripped = plain.strip()
        is_empty = stripped == ''
        is_separator = _is_separator(stripped)
        is_header = plain.startswith(TITLE_MARKER)
        is_context = plain.startswith(CONTEXT_MARKER)
        if not is_empty and not is_separator and not is_header and not is_context:
            selectable.append(i)
    return selectable


def get_next_selectable(lines: list[str], current_index: int, direction: int) -> int:
    selectable = get_selectable_indices(lines)
    if not selectable:
        return current_index
    if current_index not in selectable:
        return selectable[0] if direction > 0 else selectable[-1]
    current_pos = selectable.index(current_index)
    return selectable[(current_pos + direction) % len(selectable)]


def normalize_selected_index(lines: list[str], selected_index: Optional[int]) -> Optional[int]:
    selectable = get_selectable_indices(lines)
    if not selectable:
        return None
    if selected_index in selectable:
        return selected_index
    return selectable[0]


