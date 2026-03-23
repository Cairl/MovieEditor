import os
import re
import io
import sys
import json
import time
import atexit
import msvcrt
import shutil
import threading
import subprocess
import unicodedata
import tkinter as tk
from tkinter import filedialog
from collections import deque

if sys.platform == 'win32':
    import ctypes
    # Enable Windows VT Processing (ANSI support)
    kernel32 = ctypes.windll.kernel32
    # -11 is STD_OUTPUT_HANDLE; 7 is ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
CURSOR_HOME = '\033[H'

ACTIVE_CHILD_PROCESSES = set()
ACTIVE_CHILD_LOCK = threading.Lock()


UI_COLORS = {
    'reset': '\033[0m',
    'accent': '\033[96m',
    'title': '\033[33m',
    'muted': '\033[90m',
    'selected_row': '\033[48;5;24m',
}
UI_ICONS = {
    'focus': '›',
}
MENU_LABEL_WIDTH = 28


def register_child_process(process):
    with ACTIVE_CHILD_LOCK:
        ACTIVE_CHILD_PROCESSES.add(process)


def unregister_child_process(process):
    with ACTIVE_CHILD_LOCK:
        ACTIVE_CHILD_PROCESSES.discard(process)


def terminate_active_children():
    with ACTIVE_CHILD_LOCK:
        processes = list(ACTIVE_CHILD_PROCESSES)
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
    time.sleep(0.2)
    for process in processes:
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            pass


atexit.register(terminate_active_children)

if os.name == 'nt':
    try:
        import ctypes
        _CTRL_HANDLER = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def _console_ctrl_handler(_):
            terminate_active_children()
            return False

        _console_ctrl_handler_ref = _CTRL_HANDLER(_console_ctrl_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_ctrl_handler_ref, True)
    except Exception:
        pass


def hide_cursor():
    print('\033[?25l', end='', flush=True)


def show_cursor():
    print('\033[?25h', end='', flush=True)


def get_display_width(text):
    # Strip ANSI escape sequences before calculating width
    clean_text = ANSI_ESCAPE.sub('', str(text))
    width = 0
    for ch in clean_text:
        width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return width


TITLE_MARKER = '__TITLE__ '
MENU_SEPARATOR = '─' * 52


def menu_section(title):
    clean = str(title).replace('\n', ' ').strip()
    return f"{TITLE_MARKER}{clean}"


HINT_SEP = '\x1f'

def with_ffmpeg_hint(label, ffmpeg_hint=None, enabled=True):
    if enabled and ffmpeg_hint:
        hint_text = str(ffmpeg_hint).strip()
        if hint_text.startswith('(') and hint_text.endswith(')'):
            hint_text = hint_text[1:-1].strip()
        return f'{label}{HINT_SEP}{hint_text}'
    return label


def pad_display(text, width):
    return text + (' ' * max(0, width - get_display_width(text)))


def menu_item(label, value=None, icon=None, hint=None, indent=0):
    icon_text = UI_ICONS.get(icon, '') if icon else ''
    lead = ' ' * (indent * 2)
    body = f'{lead}{label}' if not icon_text else f'{lead}{icon_text} {label}'
    if value is not None:
        body = f"{pad_display(body, MENU_LABEL_WIDTH)} : {value}"
    if hint:
        body = f'{body}{HINT_SEP}{hint}'
    return body


def shorten_items(items, max_items=3):
    if len(items) <= max_items:
        return items
    return items[:max_items] + ['...']


def trim_to_display_width(text, max_width):
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


def build_top_border(inner_width, title_text=None, divider_pos=None, right_title=None):
    if divider_pos is None:
        if not title_text:
            return f"  ╭{'─' * inner_width}╮"
        clean_title = str(title_text).replace('\n', ' ').strip()
        title_plain = f' {clean_title} '
        max_title_width = max(1, inner_width - 2)
        title_plain = trim_to_display_width(title_plain, max_title_width)
        title_w = get_display_width(title_plain)
        remain = max(0, inner_width - title_w)
        left = min(2, remain)
        right = remain - left
        return f"  ╭{'─' * left}{UI_COLORS['title']}\033[1m{title_plain}{UI_COLORS['reset']}{'─' * right}╮"
    else:
        # Split top border with T-junction and optional right title
        # Left part
        left_str = ""
        if title_text:
            clean_title = str(title_text).replace('\n', ' ').strip()
            title_p = f' {clean_title} '
            tw = get_display_width(title_p)
            if tw < divider_pos - 2:
                rem = divider_pos - tw
                l_len = min(2, rem)
                r_len = rem - l_len
                left_str = f"{'─' * l_len}{UI_COLORS['title']}\033[1m{title_p}{UI_COLORS['reset']}{'─' * r_len}"
            else:
                left_str = '─' * divider_pos
        else:
            left_str = '─' * divider_pos

        # Right part
        right_avail = inner_width - divider_pos - 1
        right_str = ""
        if right_title:
            rt_p = f' {right_title} '
            rtw = get_display_width(rt_p)
            if rtw < right_avail - 2:
                rem_r = right_avail - rtw
                rl_len = min(2, rem_r)
                rr_len = rem_r - rl_len
                right_str = f"{'─' * rl_len}{UI_COLORS['title']}\033[1m{rt_p}{UI_COLORS['reset']}{'─' * rr_len}"
            else:
                right_str = '─' * right_avail
        else:
            right_str = '─' * right_avail

        return f"  ╭{left_str}┬{right_str}╮"


def render_menu_box(lines, selected_index=None):
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
        is_sep = len(stripped) > 0 and len(set(stripped)) == 1 and stripped[0] in ('─', '-', '=')
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
            if not is_sep and not is_empty:
                max_left_w = max(max_left_w, get_display_width(left_plain))
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

    # Build top border with '参数' on the right if applicable
    out = [build_top_border(inner_width, border_title, divider_pos, right_title="参数" if divider_pos else None)]
    if border_title:
        if divider_pos:
            out.append(f"  │{' ' * divider_pos}│{' ' * (inner_width - divider_pos - 1)}│")
        else:
            out.append(f"  │{' ' * inner_width}│")

    for idx, item in enumerate(visible_content):
        i = start_row + idx
        headers_before = sum(1 for p in parsed_lines if p['type'] == 'header' and parsed_lines.index(p) <= selected_index) if selected_index is not None else 0
        is_selected = selected_index is not None and (i + headers_before) == selected_index
        
        left_plain = item['left_plain']
        stripped = left_plain.strip()
        is_separator = len(stripped) > 0 and len(set(stripped)) == 1 and stripped[0] in ('─', '-', '=')
        is_empty = stripped == ''

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
        l_color = UI_COLORS['selected_row'] + '\033[1m' if is_selected else ""
        l_pad = ' ' * max(0, (divider_pos if divider_pos else inner_width) - get_display_width(l_text))
        
        if divider_pos:
            # Right column
            r_avail = inner_width - divider_pos - 5
            r_trunc = trim_to_display_width(r_content or "", r_avail)
            # Bold the right column text as well if selected
            r_style = UI_COLORS['muted'] + ('\033[1m' if is_selected else "")
            r_text = f" {r_style}{r_trunc}{UI_COLORS['reset']}" if r_content else ""
            r_pad = ' ' * max(0, (inner_width - divider_pos - 1) - get_display_width(r_text))
            out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│{r_text}{r_pad}│")
        else:
            out.append(f"  │{l_color}{l_text}{l_pad}{UI_COLORS['reset']}│")

    if divider_pos:
        out.append(f"  ╰{'─' * divider_pos}┴{'─' * (inner_width - divider_pos - 1)}╯")
    else:
        out.append(f"  ╰{'─' * inner_width}╯")
    
    os.system('cls' if os.name == 'nt' else 'clear')
    sys.stdout.write('\n'.join(out) + '\n')
    sys.stdout.flush()


