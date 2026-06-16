# 显示层：菜单渲染、文本格式化、预览框
#
# 渲染策略：由 rich 接管逐行 diff，通过 ui.live.update() 差异更新。
#
# 语义层（menu_item / with_ffmpeg_hint / menu_section / MENU_SEPARATOR 等）
# 仍产出带内嵌 ANSI 的字符串（保持现有调用方签名稳定），渲染时由
# Text.from_ansi 统一解析为带样式 span 的 Text。
import re
import shutil
import unicodedata
from enum import Enum
from typing import Optional

from rich.console import Group
from rich.text import Text

from ui.console import ANSI_ESCAPE, UI_COLORS, UI_ICONS, MENU_LABEL_WIDTH, TITLE_MARKER, CONTEXT_MARKER, _is_separator, _shutdown_requested
from core.helpers import truncate_name  # re-exported for ui.app
from ui.navigation import get_selectable_indices, get_next_selectable, normalize_selected_index, read_navigation_key
import ui.live as live

# 选中行前景色（背景色复用 UI_COLORS['selected_row']）
SELECTED_FG = "\033[38;2;205;214;244m\033[1m"

# 提取行首 ANSI 转义序列（预编译）
_ANSI_PREFIX_RE = re.compile(r'(\x1b\[[0-9;]*m)+')

# Title left-padding in top border (╭─── Title ───╮)
TITLE_LEFT_PAD = 3


def get_display_width(text: str) -> int:
    """Calculate display width, stripping ANSI escapes first."""
    return _display_width(ANSI_ESCAPE.sub('', str(text)))


def _display_width(clean_text: str) -> int:
    """Calculate display width of already-clean text (no ANSI escapes)."""
    return sum(_char_width(ch) for ch in clean_text)


def _char_width(ch: str) -> int:
    """Display width of a single character (2 for wide/fullwidth, 1 otherwise)."""
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def _sanitize_title(title) -> str:
    """Normalize a title: cast to str, replace newlines, strip."""
    return str(title).replace('\n', ' ').strip()


MENU_SEPARATOR = "─" * 52


def menu_section(title: str) -> str:
    return f"{TITLE_MARKER}{_sanitize_title(title)}"


_RIGHT_ALIGN = '\x1e'


def menu_return_item(label: str = '返回菜单') -> str:
    """Right-aligned return/back menu item; renderer places › before label."""
    return f"{_RIGHT_ALIGN}{UI_COLORS['muted']}{label}{UI_COLORS['reset']}"


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
    out = []
    width = 0
    for ch in text:
        ch_w = _char_width(ch)
        if width + ch_w > max_width - suffix_w:
            break
        out.append(ch)
        width += ch_w
    return ''.join(out) + suffix


def _render_title_segment(title: Optional[str], width: int) -> str:
    """Render a horizontal line segment with an optional centered title."""
    if not title:
        return '─' * width
    padded = trim_to_display_width(f' {_sanitize_title(title)} ', width - 4)
    tw = _display_width(padded)
    left = min(TITLE_LEFT_PAD, max(0, width - tw))
    right = max(0, width - tw) - left
    return f"{'─' * left}{UI_COLORS['title']}\033[1m{padded}{UI_COLORS['reset']}{'─' * right}"


def build_top_border(inner_width: int, title_text: Optional[str] = None, divider_pos: Optional[int] = None, right_title: Optional[str] = None) -> str:
    if divider_pos is None:
        if title_text:
            seg = _render_title_segment(title_text, inner_width)
            return f"  ╭{seg}╮"
        return f"  ╭{'─' * inner_width}╮"
    left_str = _render_title_segment(title_text, divider_pos)
    right_avail = inner_width - divider_pos - 1
    right_str = _render_title_segment(right_title, right_avail)
    return f"  ╭{left_str}┬{right_str}╮"


