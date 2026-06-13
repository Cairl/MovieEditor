# 显示层：菜单渲染、文本格式化、预览框
import re
import sys
import shutil
import unicodedata
from enum import Enum
from typing import Optional

from ui.console import ANSI_ESCAPE, CURSOR_HOME, UI_COLORS, UI_ICONS, MENU_LABEL_WIDTH, TITLE_MARKER, CONTEXT_MARKER, _is_separator, hide_cursor, _shutdown_requested
from core.helpers import truncate_name
from ui.navigation import get_selectable_indices, get_next_selectable, normalize_selected_index, read_navigation_key

LAST_MENU_LINES = None

def reset_menu_cache() -> None:
    """Reset the incremental render cache so the next menu render is a full redraw."""
    global LAST_MENU_LINES
    LAST_MENU_LINES = None

def get_display_width(text: str) -> int:
    # Strip ANSI escape sequences before calculating width
    clean_text = ANSI_ESCAPE.sub('', str(text))
    width = 0
    for ch in clean_text:
        width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return width


MENU_SEPARATOR = "─" * 52


def menu_section(title: str) -> str:
    clean = str(title).replace('\n', ' ').strip()
    return f"{TITLE_MARKER}{clean}"


HINT_SEP = '\x1f'

def with_ffmpeg_hint(label: str, ffmpeg_hint: Optional[str] = None, enabled: bool = True) -> str:
    if enabled and ffmpeg_hint:
        hint_text = str(ffmpeg_hint).strip()
        if hint_text.startswith('(') and hint_text.endswith(')'):
            hint_text = hint_text[1:-1].strip()
        return f'{label}{HINT_SEP}{hint_text}'
    return label


def pad_display(text: str, width: int) -> str:
    return text + (' ' * max(0, width - get_display_width(text)))


def menu_item(label: str, value: Optional[str] = None, icon: Optional[str] = None, hint: Optional[str] = None, indent: int = 0) -> str:
    icon_text = UI_ICONS.get(icon, '') if icon else ''
    lead = ' ' * (indent * 2)
    body = f'{lead}{label}' if not icon_text else f'{lead}{icon_text} {label}'
    if value is not None:
        body = f"{pad_display(body, MENU_LABEL_WIDTH)} : {value}"
    if hint:
        body = f'{body}{HINT_SEP}{hint}'
    return body


def shorten_items(items: list[str], max_items: int = 3) -> list[str]:
    if len(items) <= max_items:
        return items
    return items[:max_items] + ['...']