def render_preview_box(lines, title=None):
    # Use physical clear to handle potential buffer overflow for long commands
    os.system('cls' if os.name == 'nt' else 'clear')
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
        
    out.append(f"  ╰{'─' * inner_width}╯")
    sys.stdout.write('\n'.join(out) + '\n')
    sys.stdout.flush()


def get_selectable_indices(lines):
    selectable = []
    for i, line in enumerate(lines):
        plain = ANSI_ESCAPE.sub('', line)
        stripped = plain.strip()
        is_empty = stripped == ''
        is_separator = len(stripped) > 0 and len(set(stripped)) == 1 and stripped[0] in ('─', '-', '=')
        is_header = plain.startswith(TITLE_MARKER)
        if not is_empty and not is_separator and not is_header:
            selectable.append(i)
    return selectable


def get_next_selectable(lines, current_index, direction):
    selectable = get_selectable_indices(lines)
    if not selectable:
        return current_index
    if current_index not in selectable:
        return selectable[0] if direction > 0 else selectable[-1]
    current_pos = selectable.index(current_index)
    return selectable[(current_pos + direction) % len(selectable)]


def normalize_selected_index(lines, selected_index):
    selectable = get_selectable_indices(lines)
    if not selectable:
        return None
    if selected_index in selectable:
        return selected_index
    return selectable[0]


def render_screen_menu(screen_title, context_lines, menu_lines, selected_index=None, footer_hint=None):
    composed = [menu_section(screen_title)]
    for line in context_lines:
        composed.append(line)
    if context_lines:
        composed.append(MENU_SEPARATOR)
    menu_offset = len(composed)
    composed.extend(menu_lines)
    if footer_hint:
        composed.append(MENU_SEPARATOR)
        composed.append(footer_hint)

    normalized = normalize_selected_index(menu_lines, selected_index)
    adjusted_selected = (normalized + menu_offset) if normalized is not None else None
    render_menu_box(composed, selected_index=adjusted_selected)