def build_menu_renderable(lines: list[str], selected_index: Optional[int] = None):
    """Build the menu box as a rich renderable (Group of Text lines).

    Layout mirrors the previous ANSI output exactly; each composed line is
    parsed back into a styled Text via Text.from_ansi so rich can diff it.
    Returns None if there is nothing to render.
    """
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
                max_left_w = max(max_left_w, _display_width(left_plain))
                max_right_w = max(max_right_w, _display_width(right_plain))
            parsed_lines.append({'type': 'item', 'left': left_part, 'right': right_part, 'left_plain': left_plain, 'right_plain': right_plain})
        else:
            left_plain = plain
            # Strip context marker for width calculation
            measure_plain = left_plain[len(CONTEXT_MARKER):] if left_plain.startswith(CONTEXT_MARKER) else left_plain
            if not is_sep and not is_empty:
                max_left_w = max(max_left_w, _display_width(measure_plain))
            parsed_lines.append({'type': 'item', 'left': line, 'right': None, 'left_plain': left_plain, 'right_plain': ''})

    term_w, term_h = shutil.get_terminal_size((120, 30))

    # Layout calculation
    divider_pos = None
    if has_any_hint:
        divider_pos = max_left_w + 4
        # Ensure right title ' 参数 ' fits
        min_right_w = _display_width(' 参数 ') + 4
        current_right_w = max(max_right_w, min_right_w)
        inner_width = divider_pos + current_right_w + 5
    else:
        # Standard adaptive width for single-column menus
        inner_width = max_left_w + 4

    if border_title:
        inner_width = max(inner_width, _display_width(f' {border_title} ') + 6)

    inner_width = min(inner_width, term_w - 6)
    if divider_pos and divider_pos > inner_width - 15:
        divider_pos = max(20, inner_width - max_right_w - 5)

    # Handle scrolling
    content_lines = [p for p in parsed_lines if p['type'] != 'header']
    max_rows = term_h - (6 if border_title else 4)
    start_row = 0
    headers_before_selected = 0
    if selected_index is not None:
        headers_before_selected = sum(1 for p in parsed_lines[:selected_index] if p['type'] == 'header')
        rel_idx = selected_index - headers_before_selected
        if len(content_lines) > max_rows:
            start_row = max(0, rel_idx - max_rows // 2)
            if start_row + max_rows > len(content_lines):
                start_row = max(0, len(content_lines) - max_rows)

    visible_content = content_lines[start_row : start_row + max_rows]

    # Build top border with '参数' on the right if applicable
    out = [build_top_border(inner_width, border_title, divider_pos, right_title="参数" if divider_pos else None)]
    if border_title:
        if divider_pos:
            out.append(f"  │{' ' * divider_pos}│{' ' * (inner_width - divider_pos - 1)}│")
        else:
            out.append(f"  │{' ' * inner_width}│")

    # Column geometry constants
    l_avail = (divider_pos - 4) if divider_pos else (inner_width - 4)
    l_col_w = divider_pos or inner_width  # left column outer width
    r_col_w = (inner_width - divider_pos - 1) if divider_pos else 0  # right column inner width

    def _empty_row() -> str:
        if divider_pos:
            return f"  │{' ' * divider_pos}│{' ' * r_col_w}│"
        return f"  │{' ' * inner_width}│"

    def _sep_row() -> str:
        muted = UI_COLORS['muted']
        reset = UI_COLORS['reset']
        if divider_pos:
            l_sep = '─' * max(0, divider_pos - 2)
            r_sep = '─' * max(0, r_col_w - 2)
            return f"  │ {muted}{l_sep}{reset} │ {muted}{r_sep}{reset} │"
        return f"  │ {muted}{'─' * max(0, inner_width - 2)}{reset} │"

    for idx, item in enumerate(visible_content):
        i = start_row + idx
        is_selected = selected_index is not None and (i + headers_before_selected) == selected_index

        left_plain = item['left_plain']
        stripped = left_plain.strip()
        is_separator = _is_separator(stripped)
        is_empty = stripped == ''
        is_context = left_plain.startswith(CONTEXT_MARKER)

        if is_separator:
            out.append(_sep_row())
            continue

        if is_context:
            ctx_text = left_plain[len(CONTEXT_MARKER):]
            ctx_display = f"  {ctx_text}"
            ctx_avail = (divider_pos - 2) if divider_pos else (inner_width - 2)
            ctx_trunc = trim_to_display_width(ctx_display, ctx_avail)
            ctx_pad = ' ' * max(2, l_col_w - _display_width(ctx_trunc))
            right_pad = f"│{' ' * r_col_w}│" if divider_pos else "│"
            out.append(f"  │{UI_COLORS['muted']}{ctx_trunc}{ctx_pad}{UI_COLORS['reset']}{right_pad}")
            continue

        if is_empty:
            out.append(_empty_row())
            continue

        # Right-aligned item (return/back button)
        if left_plain.startswith(_RIGHT_ALIGN):
            raw_content = item.get('left', '')[len(_RIGHT_ALIGN):]
            plain_label = left_plain[len(_RIGHT_ALIGN):]
            label_w = _display_width(plain_label)
            m_ra = _ANSI_PREFIX_RE.match(raw_content)
            ra_ansi = m_ra.group(0) if m_ra else ''
            content_w = l_col_w - 4  # 2 left + 2 right margin
            cursor_w = 2 if is_selected else 0
            max_label_w = content_w - cursor_w
            if label_w > max_label_w:
                plain_label = trim_to_display_width(plain_label, max_label_w)
                label_w = _display_width(plain_label)
            pad_n = max(0, content_w - label_w - cursor_w)
            if is_selected:
                l_text = '  ' + ' ' * pad_n + '› ' + plain_label + '  '
                l_color = UI_COLORS['selected_row'] + SELECTED_FG
            else:
                l_text = '  ' + ' ' * pad_n + plain_label + '  '
                l_color = ra_ansi
            l_pad = ' ' * max(0, l_col_w - _display_width(l_text))
            if divider_pos:
                out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│{' ' * r_col_w}│")
            else:
                out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│")
            continue

        # Left column
        l_trunc = trim_to_display_width(left_plain, l_avail)
        l_marker = "› " if is_selected else "  "
        l_text = f"{l_marker}{l_trunc}"
        # Extract embedded ANSI colors from raw item (e.g. green/yellow + bold)
        m = _ANSI_PREFIX_RE.match(item.get('left', ''))
        ansi_prefix = m.group(0) if m else ''
        if is_selected:
            l_color = UI_COLORS['selected_row'] + SELECTED_FG
        else:
            l_color = ansi_prefix
        l_pad = ' ' * max(0, l_col_w - get_display_width(l_text))

        if divider_pos:
            # Right column
            r_trunc = trim_to_display_width(item['right'] or "", r_col_w - 4)
            r_style = UI_COLORS['muted'] + (SELECTED_FG if is_selected else "")
            r_text = f"  {r_style}{r_trunc}{UI_COLORS['reset']}" if item['right'] else ""
            r_pad = ' ' * max(2, r_col_w - get_display_width(r_text))
            out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│{r_text}{r_pad}│")
        else:
            out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│")

    if divider_pos:
        out.append(f"  ╰{'─' * divider_pos}┴{'─' * r_col_w}╯")
    else:
        out.append(f"  ╰{'─' * inner_width}╯")

    # Convert composed ANSI lines into a rich Group (Text per line).
    # rich will diff the Group frame-to-frame; no manual screen clearing.
    return Group(*[Text.from_ansi(line) for line in out])


def render_screen_menu(screen_title: str, context_lines: list[str], menu_lines: list[str], selected_index: Optional[int] = None, footer_hint: Optional[str] = None):
    """Compose full screen (title + context + menu + footer) and push to Live."""
    composed = [menu_section(screen_title)] + list(context_lines)
    if context_lines and footer_hint:
        composed.append(MENU_SEPARATOR)
    menu_offset = len(composed)
    composed.extend(menu_lines)
    if footer_hint:
        composed.append(MENU_SEPARATOR)
        composed.append(footer_hint)

    normalized = normalize_selected_index(menu_lines, selected_index)
    adjusted_selected = (normalized + menu_offset) if normalized is not None else None
    renderable = build_menu_renderable(composed, selected_index=adjusted_selected)
    live.update(renderable)


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
    menu = build_menu()
    needs_rebuild = False
    needs_render = True
    while True:
        if _shutdown_requested.is_set():
            return None
        if needs_rebuild:
            menu = build_menu()
            needs_rebuild = False
            needs_render = True
        if needs_render:
            ctx = context_lines() if callable(context_lines) else context_lines
            render_screen_menu(title, ctx, menu, selected_index=idx, footer_hint=footer_hint)
            idx = normalize_selected_index(menu, idx) or 0
            needs_render = False
        key = read_navigation_key()

        if allow_episode_nav and key in ('LEFT', 'RIGHT'):
            if no_nav_indices:
                sel = get_selectable_indices(menu)
                if idx in sel and sel.index(idx) in no_nav_indices:
                    continue
            if update_current_episode and current_file_idx_ref is not None:
                new_idx = current_file_idx_ref[0] + (-1 if key == 'LEFT' else 1)
                update_current_episode(new_idx)
                current_file_idx_ref[0] = new_idx
                needs_rebuild = True
            continue
        if key in ('UP', 'DOWN'):
            new_idx = get_next_selectable(menu, idx, -1 if key == 'UP' else 1)
            if new_idx != idx:
                idx = new_idx
                needs_render = True
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
            menu = build_menu()
            needs_rebuild = False
            needs_render = True
            continue
        return result