def trim_to_display_width(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ''
    if get_display_width(text) <= max_width:
        return text
    suffix = '...'
    suffix_w = get_display_width(suffix)
    if max_width <= suffix_w:
        return suffix[:max_width]
    out = ''
    width = 0
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if width + ch_w > max_width - suffix_w:
            break
        out += ch
        width += ch_w
    return out + suffix


def _render_title_segment(title: Optional[str], width: int) -> str:
    """Render a horizontal line segment with an optional centered title."""
    if not title:
        return '─' * width
    clean = str(title).replace('\n', ' ').strip()
    padded = f' {clean} '
    tw = get_display_width(padded)
    if tw >= width - 2:
        return '─' * width
    remain = width - tw
    l_len = min(2, remain)
    r_len = remain - l_len
    return f"{'─' * l_len}{UI_COLORS['title']}\033[1m{padded}{UI_COLORS['reset']}{'─' * r_len}"


def build_top_border(inner_width: int, title_text: Optional[str] = None, divider_pos: Optional[int] = None, right_title: Optional[str] = None) -> str:
    if divider_pos is None:
        max_title_width = max(1, inner_width - 2)
        if title_text:
            clean_title = str(title_text).replace('\n', ' ').strip()
            title_plain = trim_to_display_width(f' {clean_title} ', max_title_width)
            title_w = get_display_width(title_plain)
            remain = max(0, inner_width - title_w)
            left = min(2, remain)
            right = remain - left
            return f"  ╭{'─' * left}{UI_COLORS['title']}\033[1m{title_plain}{UI_COLORS['reset']}{'─' * right}╮"
        return f"  ╭{'─' * inner_width}╮"
    left_str = _render_title_segment(title_text, divider_pos)
    right_avail = inner_width - divider_pos - 1
    right_str = _render_title_segment(right_title, right_avail)
    return f"  ╭{left_str}┬{right_str}╮"


def render_menu_box(lines: list[str], selected_index: Optional[int] = None) -> None:
    parsed_lines = []
    max_left_w = 0
    max_right_w = 0
    has_any_hint = False
    border_title = None

    for line in lines:
        plain = ANSI_ESCAPE.sub('', line)
        if plain.startswith(TITLE_MARKER) and border_title is None:
            border_title = plain[len(TITLE_MARKER):].strip()
            parsed_lines.append({'type': 'header', 'plain': plain})
            continue

        stripped = plain.strip()
        is_sep = _is_separator(stripped)
        is_empty = stripped == ''

        if HINT_SEP in line:
            has_any_hint = True
            parts = line.split(HINT_SEP, 1)
            left_part = parts[0]
            right_part = parts[1]
            left_plain = ANSI_ESCAPE.sub('', left_part)
            right_plain = ANSI_ESCAPE.sub('', right_part)
            if not is_sep and not is_empty:
                max_left_w = max(max_left_w, get_display_width(left_plain))
                max_right_w = max(max_right_w, get_display_width(right_plain))
            parsed_lines.append({'type': 'item', 'left': left_part, 'right': right_part, 'left_plain': left_plain, 'right_plain': right_plain})
        else:
            left_plain = plain
            # Strip context marker for width calculation
            measure_plain = left_plain[len(CONTEXT_MARKER):] if left_plain.startswith(CONTEXT_MARKER) else left_plain
            if not is_sep and not is_empty:
                max_left_w = max(max_left_w, get_display_width(measure_plain))
            parsed_lines.append({'type': 'item', 'left': line, 'right': None, 'left_plain': left_plain, 'right_plain': ''})

    term_w, term_h = shutil.get_terminal_size((120, 30))
    
    # Layout calculation
    divider_pos = None
    if has_any_hint:
        divider_pos = max_left_w + 6
        # Ensure right title ' 参数 ' fits
        min_right_w = get_display_width(' 参数 ') + 4
        current_right_w = max(max_right_w, min_right_w)
        inner_width = divider_pos + current_right_w + 5
    else:
        # Standard adaptive width for single-column menus
        inner_width = max_left_w + 6
        
    if border_title:
        inner_width = max(inner_width, get_display_width(f' {border_title} ') + 6)
    
    inner_width = min(inner_width, term_w - 6)
    if divider_pos and divider_pos > inner_width - 15:
        divider_pos = max(20, inner_width - max_right_w - 5)

    # Handle scrolling
    content_lines = [p for p in parsed_lines if p['type'] != 'header']
    max_rows = term_h - (6 if border_title else 4)
    start_row = 0
    if selected_index is not None:
        header_count = sum(1 for p in parsed_lines[:selected_index] if p['type'] == 'header')
        rel_idx = selected_index - header_count
        if len(content_lines) > max_rows:
            start_row = max(0, rel_idx - max_rows // 2)
            if start_row + max_rows > len(content_lines):
                start_row = max(0, len(content_lines) - max_rows)

    visible_content = content_lines[start_row : start_row + max_rows]

    # Pre-compute headers_before for selected_index (O(n) instead of O(n²))
    headers_before_selected = 0
    if selected_index is not None:
        headers_before_selected = sum(1 for p in parsed_lines[:selected_index] if p['type'] == 'header')

    # Build top border with '参数' on the right if applicable
    out = [build_top_border(inner_width, border_title, divider_pos, right_title="参数" if divider_pos else None)]
    if border_title:
        if divider_pos:
            out.append(f"  │{' ' * divider_pos}│{' ' * (inner_width - divider_pos - 1)}│")
        else:
            out.append(f"  │{' ' * inner_width}│")

    for idx, item in enumerate(visible_content):
        i = start_row + idx
        is_selected = selected_index is not None and (i + headers_before_selected) == selected_index
        
        left_plain = item['left_plain']
        stripped = left_plain.strip()
        is_separator = _is_separator(stripped)
        is_empty = stripped == ''
        is_context = left_plain.startswith(CONTEXT_MARKER)

        if is_separator:
            if divider_pos:
                # Left side: space + line + space | Divider | Right side: space + line + space
                l_sep = '─' * max(0, divider_pos - 2)
                r_sep = '─' * max(0, inner_width - divider_pos - 3)
                out.append(f"  │ {UI_COLORS['muted']}{l_sep}{UI_COLORS['reset']} │ {UI_COLORS['muted']}{r_sep}{UI_COLORS['reset']} │")
            else:
                # Single column: space + line + space
                sep = '─' * max(0, inner_width - 2)
                out.append(f"  │ {UI_COLORS['muted']}{sep}{UI_COLORS['reset']} │")
            continue

        if is_context:
            ctx_text = left_plain[len(CONTEXT_MARKER):]
            ctx_display = f"  {ctx_text}"
            l_avail = divider_pos - 2 if divider_pos else inner_width - 2
            ctx_trunc = trim_to_display_width(ctx_display, l_avail)
            ctx_pad = ' ' * max(0, l_avail - get_display_width(ctx_trunc))
            right_pad = f"│{' ' * (inner_width - divider_pos - 1)}│" if divider_pos else "│"
            out.append(f"  │{UI_COLORS['muted']}{ctx_trunc}{ctx_pad}{UI_COLORS['reset']}{right_pad}")
            continue

        if is_empty:
            if divider_pos:
                out.append(f"  │{' ' * divider_pos}│{' ' * (inner_width - divider_pos - 1)}│")
            else:
                out.append(f"  │{' ' * inner_width}│")
            continue

        # Draw columns
        r_content = item['right']
        
        # Left column
        l_avail = divider_pos - 6 if divider_pos else inner_width - 6
        l_trunc = trim_to_display_width(left_plain, l_avail)
        l_marker = f" {UI_ICONS['focus']} " if is_selected else "   "
        l_text = f"{l_marker}{l_trunc}"
        # Apply background color and bold font for selected row
        l_color = UI_COLORS['selected_row'] + '\033[38;2;205;214;244m\033[1m' if is_selected else ""
        # For non-selected rows with embedded ANSI colors, preserve them
        if not is_selected:
            raw = item.get('left', '')
            # Extract all leading ANSI codes (e.g. color + bold)
            ansi_prefix = ''
            pos = 0
            while pos < len(raw):
                m = re.match(r'(\x1b\[[0-9;]*m)', raw[pos:])
                if m:
                    ansi_prefix += m.group(1)
                    pos += len(m.group(1))
                else:
                    break
            if ansi_prefix:
                l_color = ansi_prefix
        l_pad = ' ' * max(0, (divider_pos if divider_pos else inner_width) - get_display_width(l_text))
        
        if divider_pos:
            # Right column
            r_avail = inner_width - divider_pos - 5
            r_trunc = trim_to_display_width(r_content or "", r_avail)
            # Bold the right column text as well if selected
            r_style = UI_COLORS['muted'] + ('\033[38;2;205;214;244m\033[1m' if is_selected else "")
            r_text = f" {r_style}{r_trunc}{UI_COLORS['reset']}" if r_content else ""
            r_pad = ' ' * max(0, (inner_width - divider_pos - 1) - get_display_width(r_text))
            out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│{r_text}{r_pad}│")
        else:
            out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│")

    if divider_pos:
        out.append(f"  ╰{'─' * divider_pos}┴{'─' * (inner_width - divider_pos - 1)}╯")
    else:
        out.append(f"  ╰{'─' * inner_width}╯")

    # Incremental render: only update changed lines
    global LAST_MENU_LINES
    if LAST_MENU_LINES is None:
        # First render: clear screen and draw all
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.write('\n'.join(out) + '\n')
    else:
        # Subsequent renders: diff and update only changed lines
        for i, line in enumerate(out):
            if i >= len(LAST_MENU_LINES) or line != LAST_MENU_LINES[i]:
                sys.stdout.write(f'\033[{i+1};1H{line}\033[K')
        # Clear extra lines if new output has fewer lines
        if len(out) < len(LAST_MENU_LINES):
            sys.stdout.write(f'\033[{len(out)+1};1H\033[J')
        # Ensure area below is clean
        sys.stdout.write(f'\033[{len(out)+1};1H\033[J')
    LAST_MENU_LINES = out
    sys.stdout.flush()


def render_preview_box(lines: list[str], title: Optional[str] = None) -> None:
    global LAST_PREVIEW_LINES, LAST_MENU_LINES
    parsed_lines = []
    max_w = 0
    for line in lines:
        plain = ANSI_ESCAPE.sub('', line)
        max_w = max(max_w, get_display_width(plain))
        parsed_lines.append((line, plain))

    term_w, _ = shutil.get_terminal_size((120, 30))
    # Add padding for visual comfort
    inner_width = min(max_w + 4, term_w - 6)

    out = [build_top_border(inner_width, title)]
    out.append(f"  │{' ' * inner_width}│") # Top padding

    for original, plain in parsed_lines:
        # Maintain ANSI colors but truncate text to terminal width
        trunc = trim_to_display_width(plain, inner_width - 2)
        padding = ' ' * (inner_width - get_display_width(trunc) - 1)
        # Combine leading color codes with truncated content
        prefix = original[:original.find(plain)] if plain in original else ''
        out.append(f'  │ {prefix}{trunc}{padding}│')

    # Safety padding row
    out.append(f"  │{' ' * inner_width}│")
    out.append(f"  ╰{'─' * inner_width}╯")

    # Always full render for preview (not incremental like menu)
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.write('\n'.join(out) + '\n')
    sys.stdout.flush()
    LAST_PREVIEW_LINES = out
    # Force next menu render to do a full redraw (preview replaces menu content)
    LAST_MENU_LINES = None


def render_screen_menu(screen_title: str, context_lines: list[str], menu_lines: list[str], selected_index: Optional[int] = None, footer_hint: Optional[str] = None) -> None:
    composed = [menu_section(screen_title)]
    for line in context_lines:
        composed.append(line)
    if context_lines and footer_hint:
        composed.append(MENU_SEPARATOR)
    menu_offset = len(composed)
    composed.extend(menu_lines)
    if footer_hint:
        composed.append(MENU_SEPARATOR)
        composed.append(footer_hint)

    normalized = normalize_selected_index(menu_lines, selected_index)
    adjusted_selected = (normalized + menu_offset) if normalized is not None else None
    render_menu_box(composed, selected_index=adjusted_selected)


class Action(Enum):
    CONTINUE = 'continue'
    BREAK = 'break'


def run_menu_loop(
    title: str,
    context_lines,
    build_menu,
    action_handler,
    footer_hint: str = None,
    allow_episode_nav: bool = False,
    update_current_episode=None,
    current_file_idx_ref: list = None,
    no_nav_indices: set = None,
):
    """Reusable menu loop handling UP/DOWN/BACKSPACE/LEFT/RIGHT/ENTER navigation.

    Args:
        context_lines: list or callable() -> list — context lines rendered above the menu.
        build_menu: callable() -> list[str] — returns menu items each iteration.
        action_handler: callable(key, selected_item, idx_in_sel) -> Action or None.
            Return None to continue the loop, Action.BREAK to exit, or any other
            value to exit and return it.
        allow_episode_nav: whether LEFT/RIGHT triggers episode navigation.
        update_current_episode: callable(new_idx) for episode navigation.
        current_file_idx_ref: single-element list with current file index.
        no_nav_indices: set of action-handler indices where episode nav is suppressed.
    Returns:
        The value returned by action_handler, or None if BACKSPACE was pressed.
    """
    idx = 0
    while True:
        if _shutdown_requested.is_set():
            return None
        print(CURSOR_HOME, end='', flush=True)
        hide_cursor()
        ctx = context_lines() if callable(context_lines) else context_lines
        menu = build_menu()
        render_screen_menu(title, ctx, menu, selected_index=idx, footer_hint=footer_hint)
        idx = normalize_selected_index(menu, idx) or 0
        key = read_navigation_key()

        if allow_episode_nav and key in ('LEFT', 'RIGHT'):
            should_nav = True
            if no_nav_indices:
                sel = get_selectable_indices(menu)
                if idx in sel and sel.index(idx) in no_nav_indices:
                    should_nav = False
            if should_nav:
                if update_current_episode and current_file_idx_ref is not None:
                    new_idx = current_file_idx_ref[0] + (-1 if key == 'LEFT' else 1)
                    update_current_episode(new_idx)
                    current_file_idx_ref[0] = new_idx  # sync ref for next press
                continue
        if key == 'UP':
            idx = get_next_selectable(menu, idx, -1)
            continue
        if key == 'DOWN':
            idx = get_next_selectable(menu, idx, 1)
            continue
        if key == 'BACKSPACE':
            return None
        if key not in ('LEFT', 'RIGHT', 'SHIFT_LEFT', 'SHIFT_RIGHT', 'ENTER', 'SHIFT_UP', 'SHIFT_DOWN'):
            continue

        sel = get_selectable_indices(menu)
        if idx not in sel:
            continue
        selected_item = ANSI_ESCAPE.sub('', menu[idx]).strip()
        result = action_handler(key, selected_item, sel.index(idx))
        if result is None or result == Action.CONTINUE:
            continue
        return result