def format_hms(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def parse_time_to_seconds(time_text):
    if time_text is None:
        return 0
    value = str(time_text).strip()
    if value in ('', '0'):
        return 0
    if value.isdigit():
        return int(value)
    parts = value.split(':')
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        m, s = map(int, parts)
        return m * 60 + s
    return None


def adjust_time_setting(time_text, delta_seconds):
    seconds = parse_time_to_seconds(time_text)
    if seconds is None:
        seconds = 0
    new_seconds = max(0, seconds + delta_seconds)
    return format_hms(new_seconds) if new_seconds > 0 else None


def cycle_option(current, options, step):
    if not options:
        return current
    try:
        idx = options.index(current)
    except ValueError:
        idx = 0
    return options[(idx + step) % len(options)]


def format_on_off(enabled):
    return '开启' if enabled else '关闭'


def build_resolution_options(src_width, src_height):
    options: list = [None]
    if not src_width or not src_height:
        return options
    seen = set()
    for scale in (0.75, 0.5, 0.25):
        w = int(src_width * scale)
        h = int(src_height * scale)
        w -= w % 2
        h -= h % 2
        if w < 2 or h < 2:
            continue
        text = f'{w}x{h}'
        if text in seen:
            continue
        seen.add(text)
        options.append(text)
    return options


def read_navigation_key():
    while True:
        try:
            key = msvcrt.getch()
            # Check Shift key state on Windows
            is_shift = False
            if sys.platform == 'win32':
                is_shift = bool(ctypes.windll.user32.GetKeyState(0x10) & 0x8000)

            if key in (b'\xe0', b'\x00'):
                ext = msvcrt.getch()
                if ext == b'H':
                    return 'SHIFT_UP' if is_shift else 'UP'
                if ext == b'P':
                    return 'SHIFT_DOWN' if is_shift else 'DOWN'
                if ext == b'K':
                    return 'LEFT'
                if ext == b'M':
                    return 'RIGHT'
            elif key in (b'\r', b'\n'):
                return 'ENTER'
            elif key == b'\x08':
                return 'BACKSPACE'
            elif key == b'\x03':
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            raise
        except Exception:
            pass


def clear_keyboard_buffer():
    try:
        while msvcrt.kbhit():
            msvcrt.getch()
    except Exception:
        pass


def choose_files(title, filetypes):
    root = tk.Tk()
    root.withdraw()
    files = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    root.destroy()
    return list(files)


def choose_file(title, filetypes):
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return file_path


def choose_directory(title):
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(title=title)
    root.destroy()
    return path


def get_video_files_in_dir(dir_path):
    exts = ('.mp4', '.mkv', '.mov', '.avi', '.flv', '.wmv')
    files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.lower().endswith(exts)]
    # Sort files naturally (e.g., S01E01 before S01E10)
    files.sort(key=lambda x: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', x)])
    return files


def get_video_resolution(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        out = result.stdout.strip()
        if not out:
            return 0, 0
        w, h = map(int, out.split(','))
        return w, h
    except Exception:
        return 0, 0


def get_video_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0


def _probe_streams_json(file_path, selector, entries):
    try:
        # Increased probesize and duration for large 4K/BluRay files
        cmd = [
            'ffprobe', '-v', 'quiet', 
            '-probesize', '50M', '-analyzeduration', '100M',
            '-select_streams', selector, 
            '-show_entries', entries, 
            '-of', 'json', file_path
        ]
        # Use bytes and manual decode to avoid Windows locale encoding issues
        result = subprocess.run(cmd, capture_output=True, check=True)
        stdout_text = result.stdout.decode('utf-8', errors='replace')
        data = json.loads(stdout_text or '{}')
        return data.get('streams', [])
    except Exception:
        # Fallback attempt without extra probe params
        try:
            cmd = ['ffprobe', '-v', 'quiet', '-select_streams', selector, '-show_entries', entries, '-of', 'json', file_path]
            result = subprocess.run(cmd, capture_output=True, check=True)
            stdout_text = result.stdout.decode('utf-8', errors='replace')
            data = json.loads(stdout_text or '{}')
            return data.get('streams', [])
        except Exception:
            return []


def get_audio_streams(file_path):
    streams = []
    for i, s in enumerate(_probe_streams_json(file_path, 'a', 'stream=index,codec_name,channels:stream_tags=language')):
        streams.append({
            'index': s.get('index'), 
            'rel_index': i,
            'codec': s.get('codec_name', 'unknown'), 
            'channels': s.get('channels', 2), 
            'language': s.get('tags', {}).get('language', 'und')
        })
    return streams


def get_subtitle_streams(file_path):
    # 1. Get structured data using robust JSON probe
    streams_data = _probe_streams_json(file_path, 's', 'stream=index,codec_name:stream_tags=language,title')
    streams = []
    for i, s in enumerate(streams_data):
        tags = s.get('tags', {})
        streams.append({
            'index': s.get('index'), 
            'rel_index': i,
            'codec': s.get('codec_name', 'unknown'), 
            'language': tags.get('language', 'und'),
            'title': tags.get('title', ''),
            'raw_display_name': None
        })
    
    if not streams:
        return []

    # 2. Capture alias name from parentheses in raw output
    try:
        cmd = ['ffprobe', '-hide_banner', '-i', file_path]
        result = subprocess.run(cmd, capture_output=True)
        stderr_content = result.stderr.decode('utf-8', errors='replace')
        
        for s in streams:
            # Improved regex to handle language tags like Stream #0:2(eng)
            pattern = rf"Stream #\d+:{s['index']}.*?Subtitle: [^(]+?\((\w+)\)"
            match = re.search(pattern, stderr_content)
            if match:
                s['raw_display_name'] = match.group(1)
            else:
                s['raw_display_name'] = s['codec']
    except Exception:
        for s in streams:
            s['raw_display_name'] = s['codec']
            
    return streams


def format_preview_lines(command, input_file=None, output_file=None):
    def replace_path(token):
        text = str(token)
        if input_file and text == input_file:
            return 'input'
        if output_file and text == output_file:
            return 'output'
        return text

    lines = [f'  {command[0]}']
    i = 1
    
    while i < len(command):
        token = replace_path(command[i])
        
        if token.startswith('-'):
            line = f'    {token}'
            if i + 1 < len(command) and not str(command[i + 1]).startswith('-'):
                arg = replace_path(command[i + 1])
                if any(c.isspace() for c in arg):
                    arg = f'"{arg}"'
                line += f' {arg}'
                i += 1
            lines.append(line)
        else:
            lines.append(f'    {token}')
        i += 1
    
    return lines


def run_ffmpeg_with_progress(command, total_duration, title_prefix=''):
    output_file = command[-1]
    # Prepare command for execution
    exec_command = command[:-1] + ['-progress', 'pipe:1', output_file]
    
    # Extract input/output for pretty display
    input_file = None
    try:
        if '-i' in command:
            idx = command.index('-i')
            if idx + 1 < len(command):
                input_file = command[idx+1]
    except Exception:
        pass

    # Format command lines vertically
    cmd_lines_raw = format_preview_lines(command, input_file, output_file)

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = subprocess.Popen(exec_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='replace', creationflags=creationflags)
    register_child_process(process)
    
    stderr_tail = deque(maxlen=10)

    def collect_err():
        try:
            if process.stderr:
                for line in process.stderr:
                    clean = line.strip()
                    if clean:
                        stderr_tail.append(clean)
        except Exception:
            pass

    t_err = threading.Thread(target=collect_err, daemon=True)
    t_err.start()

    state = {
        'current_ms': 0,
        'speed': 0.0,
        'done': False,
        'started': False,
        'lock': threading.Lock()
    }

    def reader():
        alpha = 0.1
        try:
            if process.stdout:
                for line in process.stdout:
                    if 'out_time_ms=' in line:
                        try:
                            ms = int(line.split('=', 1)[1].strip())
                            if ms > 0:
                                with state['lock']:
                                    state['current_ms'] = ms
                                    state['started'] = True
                        except Exception:
                            pass
                    if 'speed=' in line:
                        try:
                            sp_str = line.split('speed=', 1)[1].split('x', 1)[0].strip()
                            if sp_str != 'N/A':
                                cur = float(sp_str)
                                with state['lock']:
                                    state['speed'] = alpha * cur + (1 - alpha) * (state['speed'] if state['speed'] > 0 else cur)
                                    if cur > 0.01:
                                        state['started'] = True
                        except Exception:
                            pass
                    if 'progress=end' in line:
                        break
        except Exception:
            pass
        finally:
            state['done'] = True

    t_read = threading.Thread(target=reader, daemon=True)
    t_read.start()

    def get_shimmer_text(text, offset):
        C_DIM = '\033[90m'
        C_MID = '\033[37m'
        C_BRIGHT = '\033[97m\033[1m'
        C_RESET = '\033[0m'
        
        out = []
        text_len = len(text)
        wave_width = 12
        total_range = text_len + wave_width * 2
        center = (offset * total_range) - wave_width
        
        for i, char in enumerate(text):
            dist = abs(i - center)
            if dist < 2:
                color = C_BRIGHT
            elif dist < 5:
                color = C_MID
            else:
                color = C_DIM
            out.append(f'{color}{char}')
        out.append(C_RESET)
        return ''.join(out)

    hide_cursor()
    last_plain_text = '正在初始化进程...'
    
    # State for UI rendering
    last_term_size = (0, 0)
    
    # Layout constants
    PROGRESS_ROW_IDX = 3 # 1-based ANSI line number

    def draw_full_interface(progress_text, title, is_finished):
        term_w, term_h = shutil.get_terminal_size((120, 30))
        width = max(70, min(120, term_w - 2))
        inner_width = width - 4
        
        # Truncate command lines if they are too many for the current terminal height
        display_cmd = cmd_lines_raw
        max_cmd_lines = max(3, term_h - 10)
        if len(display_cmd) > max_cmd_lines:
            display_cmd = display_cmd[:max_cmd_lines-1] + ["    ... (更多参数已在下方省略)"]

        # Title
        clean_title = f' {title} '
        title_plain_len = get_display_width(clean_title)
        remain_w = max(0, width - 2 - title_plain_len)
        left_line_len = 2
        right_line_len = max(0, remain_w - left_line_len)
        
        top_bar = (
            f"  ╭{'─' * left_line_len}"
            f"{UI_COLORS['title']}\033[1m{clean_title}{UI_COLORS['reset']}"
            f"{'─' * right_line_len}╮"
        )
        
        # Build lines
        lines = []
        lines.append(top_bar)
        lines.append(f"  │{' ' * (width - 2)}│") # Padding
        lines.append(build_progress_line(progress_text, width, is_finished))
        lines.append(f"  │{' ' * (width - 2)}│") # Padding

        # Command Lines
        for line in display_cmd:
            plain = ANSI_ESCAPE.sub('', line)
            trunc = trim_to_display_width(plain, inner_width - 2)
            colored = f"{UI_COLORS['muted']}{trunc}{UI_COLORS['reset']}"
            pad = ' ' * max(0, width - 2 - get_display_width(trunc))
            lines.append(f"  │{colored}{pad}│")
            
        lines.append(f"  ╰{'─' * (width - 2)}╯")
        
        sys.stdout.write('\033[H\033[J')
        sys.stdout.write('\n'.join(lines) + '\n')
        sys.stdout.flush()
        
        return (term_w, term_h)

    def build_progress_line(text, width, is_finished):
        indent = '  '
        inner_w = width - 2
        if is_finished:
             p_display = f"\033[97m\033[1m{text}\033[0m"
             plain_len = get_display_width(text)
        else:
             p_display = text
             plain_len = get_display_width(ANSI_ESCAPE.sub('', text))
        pad_len = max(0, inner_w - len(indent) - plain_len)
        return f"  │{indent}{p_display}{' ' * pad_len}│"

    try:
        start_time = time.time()
        display_title = f"{title_prefix} - 运行中" if title_prefix else "运行中"
        last_term_size = draw_full_interface(last_plain_text, display_title, False)
        
        while not state['done']:
            now = time.time()
            elapsed = now - start_time
            
            with state['lock']:
                curr_ms = state['current_ms']
                spd = state['speed']
                has_started = state['started']
            
            if not has_started:
                plain_text = '正在初始化进程...'
            else:
                curr_sec = curr_ms / 1000000.0
                if total_duration > 0:
                    pct = min(100.0, curr_sec / total_duration * 100)
                    rem = max(0, total_duration - curr_sec)
                    eta = rem / spd if spd > 0.01 else 0
                    plain_text = f'进度：{format_hms(curr_sec)}/{format_hms(total_duration)} ({pct:>6.2f}%) │ 速度：{spd:.2f}x │ 用时：{format_hms(elapsed)} │ 剩余：{format_hms(eta)}'
                else:
                    plain_text = f'进度：{format_hms(curr_sec)} │ 速度：{spd:.2f}x │ 用时：{format_hms(elapsed)}'
            
            last_plain_text = plain_text
            
            current_term_size = shutil.get_terminal_size((120, 30))
            # If command is too tall for terminal, absolute positioning won't work correctly after scroll.
            # In such cases, we fallback to full redraw every loop (using CURSOR_HOME + Clear Screen).
            content_height = len(cmd_lines_raw) + 7
            is_too_tall = content_height > current_term_size.lines

            if current_term_size != last_term_size or is_too_tall:
                cycle = 2.0
                shimmer_offset = (now % cycle) / cycle
                styled_text = get_shimmer_text(plain_text, shimmer_offset)
                last_term_size = draw_full_interface(styled_text, display_title, False)
            else:
                cycle = 2.0
                shimmer_offset = (now % cycle) / cycle
                styled_text = get_shimmer_text(plain_text, shimmer_offset)
                width = max(70, min(120, current_term_size.columns - 2))
                line_str = build_progress_line(styled_text, width, False)
                print(f'\033[{PROGRESS_ROW_IDX};1H{line_str}', end='', flush=True)
            
            time.sleep(0.05)
            if process.poll() is not None and not state['done']:
                state['done'] = True

        process.wait()
        t_read.join(timeout=1.0)
        t_err.join(timeout=1.0)
        
        if process.returncode != 0:
            msg = f'FFmpeg 执行失败，返回码: {process.returncode}'
            if stderr_tail:
                msg += '\n' + '\n'.join(stderr_tail)
            raise RuntimeError(msg)
            
        # Final Render: Completed state
        finish_title = f"{title_prefix} - 已完成" if title_prefix else "已完成"
        draw_full_interface(last_plain_text, finish_title, True)

    finally:
        unregister_child_process(process)


def get_full_language_name(lang_code):
    mapping = {
        'chi': 'Chinese', 'zho': 'Chinese', 'chs': 'Chinese (Simplified)', 'cht': 'Chinese (Traditional)',
        'eng': 'English', 'jpn': 'Japanese', 'kor': 'Korean', 'fre': 'French', 'fra': 'French',
        'ger': 'German', 'deu': 'German', 'rus': 'Russian', 'spa': 'Spanish', 'ita': 'Italian',
        'ara': 'Arabic', 'bul': 'Bulgarian', 'cze': 'Czech', 'ces': 'Czech', 'dan': 'Danish',
        'est': 'Estonian', 'fin': 'Finnish', 'gre': 'Greek', 'ell': 'Greek', 'heb': 'Hebrew',
        'hin': 'Hindi', 'hun': 'Hungarian', 'ind': 'Indonesian', 'lit': 'Lithuanian',
        'lav': 'Latvian', 'may': 'Malay', 'msa': 'Malay', 'dut': 'Dutch', 'nld': 'Dutch',
        'nor': 'Norwegian', 'pol': 'Polish', 'por': 'Portuguese', 'rum': 'Romanian', 'ron': 'Romanian',
        'slo': 'Slovak', 'slk': 'Slovak', 'slv': 'Slovenian', 'swe': 'Swedish', 'tha': 'Thai',
        'tur': 'Turkish', 'ukr': 'Ukrainian', 'vie': 'Vietnamese'
    }
    code = str(lang_code).lower()
    return mapping.get(code, code.upper())


def get_subtitle_format_name(codec_name):
    mapping = {
        'subrip': 'SRT',
        'mov_text': 'Text',
        'text': 'Text',
        'ass': 'ASS',
        'ssa': 'SSA',
        'hdmv_pgs_subtitle': 'PGS',
        'dvd_subtitle': 'DVD',
        'webvtt': 'VTT'
    }
    name = str(codec_name).lower()
    return mapping.get(name, name.upper())


def process_files():
    input_paths = []
    is_series_mode = False

    if len(sys.argv) > 1:
        is_series_mode = any(os.path.isdir(arg) for arg in sys.argv[1:])
        if is_series_mode:
            for arg in sys.argv[1:]:
                if os.path.isdir(arg):
                    input_paths.extend(get_video_files_in_dir(arg))
                elif os.path.isfile(arg):
                    input_paths.append(arg)
        else:
            # Movie mode: only take the first file
            for arg in sys.argv[1:]:
                if os.path.isfile(arg):
                    input_paths = [arg]
                    break
    else:
        # No arguments provided: TUI selection
        tui_idx = 0
        while True:
            # Re-read screen dimensions or use fixed menu
            tui_lines = [
                menu_item('选择单个视频文件'),
                menu_item('选择剧集文件夹'),
                MENU_SEPARATOR,
                menu_item('退出程序'),
                ''
            ]
            render_screen_menu('请选择输入目标', [], tui_lines, selected_index=tui_idx)
            tui_idx = normalize_selected_index(tui_lines, tui_idx) or 0
            
            tk_key = read_navigation_key()
            if tk_key == 'UP':
                tui_idx = get_next_selectable(tui_lines, tui_idx, -1)
                continue
            if tk_key == 'DOWN':
                tui_idx = get_next_selectable(tui_lines, tui_idx, 1)
                continue
            if tk_key != 'ENTER':
                continue
                
            sel = get_selectable_indices(tui_lines)
            if tui_idx not in sel: continue
            choice = sel.index(tui_idx)
            
            if choice == 0:
                path = choose_file('选择媒体文件 (电影模式)', [('视频文件', '*.mp4 *.mkv *.mov *.avi *.flv *.wmv'), ('所有文件', '*.*')])
                if path:
                    input_paths = [path]
                    is_series_mode = False
                    break
            elif choice == 1:
                dir_path = choose_directory('选择剧集文件夹 (剧集模式)')
                if dir_path:
                    files = get_video_files_in_dir(dir_path)
                    if files:
                        input_paths = files
                        is_series_mode = True
                        break
            elif choice == 2:
                return

    if not input_paths:
        print('未发现可处理的文件')
        return

    # Use the first file to probe streams and settings
    current_file_idx = 0
    first_file = ""
    first_width, first_height = 0, 0
    audio_streams = []
    subtitle_streams = []
    resolution_options = []

    def update_current_episode(idx):
        nonlocal current_file_idx, first_file, first_width, first_height, audio_streams, subtitle_streams, resolution_options
        current_file_idx = idx % len(input_paths)
        first_file = input_paths[current_file_idx]
        first_width, first_height = get_video_resolution(first_file)
        audio_streams = get_audio_streams(first_file)
        subtitle_streams = get_subtitle_streams(first_file)
        resolution_options = build_resolution_options(first_width, first_height)
    
    update_current_episode(0)

    mode_title = "剧集模式" if is_series_mode else "电影模式"

    settings = {
        'video': {'hevc': True, 'resolution': None, 'crop_top': 0, 'crop_left': 0, 'ss': None, 'to': None},
        'audio': {'reencode': True, 'codec': 'aac', 'internal_streams': {}},
        'subtitle': {'mode': 'internal', 'files': [], 'burn_in': False, 'disable': False, 'codec': 'copy', 'internal_streams': {}, 'external_streams': {}},
    }

    audio_codec_options = ['aac', 'mp3', 'ac3', 'flac']

    def should_use_simple_map0():
        # Check if we can use -map 0 (all streams)
        # This is allowed if we are not selectively dropping streams or using external inputs
        
        # Audio: All internal streams must be enabled (or not yet configured/visited)
        if not all(settings['audio']['internal_streams'].values()):
            return False
            
        # Subtitle: Must be internal mode, no burn-in, not disabled, all streams enabled
        if settings['subtitle']['mode'] != 'internal':
            return False
        if settings['subtitle']['burn_in']:
            return False
        if settings['subtitle']['disable']:
            return False
        if not all(settings['subtitle']['internal_streams'].values()):
            return False
            
        return True

    def build_crop_filter_text():
        return f"crop=in_w-{settings['video']['crop_left']*2}:in_h-{settings['video']['crop_top']*2}:{settings['video']['crop_left']}:{settings['video']['crop_top']}"

    def build_ffmpeg_command(input_file, audio_streams, subtitle_streams, series_mode=False, external_subtitle=None):
        if series_mode:
            out_dir = os.path.join(os.path.dirname(input_file), 'Edited')
            out_path = os.path.join(out_dir, os.path.splitext(os.path.basename(input_file))[0] + '.mp4')
        else:
            out_path = os.path.join(os.path.dirname(input_file), '[FF] ' + os.path.splitext(os.path.basename(input_file))[0] + '.mp4')
        
        # Use -ignore_unknown to prevent failing on data/attachment streams
        cmd = ['ffmpeg', '-y', '-hide_banner', '-ignore_unknown', '-i', input_file]
        vf_filters = []
        if settings['video']['crop_top'] > 0 or settings['video']['crop_left'] > 0:
            vf_filters.append(build_crop_filter_text())

        selected_internal_sub = [s for s in subtitle_streams if settings['subtitle']['internal_streams'].get(str(s['index']), True)]
        
        # Find selected audio streams in their current order
        selected_audio_streams = [s for s in audio_streams if settings['audio']['internal_streams'].get(str(s['index']), True)]
        
        if external_subtitle:
            selected_external_sub = [external_subtitle]
        else:
            selected_external_sub = [f for i, f in enumerate(settings['subtitle']['files']) if settings['subtitle']['external_streams'].get(str(i), True)]

        if settings['subtitle']['burn_in'] and not settings['subtitle']['disable']:
            if settings['subtitle']['mode'] == 'internal' and selected_internal_sub:
                # On Windows, drive colons must be escaped for the subtitles filter
                safe_input_path = input_file.replace('\\', '/').replace(':', '\\:').replace('[', '\\[').replace(']', '\\]')
                vf_filters.append(f"subtitles={safe_input_path}:si={selected_internal_sub[0]['rel_index']}")
            elif settings['subtitle']['mode'] == 'external' and selected_external_sub:
                f = selected_external_sub[0]
                safe_path = f.replace('\\', '/').replace(':', '\\:').replace('[', '\\[').replace(']', '\\]')
                vf_filters.append(f"subtitles={safe_path}")

        # Always use explicit mapping for better compatibility with MP4
        cmd.extend(['-map', '0:v:0']) # Map first video stream
        
        # Use semantic audio mapping with original relative indices
        for s in selected_audio_streams:
            cmd.extend(['-map', f"0:a:{s['rel_index']}"])

        if not settings['subtitle']['disable'] and not settings['subtitle']['burn_in']:
            if settings['subtitle']['mode'] == 'internal':
                for s in selected_internal_sub:
                    cmd.extend(['-map', f"0:s:{s['rel_index']}"])
            else:
                base = 1
                for f in selected_external_sub:
                    cmd.extend(['-i', f])
                for i in range(len(selected_external_sub)):
                    cmd.extend(['-map', f'{base+i}:s:0'])

        if settings['video']['hevc']:
            # Use libx265 for better compatibility, though 'hevc' often works as an alias
            cmd.extend(['-c:v', 'libx265', '-crf', '23'])
        else:
            cmd.extend(['-c:v', 'libx264'])
        
        # Audio codec
        if not settings['audio']['reencode']:
            cmd.extend(['-c:a', 'copy'])
            
        if settings['subtitle']['burn_in']:
            cmd.append('-sn')
        elif not settings['subtitle']['burn_in']:
            has_subtitle_stream = (settings['subtitle']['mode'] == 'internal' and len(selected_internal_sub) > 0) or (settings['subtitle']['mode'] == 'external' and len(selected_external_sub) > 0)
            if has_subtitle_stream:
                # MP4 only supports mov_text. If user wants copy, we try, but mov_text is safer.
                if settings['subtitle']['codec'] == 'copy':
                    cmd.extend(['-c:s', 'mov_text'])
                else:
                    cmd.extend(['-c:s', settings['subtitle']['codec']])

        # Metadata and safety flags
        cmd.extend([
            '-map_metadata', '0', 
            '-map_chapters', '0', 
            '-metadata', 'handler_name=@Cairl'
        ])
        
        if vf_filters:
            cmd.extend(['-vf', ','.join(vf_filters)])
        if settings['video']['resolution']:
            cmd.extend(['-s', settings['video']['resolution'], '-aspect', settings['video']['resolution'].replace('x', ':')])
        
        # Positioning -ss and -to before output file as output options
        if settings['video']['ss']:
            cmd.extend(['-ss', settings['video']['ss']])
        if settings['video']['to']:
            cmd.extend(['-to', settings['video']['to']])

        cmd.append(out_path)
        return cmd

    main_index = 0
    while True:
        hide_cursor()

        context = [
            f"模式: {mode_title}",
            f"文件: {len(input_paths)} 个"
        ]
        if is_series_mode:
            context.append(f"当前针对: {os.path.basename(first_file)} ({current_file_idx+1}/{len(input_paths)})")

        menu = [
            menu_item('开始处理'),
            MENU_SEPARATOR,
            menu_item('视频设置'),
            menu_item('音频设置'),
            menu_item('字幕设置'),
            MENU_SEPARATOR,
            menu_item('查看 FFmpeg 命令预览'),
            '',
        ]
        render_screen_menu('主界面', context, menu, selected_index=main_index)
        main_index = normalize_selected_index(menu, main_index) or 0
        k = read_navigation_key()
        if is_series_mode and k in ('LEFT', 'RIGHT'):
            update_current_episode(current_file_idx + (-1 if k == 'LEFT' else 1))
            continue
        if k == 'UP':
            main_index = get_next_selectable(menu, main_index, -1)
            continue
        if k == 'DOWN':
            main_index = get_next_selectable(menu, main_index, 1)
            continue
        if k != 'ENTER':
            continue

        selectable = get_selectable_indices(menu)
        if main_index not in selectable:
            continue
        actual = selectable.index(main_index)

        if actual == 0:
            break
        if actual == 1:
            v_idx = 0
            while True:
                print(CURSOR_HOME, end='', flush=True)
                hide_cursor()
                crop_hint = f"-vf {build_crop_filter_text()}"
                res = settings['video']['resolution']
                vm = [
                    with_ffmpeg_hint(menu_item('H.265 编码', format_on_off(settings['video']['hevc'])), '-c:v hevc -crf 23', settings['video']['hevc']),
                    MENU_SEPARATOR,
                    with_ffmpeg_hint(menu_item('开始时间', settings['video']['ss'] or '00:00:00'), f"-ss {settings['video']['ss']}" if settings['video']['ss'] else None, bool(settings['video']['ss'])),
                    with_ffmpeg_hint(menu_item('结束时间', settings['video']['to'] or '00:00:00'), f"-to {settings['video']['to']}" if settings['video']['to'] else None, bool(settings['video']['to'])),
                    MENU_SEPARATOR,
                    with_ffmpeg_hint(menu_item('裁剪上下黑边', f"{settings['video']['crop_top']}px" if settings['video']['crop_top'] > 0 else '不裁剪'), crop_hint, settings['video']['crop_top'] > 0),
                    with_ffmpeg_hint(menu_item('裁剪左右黑边', f"{settings['video']['crop_left']}px" if settings['video']['crop_left'] > 0 else '不裁剪'), crop_hint, settings['video']['crop_left'] > 0),
                    MENU_SEPARATOR,
                    menu_item('返回主菜单'),
                    '',
                ]
                v_context = []
                if is_series_mode:
                    v_context.append(f"当前针对: {os.path.basename(first_file)} ({current_file_idx+1}/{len(input_paths)})")
                
                render_screen_menu('视频设置', v_context, vm, selected_index=v_idx)
                v_idx = normalize_selected_index(vm, v_idx) or 0
                kk = read_navigation_key()
                if is_series_mode and kk in ('LEFT', 'RIGHT'):
                    s = get_selectable_indices(vm)
                    if v_idx in s:
                        ai = s.index(v_idx)
                        if ai not in (1, 2, 3, 4): # Skip items that use LEFT/RIGHT for adjustment
                            update_current_episode(current_file_idx + (-1 if kk == 'LEFT' else 1))
                            continue
                if kk == 'UP':
                    v_idx = get_next_selectable(vm, v_idx, -1)
                    continue
                if kk == 'DOWN':
                    v_idx = get_next_selectable(vm, v_idx, 1)
                    continue
                if kk == 'BACKSPACE':
                    break
                if kk not in ('LEFT', 'RIGHT', 'ENTER'):
                    continue
                s = get_selectable_indices(vm)
                if v_idx not in s:
                    continue
                ai = s.index(v_idx)
                step = -1 if kk == 'LEFT' else 1
                if ai == 0:
                    settings['video']['hevc'] = not settings['video']['hevc']
                elif ai == 1 and kk in ('LEFT', 'RIGHT'):
                    settings['video']['ss'] = adjust_time_setting(settings['video']['ss'], step * 5)
                elif ai == 2 and kk in ('LEFT', 'RIGHT'):
                    settings['video']['to'] = adjust_time_setting(settings['video']['to'], step * 5)
                elif ai == 3 and kk in ('LEFT', 'RIGHT'):
                    settings['video']['crop_top'] = max(0, min(max(0, first_height // 2 - 1), settings['video']['crop_top'] + step * 2))
                elif ai == 4 and kk in ('LEFT', 'RIGHT'):
                    settings['video']['crop_left'] = max(0, min(max(0, first_width // 2 - 1), settings['video']['crop_left'] + step * 2))
                elif ai == 5:
                    break
        elif actual == 2:
            a_idx = 0
            while True:
                print(CURSOR_HOME, end='', flush=True)
                hide_cursor()
                for s in audio_streams:
                    key = str(s['index'])
                    if key not in settings['audio']['internal_streams']:
                        settings['audio']['internal_streams'][key] = True

                codec_hint = None if settings['audio']['reencode'] else "-c:a copy"

                am = [
                    with_ffmpeg_hint(menu_item('重新编码', format_on_off(settings['audio']['reencode'])), codec_hint, not settings['audio']['reencode']),
                    MENU_SEPARATOR,
                ]

                max_a_idx_w = max((len(str(s['rel_index'] + 1)) for s in audio_streams), default=1)
                for i, s in enumerate(audio_streams):
                    key = str(s['index'])
                    enabled = settings['audio']['internal_streams'].get(key, True)
                    status = format_on_off(enabled)
                    channels = f"{s['channels']}ch" if s['channels'] else '2ch'
                    # Use original relative numbering
                    padded_idx = str(s['rel_index'] + 1).ljust(max_a_idx_w)
                    line = f"#{padded_idx} | {s['codec'].upper()} | {channels} | {s['language']} : {status}"
                    hint = f"-map 0:a:{s['rel_index']}" if enabled else None
                    am.append(with_ffmpeg_hint(line, hint, bool(hint)))

                am.extend([
                    MENU_SEPARATOR,
                    menu_item('返回主菜单'),
                    '',
                ])
                a_context = []
                if is_series_mode:
                    a_context.append(f"当前针对: {os.path.basename(first_file)} ({current_file_idx+1}/{len(input_paths)})")
                
                render_screen_menu('音频设置', a_context, am, selected_index=a_idx)
                a_idx = normalize_selected_index(am, a_idx) or 0

                kk = read_navigation_key()
                if is_series_mode and kk in ('LEFT', 'RIGHT'):
                    update_current_episode(current_file_idx + (-1 if kk == 'LEFT' else 1))
                    continue
                if kk == 'UP':
                    a_idx = get_next_selectable(am, a_idx, -1)
                    continue
                if kk == 'DOWN':
                    a_idx = get_next_selectable(am, a_idx, 1)
                    continue
                if kk == 'BACKSPACE':
                    break
                if kk not in ('LEFT', 'RIGHT', 'ENTER'):
                    continue

                selectable = get_selectable_indices(am)
                if a_idx not in selectable:
                    continue
                selected_line = ANSI_ESCAPE.sub('', am[a_idx]).strip()
                if re.search(r'重新编码\s*:', selected_line):
                    settings['audio']['reencode'] = not settings['audio']['reencode']
                elif re.search(r'返回主菜单$', selected_line):
                    break
                else:
                    # Identify stream by its position in the selectable list (skipping first 1: '重新编码')
                    idx_in_sel = selectable.index(a_idx)
                    if idx_in_sel >= 1:
                        stream_pos = idx_in_sel - 1
                        if 0 <= stream_pos < len(audio_streams):
                            skey = str(audio_streams[stream_pos]['index'])
                            cur = settings['audio']['internal_streams'].get(skey, True)
                            settings['audio']['internal_streams'][skey] = not cur

        elif actual == 3:
            s_idx = 0
            while True:
                print(CURSOR_HOME, end='', flush=True)
                hide_cursor()
                for s in subtitle_streams:
                    key = str(s['index'])
                    if key not in settings['subtitle']['internal_streams']:
                        settings['subtitle']['internal_streams'][key] = True

                if settings['subtitle']['mode'] == 'external' and not settings['subtitle']['files']:
                    settings['subtitle']['mode'] = 'internal'

                enabled_internal_pos = [pos for pos, s in enumerate(subtitle_streams) if settings['subtitle']['internal_streams'].get(str(s['index']), True)]
                selected_internal_pos = enabled_internal_pos[0] if enabled_internal_pos else None
                enabled_external_idx = [i for i in range(len(settings['subtitle']['files'])) if settings['subtitle']['external_streams'].get(str(i), True)]
                selected_external_idx = enabled_external_idx[0] if enabled_external_idx else None

                burn_status = format_on_off(settings['subtitle']['burn_in'])
                burn_hint = '-sn' if settings['subtitle']['burn_in'] else None

                import_value = f"{len(settings['subtitle']['files'])} 个文件" if settings['subtitle']['files'] else '未导入'
                import_hint = None
                if settings['subtitle']['mode'] == 'external':
                    if settings['subtitle']['burn_in'] and selected_external_idx is not None:
                        import_hint = f"-vf subtitles={os.path.basename(settings['subtitle']['files'][selected_external_idx])}"
                    elif not settings['subtitle']['burn_in'] and enabled_external_idx:
                        import_hint = '-i <字幕文件> -map N:s:0'

                sm = [
                    with_ffmpeg_hint(menu_item('烧制字幕', burn_status), burn_hint, bool(burn_hint)),
                    with_ffmpeg_hint(menu_item('导入字幕', import_value), import_hint, bool(import_hint)),
                    MENU_SEPARATOR,
                ]

                if settings['subtitle']['mode'] == 'internal':
                    # First pass: calculate all labels and find max width
                    subtitle_items_data = []
                    max_idx_w = max((len(str(s['rel_index'] + 1)) for s in subtitle_streams), default=1)
                    max_label_w = 0
                    
                    for pos, s in enumerate(subtitle_streams):
                        # Use ORIGINAL index for display to satisfy user expectation
                        padded_idx = str(s['rel_index'] + 1).ljust(max_idx_w)
                        # Use the actual string found in parentheses (e.g., 'srt' instead of 'subrip')
                        raw_name = s['raw_display_name']
                        lang_name = get_full_language_name(s['language'])
                        if s['title'] and s['title'].lower() != lang_name.lower():
                            sub_display_name = f"{lang_name}, {s['title']}"
                        else:
                            sub_display_name = lang_name
                        
                        full_label = f"#{padded_idx} .{raw_name} - {sub_display_name}"
                        max_label_w = max(max_label_w, get_display_width(full_label))
                        subtitle_items_data.append((pos, s, full_label))
                    
                    # Second pass: render with aligned padding
                    for pos, s, full_label in subtitle_items_data:
                        key = str(s['index'])
                        enabled = settings['subtitle']['internal_streams'].get(key, True)
                        status = format_on_off(enabled)
                        
                        # Pad the entire label part to align the colon ':'
                        padded_full_label = pad_display(full_label, max_label_w)
                        line = f"{padded_full_label} : {status}"
                        
                        hint = None
                        if enabled:
                            if settings['subtitle']['burn_in'] and selected_internal_pos == pos:
                                hint = f"-vf subtitles=input:si={s['rel_index']}"
                            elif not settings['subtitle']['burn_in']:
                                hint = f"-map 0:s:{s['rel_index']}"
                        
                        sm.append(with_ffmpeg_hint(line, hint, bool(hint)))
                else:
                    for i, f in enumerate(settings['subtitle']['files']):
                        enabled = settings['subtitle']['external_streams'].get(str(i), True)
                        status = format_on_off(enabled)
                        line = menu_item(f"[{i}] {os.path.basename(f)}", status)
                        hint = None
                        if enabled:
                            if settings['subtitle']['burn_in'] and selected_external_idx == i:
                                hint = f"-vf subtitles={os.path.basename(f)}"
                            elif not settings['subtitle']['burn_in']:
                                hint = f"-i {os.path.basename(f)} -map N:s:0"
                        sm.append(with_ffmpeg_hint(line, hint, bool(hint)))

                sm.append('')
                sm.append(menu_item('返回主菜单'))
                sm.append('')
                s_context = []
                if is_series_mode:
                    s_context.append(f"当前针对: {os.path.basename(first_file)} ({current_file_idx+1}/{len(input_paths)})")
                
                render_screen_menu('字幕设置', s_context, sm, selected_index=s_idx, footer_hint='↑↓ 选择   Shift+↑↓ 排序   Enter 执行')
                s_idx = normalize_selected_index(sm, s_idx) or 0

                kk = read_navigation_key()
                if is_series_mode and kk in ('LEFT', 'RIGHT'):
                    update_current_episode(current_file_idx + (-1 if kk == 'LEFT' else 1))
                    continue
                if kk == 'UP':
                    s_idx = get_next_selectable(sm, s_idx, -1)
                    continue
                if kk == 'DOWN':
                    s_idx = get_next_selectable(sm, s_idx, 1)
                    continue
                
                # Handle stream reordering
                if kk in ('SHIFT_UP', 'SHIFT_DOWN'):
                    selectable = get_selectable_indices(sm)
                    if s_idx not in selectable:
                        continue
                    
                    idx_in_sel = selectable.index(s_idx)
                    # Skip first two selectable items: '烧制字幕' and '导入字幕'
                    if idx_in_sel >= 2:
                        pos = idx_in_sel - 2
                        if settings['subtitle']['mode'] == 'internal':
                            if 0 <= pos < len(subtitle_streams):
                                target_idx = pos - 1 if kk == 'SHIFT_UP' else pos + 1
                                if 0 <= target_idx < len(subtitle_streams):
                                    subtitle_streams[pos], subtitle_streams[target_idx] = subtitle_streams[target_idx], subtitle_streams[pos]
                                    # Follow the moved item
                                    s_idx = selectable[selectable.index(s_idx) + (target_idx - pos)]
                        elif settings['subtitle']['mode'] == 'external':
                            if 0 <= pos < len(settings['subtitle']['files']):
                                target_idx = pos - 1 if kk == 'SHIFT_UP' else pos + 1
                                if 0 <= target_idx < len(settings['subtitle']['files']):
                                    # Swap files
                                    files = settings['subtitle']['files']
                                    files[pos], files[target_idx] = files[target_idx], files[pos]
                                    # Swap states in external_streams
                                    states = settings['subtitle']['external_streams']
                                    s1, s2 = str(pos), str(target_idx)
                                    v1, v2 = states.get(s1, True), states.get(s2, True)
                                    states[s1], states[s2] = v2, v1
                                    # Follow the moved item
                                    s_idx = selectable[selectable.index(s_idx) + (target_idx - pos)]
                    continue

                if kk == 'BACKSPACE':
                    break
                if kk not in ('LEFT', 'RIGHT', 'ENTER'):
                    continue

                selectable = get_selectable_indices(sm)
                if s_idx not in selectable:
                    continue
                selected_line = ANSI_ESCAPE.sub('', sm[s_idx]).strip()
                if re.search(r'烧制字幕\s*:', selected_line):
                    settings['subtitle']['burn_in'] = not settings['subtitle']['burn_in']
                    if settings['subtitle']['burn_in']:
                        d = settings['subtitle']['internal_streams'] if settings['subtitle']['mode'] == 'internal' else settings['subtitle']['external_streams']
                        found = False
                        for key in list(d.keys()):
                            if d[key] and not found:
                                found = True
                            else:
                                d[key] = False
                elif re.search(r'导入字幕\s*:', selected_line):
                    if kk in ('RIGHT', 'ENTER'):
                        files = choose_files('选择字幕文件', [('字幕文件', '*.srt *.ass *.ssa *.vtt *.sup'), ('所有文件', '*.*')])
                        if files:
                            settings['subtitle']['mode'] = 'external'
                            settings['subtitle']['files'] = files
                            settings['subtitle']['external_streams'] = {str(i): (not settings['subtitle']['burn_in'] or i == 0) for i in range(len(files))}
                elif re.search(r'返回主菜单$', selected_line):
                    break
                else:
                    idx_in_sel = selectable.index(s_idx)
                    if idx_in_sel >= 2:
                        pos = idx_in_sel - 2
                        if settings['subtitle']['mode'] == 'internal':
                            if 0 <= pos < len(subtitle_streams):
                                skey = str(subtitle_streams[pos]['index'])
                                if settings['subtitle']['burn_in']:
                                    for key in settings['subtitle']['internal_streams']:
                                        settings['subtitle']['internal_streams'][key] = False
                                    settings['subtitle']['internal_streams'][skey] = True
                                else:
                                    cur = settings['subtitle']['internal_streams'].get(skey, True)
                                    settings['subtitle']['internal_streams'][skey] = not cur
                        elif settings['subtitle']['mode'] == 'external':
                            if 0 <= pos < len(settings['subtitle']['files']):
                                fkey = str(pos)
                                if settings['subtitle']['burn_in']:
                                    for key in settings['subtitle']['external_streams']:
                                        settings['subtitle']['external_streams'][key] = False
                                    settings['subtitle']['external_streams'][fkey] = True
                                else:
                                    cur = settings['subtitle']['external_streams'].get(fkey, True)
                                    settings['subtitle']['external_streams'][fkey] = not cur
        elif actual == 4:
            hide_cursor()
            # Use first_file for preview as a representative
            ext_sub = None
            if is_series_mode and settings['subtitle']['mode'] == 'external' and settings['subtitle']['files']:
                if current_file_idx < len(settings['subtitle']['files']):
                    ext_sub = settings['subtitle']['files'][current_file_idx]
            preview_command = build_ffmpeg_command(first_file, audio_streams, subtitle_streams, series_mode=is_series_mode, external_subtitle=ext_sub)
            cmd_lines = format_preview_lines(preview_command, input_file=first_file, output_file=preview_command[-1])
            
            # Render the full command box with a title and no scrolling
            render_preview_box(cmd_lines, title='FFmpeg 命令预览')
            
            # Wait for user to read, then clear and return
            read_navigation_key()
            os.system('cls' if os.name == 'nt' else 'clear')

    show_cursor()
    try:
        total_count = len(input_paths)
        for i, path in enumerate(input_paths):
            if is_series_mode:
                os.makedirs(os.path.join(os.path.dirname(path), 'Edited'), exist_ok=True)
            
            ext_sub = None
            if is_series_mode and settings['subtitle']['mode'] == 'external':
                if i < len(settings['subtitle']['files']):
                    ext_sub = settings['subtitle']['files'][i]
            
            command = build_ffmpeg_command(path, audio_streams, subtitle_streams, series_mode=is_series_mode, external_subtitle=ext_sub)
            
            # Calculate effective duration
            start_sec = parse_time_to_seconds(settings['video']['ss'])
            end_sec = parse_time_to_seconds(settings['video']['to'])
            file_duration = get_video_duration(path)
            
            calc_duration = float(file_duration)
            if end_sec is not None and end_sec > 0:
                calc_duration = float(end_sec)
            if start_sec is not None and start_sec > 0:
                calc_duration -= float(start_sec)
            calc_duration = max(0.0, calc_duration)

            prefix = f"[{i+1}/{total_count}] {os.path.basename(path)}"
            run_ffmpeg_with_progress(command, calc_duration, title_prefix=prefix)
        
        # Wait for keypress to exit, no text prompt
        read_navigation_key()

    except Exception as e:
        show_cursor()
        print(f'\n处理失败: {e}')
        input('\n按回车键退出...')


if __name__ == '__main__':
    try:
        hide_cursor()
        process_files()
    except Exception as e:
        show_cursor()
        print(f'发生错误: {e}')
        input('\n按回车键退出...')
    finally:
        show_cursor()
