# FFmpeg 相关：探测函数、命令构建、进度 UI

import os

import re

import sys

import time

import shutil

import threading

import json

import ctypes

import subprocess

from collections import deque



from rich.console import Group

from rich.text import Text



from ui.console import (

    ANSI_ESCAPE, register_child_process,

    unregister_child_process, _shutdown_requested, UI_COLORS,

    _console_has_input, _console_read_key,

)

from ui.display import get_display_width, trim_to_display_width, build_top_border

from core.helpers import format_hms

from core.logger import log_ffmpeg_start, log_ffmpeg_progress, log_ffmpeg_end, log_ffmpeg_error

import ui.live as live





class FFmpegUserTerminated(Exception):

    """Raised when the user explicitly terminates ffmpeg via the UI terminate button."""

    pass





def _copy_text_to_clipboard(text: str) -> None:

    """Copy text to Windows clipboard via PowerShell Set-Clipboard (best-effort)."""

    if not text:

        return

    try:

        # PowerShell handles Unicode correctly via base64 round-trip

        import base64

        encoded = base64.b64encode(text.encode('utf-16-le')).decode('ascii')

        ps_cmd = (

            'Set-Clipboard -Value '

            f'([System.Text.Encoding]::Unicode.GetString('

            f'[System.Convert]::FromBase64String("{encoded}")))'

        )

        subprocess.run(

            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],

            capture_output=True,

            creationflags=subprocess.CREATE_NO_WINDOW,

            timeout=10,

        )

    except Exception:

        pass  # clipboard is best-effort





def _make_paths_clickable(text: str) -> str:

    """将文本中的 Windows 文件路径转换为 OSC 8 终端超链接。"""

    _path_re = re.compile(

        r'([A-Za-z]:[^"]+\.(?:mp4|mkv|avi|mov|flv|wmv|webm|ts|m2ts|'

        r'srt|ass|ssa|sub|sup|vtt|'

        r'aac|mp3|flac|wav|opus|ogg|ac3|eac3|dts|'

        r'jpg|jpeg|png|bmp|gif|webp))(?=["\s]|$)',

        re.IGNORECASE

    )

    _esc = chr(27)

    _bs = chr(92)

    def _replace(m):

        raw = m.group(1)

        uri = raw.replace(_bs, '/')

        return f'{_esc}]8;;file:///{uri}{_esc}{_bs}{raw}{_esc}]8;;{_esc}{_bs}'

    return _path_re.sub(_replace, text)





# 剥离所有终端转义序列（ANSI CSI + OSC 8 超链接），用于宽度计算

_ALL_TERMINAL_ESC = re.compile(

    r'(?:\x1b\]8;[^;]*;[^\x1b]*\x1b\\)'   # OSC 8

    r'|(?:\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))'  # ANSI CSI

)





def _split_escaped(text: str, max_w: int, path_aware: bool = False,

                   _display_width_fn=None) -> int:

    """对含终端转义序列的文本做宽度安全的分行切分。



    返回 text 中的切分位置（保证不切断转义序列）。

    path_aware=True 时优先在目录分隔符处断开。

    """

    if _display_width_fn is None:

        _display_width_fn = get_display_width



    # 构建 clean_idx → escaped_idx 映射

    cmap = []

    esc = chr(27)

    bs = chr(92)

    i = 0

    while i < len(text):

        ch = text[i]

        if ch == esc:

            if i + 2 < len(text) and text[i + 1] == ']' and text[i + 2] == '8':

                end = text.find(esc + bs, i + 3)

                if end >= 0:

                    i = end + 2

                    continue

            j = i + 1

            while j < len(text) and text[j] not in '@A-Z[\\]^_`a-z{|}~':

                j += 1

            i = j + 1

            continue

        cmap.append(i)

        i += 1



    clean = ''.join(text[p] for p in cmap)



    if _display_width_fn(clean) <= max_w:

        return len(text)



    # 二分搜索（在 clean 文本上）

    lo, hi = 1, len(clean)

    while lo < hi:

        mid = (lo + hi + 1) // 2

        if _display_width_fn(clean[:mid]) <= max_w:

            lo = mid

        else:

            hi = mid - 1

    clean_split = lo



    # 路径感知：优先在目录分隔符处断开

    if path_aware:

        search_start = max(clean_split - max_w // 4, 0)

        for ci in range(clean_split - 1, search_start - 1, -1):

            if clean[ci] in ('\\', '/'):

                clean_split = ci + 1

                break



    if clean_split >= len(cmap):

        return len(text)

    return cmap[clean_split]





def _send_notification(title: str, message: str) -> None:

    """发送 Windows 桌面通知（best-effort）。"""

    try:

        from winotify import Notification

        Notification(app_id='MovieEditor', title=title, msg=message).show()

    except Exception:

        pass





# ---- 进度 UI helpers ----

_SPEED_EMA_ALPHA = 0.1

_PROGRESS_POLL_SEC = 0.05

_PROGRESS_LOG_INTERVAL_MS = 3000

_PROGRESS_LOG_TOLERANCE_MS = 60

_FFPROBE_TIMEOUT = 30  # seconds: prevent hangs on damaged / network files



# ---- Windows 进程暂停/恢复（挂起所有线程 → CPU = 0%） ----

_TH32CS_SNAPTHREAD = 0x00000004

_THREAD_SUSPEND_RESUME = 0x0002

_THREAD_QUERY_INFORMATION = 0x0040

_process_pause_lock = threading.Lock()

_process_paused = False





class _THREADENTRY32(ctypes.Structure):

    _fields_ = [

        ("dwSize", ctypes.c_ulong),

        ("cntUsage", ctypes.c_ulong),

        ("th32ThreadID", ctypes.c_ulong),

        ("th32OwnerProcessID", ctypes.c_ulong),

        ("tpBasePri", ctypes.c_long),

        ("tpDeltaPri", ctypes.c_long),

        ("dwFlags", ctypes.c_ulong),

    ]





def _suspend_process(process):

    """挂起进程的所有线程 → CPU 利用率归零"""

    if os.name != 'nt' or process.poll() is not None:

        return

    try:

        snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)

        if snapshot == -1:

            return

        te = _THREADENTRY32()

        te.dwSize = ctypes.sizeof(_THREADENTRY32)

        if ctypes.windll.kernel32.Thread32First(snapshot, ctypes.byref(te)):

            while True:

                if te.th32OwnerProcessID == process.pid:

                    h = ctypes.windll.kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, te.th32ThreadID)

                    if h:

                        ctypes.windll.kernel32.SuspendThread(h)

                        ctypes.windll.kernel32.CloseHandle(h)

                if not ctypes.windll.kernel32.Thread32Next(snapshot, ctypes.byref(te)):

                    break

        ctypes.windll.kernel32.CloseHandle(snapshot)

    except (OSError, AttributeError):

        pass





def _resume_process(process):

    """恢复进程的所有线程"""

    if os.name != 'nt' or process.poll() is not None:

        return

    try:

        snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)

        if snapshot == -1:

            return

        te = _THREADENTRY32()

        te.dwSize = ctypes.sizeof(_THREADENTRY32)

        if ctypes.windll.kernel32.Thread32First(snapshot, ctypes.byref(te)):

            while True:

                if te.th32OwnerProcessID == process.pid:

                    h = ctypes.windll.kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, te.th32ThreadID)

                    if h:

                        ctypes.windll.kernel32.ResumeThread(h)

                        ctypes.windll.kernel32.CloseHandle(h)

                if not ctypes.windll.kernel32.Thread32Next(snapshot, ctypes.byref(te)):

                    break

        ctypes.windll.kernel32.CloseHandle(snapshot)

    except (OSError, AttributeError):

        pass





def _reset_ffmpeg_pause(process):

    """恢复 ffmpeg 进程（如果已暂停）"""

    global _process_paused

    with _process_pause_lock:

        if _process_paused:

            _resume_process(process)

            _process_paused = False





def _toggle_ffmpeg_pause(process):

    """切换 ffmpeg 暂停：挂起/恢复所有线程"""

    global _process_paused

    with _process_pause_lock:

        if _process_paused:

            _resume_process(process)

            _process_paused = False

        else:

            _suspend_process(process)

            _process_paused = True

    return _process_paused





def _terminate_ffmpeg_via_stdin(process, stdin_lock):

    """Send 'q' to ffmpeg stdin for graceful termination, then close stdin."""

    with stdin_lock:

        try:

            if process.stdin and not process.stdin.closed:

                process.stdin.write('q')

                process.stdin.flush()

        except (IOError, OSError):

            pass

        finally:

            try:

                if process.stdin and not process.stdin.closed:

                    process.stdin.close()

            except (IOError, OSError):

                pass





def _force_terminate(process, wait_timeout=3, term_timeout=2):

    """Wait for process to exit; escalate to terminate then kill."""

    try:

        process.wait(timeout=wait_timeout)

    except subprocess.TimeoutExpired:

        try:

            process.terminate()

            process.wait(timeout=term_timeout)

        except (OSError, subprocess.TimeoutExpired):

            try:

                process.kill()

            except OSError:

                pass





# ---- 探测函数 ----

def get_video_resolution(file_path: str) -> tuple[int, int]:

    try:

        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', file_path]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',

                               timeout=_FFPROBE_TIMEOUT)

        out = result.stdout.strip()

        if not out:

            return 0, 0

        w, h = map(int, out.split(','))

        return w, h

    except (subprocess.SubprocessError, subprocess.TimeoutExpired, ValueError):

        return 0, 0





def get_video_duration(file_path: str) -> float:

    try:

        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace',

                               timeout=_FFPROBE_TIMEOUT)

        return float(result.stdout.strip())

    except (subprocess.SubprocessError, subprocess.TimeoutExpired, ValueError):

        return 0





def _probe_streams_json(file_path: str, selector: str, entries: str) -> list[dict]:

    for extra_args in [['-probesize', '50M', '-analyzeduration', '100M'], []]:

        try:

            cmd = ['ffprobe', '-v', 'quiet'] + extra_args + [

                '-select_streams', selector,

                '-show_entries', entries,

                '-of', 'json', file_path

            ]

            result = subprocess.run(cmd, capture_output=True, check=True, timeout=_FFPROBE_TIMEOUT)

            stdout_text = result.stdout.decode('utf-8', errors='replace')

            data = json.loads(stdout_text or '{}')

            return data.get('streams', [])

        except FileNotFoundError:

            print(f"错误: ffprobe 未找到，请确保 FFmpeg 已安装并在 PATH 中", file=sys.stderr)

            return []

        except (subprocess.SubprocessError, json.JSONDecodeError, UnicodeDecodeError):

            continue

    return []





def get_audio_streams(file_path: str) -> list[dict]:

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





def get_subtitle_streams(file_path: str) -> list[dict]:

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

        result = subprocess.run(cmd, capture_output=True, timeout=_FFPROBE_TIMEOUT)

        stderr_content = result.stderr.decode('utf-8', errors='replace')



        for s in streams:

            # Improved regex to handle language tags like Stream #0:2(eng)

            pattern = rf"Stream #\d+:{s['index']}.*?Subtitle: [^(]+?\((\w+)\)"

            match = re.search(pattern, stderr_content)

            if match:

                s['raw_display_name'] = match.group(1)

            else:

                s['raw_display_name'] = s['codec']

    except (subprocess.SubprocessError, subprocess.TimeoutExpired, UnicodeDecodeError):

        for s in streams:

            s['raw_display_name'] = s['codec']



    return streams





def format_preview_lines(command: list[str]) -> list[str]:

    lines = [f'{command[0]}']

    i = 1



    while i < len(command):

        token = str(command[i])



        if token.startswith('-'):

            line = f'  {token}'

            if i + 1 < len(command) and not str(command[i + 1]).startswith('-'):

                arg = str(command[i + 1])

                if any(c.isspace() for c in arg):

                    arg = f'"{arg}"'

                line += f' {arg}'

                i += 1

            lines.append(line)

        else:

            if any(c.isspace() for c in token):

                token = f'"{token}"'

            lines.append(f'  {token}')

        i += 1



    return lines







# ---- 进度 UI ----

def run_ffmpeg_with_progress(command: list[str], total_duration: float, title_prefix: str = '', is_last: bool = False, episode_progress: str = '', finish_title: str = '') -> None:

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

    except (ValueError, IndexError):

        pass



    # Format command lines vertically

    cmd_lines_raw = format_preview_lines(command)



    # 日志：记录启动信息

    run_id = log_ffmpeg_start(command, input_file, output_file, total_duration, title_prefix)



    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    process = subprocess.Popen(exec_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='replace', creationflags=creationflags)

    register_child_process(process)



    start_time = time.time()

    stderr_tail = deque(maxlen=10)



    def collect_err():

        try:

            if process.stderr:

                for line in process.stderr:

                    clean = line.strip()

                    if clean:

                        stderr_tail.append(clean)

        except (IOError, OSError, UnicodeDecodeError):

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

                        except (ValueError, IndexError):

                            pass

                    if 'speed=' in line:

                        try:

                            sp_str = line.split('speed=', 1)[1].split('x', 1)[0].strip()

                            if sp_str != 'N/A':

                                cur = float(sp_str)

                                with state['lock']:

                                    state['speed'] = _SPEED_EMA_ALPHA * cur + (1 - _SPEED_EMA_ALPHA) * (state['speed'] if state['speed'] > 0 else cur)

                                    if cur > 0.01:

                                        state['started'] = True

                        except (ValueError, IndexError):

                            pass

                    if 'progress=end' in line:

                        break

        except (IOError, OSError, ValueError, UnicodeDecodeError):

            pass

        finally:

            state['done'] = True



    t_read = threading.Thread(target=reader, daemon=True)

    t_read.start()



    last_plain_text = '正在初始化进程...'



    ffmpeg_state = {

        'paused': False,

        'terminated': False,

        'notify': False,

        'selected_button': 0,  # 0=pause/resume, 1=terminate, 2=copy, 3=notify

        'copy_flash': 0,

        'cmd_scroll': 0,

    }

    stdin_lock = threading.Lock()



    # Cache for pre-wrapped command lines (static text, only changes with terminal width)

    wrap_cache = {'inner_w': -1, 'wrapped': []}



    def _update_wrap_cache(term_w: int, inner_w: int, code_indent: str):
        if inner_w != wrap_cache['inner_w']:
            avail_w = inner_w - len(code_indent) - 2

            wrapped = []
            for raw in cmd_lines_raw:
                plain = ANSI_ESCAPE.sub('', raw)
                plain = _make_paths_clickable(plain)
                clean_plain = _ALL_TERMINAL_ESC.sub('', plain)
                stripped = clean_plain.lstrip()
                base_indent = len(clean_plain) - len(stripped)
                cont_indent = base_indent
                has_path = False
                if stripped.startswith('-'):
                    parts = stripped.split(None, 1)
                    if len(parts) > 1:
                        cont_indent = base_indent + len(parts[0]) + 1
                        arg = parts[1]
                        if arg and arg[0] in ('"', "'"):
                            cont_indent += 1
                        has_path = bool(re.search(r'[A-Za-z]:\\', clean_plain))
                else:
                    if stripped and stripped[0] in ('"', "'"):
                        cont_indent = base_indent + 1
                    has_path = bool(re.search(r'[A-Za-z]:\\', clean_plain))

                if get_display_width(clean_plain) <= avail_w:
                    wrapped.append(plain)
                else:
                    text = plain
                    split = _split_escaped(text, avail_w, path_aware=has_path)
                    wrapped.append(text[:split])
                    text = text[split:]
                    prefix = ' ' * cont_indent
                    prefix_w = cont_indent
                    cont_avail = avail_w - prefix_w
                    if cont_avail < 10:
                        prefix = ' ' * base_indent
                        prefix_w = base_indent
                        cont_avail = avail_w - prefix_w
                    if cont_avail < 1:
                        prefix = ''
                        prefix_w = 0
                        cont_avail = avail_w
                    while text and get_display_width(_ALL_TERMINAL_ESC.sub('', text)) > cont_avail:
                        split = _split_escaped(text, cont_avail, path_aware=has_path)
                        if split == 0:
                            break
                        wrapped.append(prefix + text[:split])
                        text = text[split:]
                    if text:
                        wrapped.append(prefix + text)

            wrap_cache['inner_w'] = inner_w
            wrap_cache['wrapped'] = wrapped
        return wrap_cache['wrapped']




    def _check_key_input():

        """Non-blocking keyboard check for button navigation (LEFT/RIGHT/UP/DOWN/ENTER)."""

        while _console_has_input():

            key, _ = _console_read_key()

            if key is None:

                break

            if key == b'\xe0':

                # Arrow key prefix on Windows

                if _console_has_input():

                    arrow, _ = _console_read_key()

                    if arrow == b'K':  # LEFT

                        ffmpeg_state['selected_button'] = max(0, ffmpeg_state['selected_button'] - 1)

                    elif arrow == b'M':  # RIGHT

                        ffmpeg_state['selected_button'] = min(3, ffmpeg_state['selected_button'] + 1)

                    elif arrow == b'H':  # UP

                        ffmpeg_state['cmd_scroll'] = max(0, ffmpeg_state['cmd_scroll'] - 1)

                    elif arrow == b'P':  # DOWN

                        term_h = shutil.get_terminal_size((120, 30)).lines

                        has_btns = not ffmpeg_state.get('terminated', False)

                        _fixed = 7 + (1 if has_btns else 0)

                        max_visible = max(3, term_h - _fixed - 6)

                        max_scroll = max(0, len(wrap_cache['wrapped']) - max_visible)

                        ffmpeg_state['cmd_scroll'] = min(max_scroll, ffmpeg_state['cmd_scroll'] + 1)

                continue

            if key in (b'\r', b'\n'):  # ENTER

                btn = ffmpeg_state['selected_button']

                if btn == 0:  # Pause / Resume

                    now_paused = _toggle_ffmpeg_pause(process)

                    ffmpeg_state['paused'] = now_paused

                elif btn == 1:  # Copy command to clipboard

                    parts = []

                    for a in command:

                        s = str(a)

                        if any(c.isspace() for c in s):

                            s = f'"{s}"'

                        parts.append(s)

                    cmd_str = ' '.join(parts)

                    _copy_text_to_clipboard(cmd_str)

                    ffmpeg_state['copy_flash'] = time.time()

                elif btn == 2:  # Toggle notification

                    ffmpeg_state['notify'] = not ffmpeg_state['notify']

                elif btn == 3:  # Terminate

                    if not ffmpeg_state['terminated']:

                        ffmpeg_state['terminated'] = True

                        state['done'] = True

                        if ffmpeg_state['paused']:

                            _reset_ffmpeg_pause(process)

                            ffmpeg_state['paused'] = False

                        _terminate_ffmpeg_via_stdin(process, stdin_lock)

                continue



    def build_interface_lines(progress_text, title, is_finished, pct=0, ffmpeg_state=None, output_file=None):

        """Build the interface as a single box for live.update()."""

        term_w, term_h = shutil.get_terminal_size((120, 30))

        width = max(70, min(140, term_w - 2))

        inner_w = width - 2

        text_indent = '    '   # 4 spaces: progress text & buttons

        bar_indent = '  '      # 2 spaces: progress bar

        code_indent = '  '     # 2 spaces: separator & command lines

        muted = UI_COLORS['muted']

        reset = UI_COLORS['reset']

        dim = muted if is_finished else ''



        def _pad(content_vis):

            return ' ' * max(0, inner_w - content_vis)



        def _box_bottom():

            return f"  ╰{'─' * inner_w}╯"



        def _empty():

            return f"  │{' ' * inner_w}│"



        def _separator():

            seg_w = inner_w - len(code_indent) - 2  # indent on left, 2-space pad on right

            seg = '─' * max(1, seg_w)

            return f"  │{code_indent}{muted}{seg}{reset}{' ' * 2}│"



        def _text_line(display, plain_len):

            return f"  │{text_indent}{display}{' ' * max(0, inner_w - len(text_indent) - plain_len)}│"



        # === Build ===

        lines = []

        has_buttons = ffmpeg_state and not is_finished



        # 1. Title

        lines.append(build_top_border(inner_w, title))

        # 2. Empty

        lines.append(_empty())

        # 3. Progress text

        bold = "\033[1m" if is_finished else ""

        p_disp = f"\033[38;2;205;214;244m{bold}{progress_text}\033[0m" if not is_finished else f"{dim}{progress_text}{reset}"

        lines.append(_text_line(p_disp, get_display_width(progress_text)))



        # 4. Progress bar — small box, muted borders, left-aligned at bar_indent

        bar_pct = pct if not is_finished else 100

        bar_inner = inner_w - len(bar_indent) - 6  # bar_indent + bar_box(╭content╮) + right_pad(2)

        bar_inner = max(1, bar_inner)

        filled = int(bar_inner * min(bar_pct, 100) / 100)

        empty = bar_inner - filled

        if is_finished:

            bar_str = f"{dim}{'█' * filled}{'░' * empty}{reset}"

        else:

            bar_str = f"\033[38;2;137;180;250m{'█' * filled}\033[38;2;108;112;134m{'░' * empty}\033[0m"

        bar_plain = filled + empty

        # Top:  ╭──────────╮

        top_w = bar_plain + 2  # +2 for inner spaces

        bar_full = top_w + 2  # including ╭ and ╮

        lines.append(f"  │{bar_indent}{muted}╭{'─' * top_w}╮{reset}{' ' * max(0, inner_w - len(bar_indent) - bar_full)}│")

        # Bar:  │ ░░░░░░░░ │

        lines.append(f"  │{bar_indent}{muted}│{reset} {bar_str} {muted}│{reset}{' ' * max(0, inner_w - len(bar_indent) - bar_full)}│")

        # Bottom:  ╰──────────╯

        lines.append(f"  │{bar_indent}{muted}╰{'─' * top_w}╯{reset}{' ' * max(0, inner_w - len(bar_indent) - bar_full)}│")



        # 6. Buttons

        if has_buttons:

            is_paused = ffmpeg_state.get('paused', False)

            notify_on = ffmpeg_state.get('notify', False)

            sel = ffmpeg_state.get('selected_button', 0)



            p_label = '恢复任务' if is_paused else '暂停任务'

            copy_flash = ffmpeg_state.get('copy_flash', 0)

            c_label = '复制成功' if copy_flash and time.time() - copy_flash < 1.5 else '复制命令'

            n_label = '关闭通知' if notify_on else '开启通知'

            t_label = '终止任务'



            ESC = chr(27)

            BOLD = f"{ESC}[97;1m"

            RESET_BTN = f"{ESC}[0m"



            def _btn(label, idx):

                if idx == sel:

                    return f"[{BOLD}{label}{RESET_BTN}]"

                return f" {label} "



            left_part = "  " + _btn(p_label, 0) + "   " + _btn(c_label, 1) + "   " + _btn(n_label, 2)

            right_part = _btn(t_label, 3) + "  "

            left_w = get_display_width(left_part)

            right_w = get_display_width(right_part)

            mid_pad = max(3, inner_w - left_w - right_w)

            btn_row = f"  │{left_part}{' ' * mid_pad}{right_part}│"

            lines.append(btn_row)

            lines.append(_empty())



        # 7. Separator

        lines.append(_separator())

        # 8. Empty

        lines.append(_empty())



        # 9. Command lines (cached wrapping — static text only re-wrapped when terminal width changes)

        fixed = 7 + (1 if has_buttons else 0)

        max_visible = max(3, term_h - fixed - 6)



        wrapped = _update_wrap_cache(term_w, inner_w, code_indent)



        cmd_scroll = 0

        if ffmpeg_state:

            cmd_scroll = ffmpeg_state.get('cmd_scroll', 0)



        max_scroll = max(0, len(wrapped) - max_visible)

        cmd_scroll = min(cmd_scroll, max_scroll)



        ellipsis_line = f"  │{code_indent}{muted}···{_pad(len(code_indent) + 3)}{reset}│"

        if cmd_scroll > 0:

            lines.append(ellipsis_line)



        _esc = chr(27)
        _green_out = f"{_esc}[38;2;166;227;161m"
        for seg in wrapped[cmd_scroll : cmd_scroll + max_visible]:
            sv = get_display_width(_ALL_TERMINAL_ESC.sub('', seg))
            if is_finished and output_file and output_file in seg:
                lines.append(f"  │{code_indent}{_green_out}{seg}{reset}{_pad(len(code_indent) + sv)}│")
            else:
                lines.append(f"  │{code_indent}{muted}{seg}{reset}{_pad(len(code_indent) + sv)}│")


        if cmd_scroll + max_visible < len(wrapped):

            lines.append(ellipsis_line)



        # 10. Bottom

        lines.append(_empty())

        lines.append(_box_bottom())



        return Group(*[Text.from_ansi(line) for line in lines])





    try:



        progress_tag = f' ({episode_progress})' if episode_progress else ''

        display_title = f"正在运行{progress_tag}: {title_prefix}" if title_prefix else f"正在运行{progress_tag}"

        live.update(build_interface_lines(last_plain_text, display_title, False, 0, ffmpeg_state, output_file=output_file))

        cur_pct = 0.0



        while not state['done']:

            _check_key_input()



            if _shutdown_requested.is_set():

                state['done'] = True

                break



            now = time.time()

            elapsed = now - start_time



            with state['lock']:

                curr_ms = state['current_ms']

                spd = state['speed']

                has_started = state['started']



            if not has_started:

                plain_text = '正在初始化进程...'

                cur_pct = 0.0

            else:

                curr_sec = curr_ms / 1000000.0

                if total_duration > 0:

                    cur_pct = min(100.0, curr_sec / total_duration * 100)

                    rem = max(0, total_duration - curr_sec)

                    eta = rem / spd if spd > 0.01 else 0

                    plain_text = f'进度：{format_hms(curr_sec)}/{format_hms(total_duration)} ({cur_pct:>6.2f}%) | 速度：{spd:.2f}x | 用时：{format_hms(elapsed)} | 剩余：{format_hms(eta)}'

                else:

                    plain_text = f'进度：{format_hms(curr_sec)} | 速度：{spd:.2f}x | 用时：{format_hms(elapsed)}'



            last_plain_text = plain_text



            live.update(build_interface_lines(plain_text, display_title, False, cur_pct, ffmpeg_state, output_file=output_file))



            # 日志：每 3 秒记录一次进度

            if int(now * 1000) % _PROGRESS_LOG_INTERVAL_MS < _PROGRESS_LOG_TOLERANCE_MS and has_started:

                log_ffmpeg_progress(run_id, state['current_ms'], total_duration, spd, elapsed)

            time.sleep(_PROGRESS_POLL_SEC)

            if process.poll() is not None and not state['done']:

                state['done'] = True



        if _shutdown_requested.is_set():

            _reset_ffmpeg_pause(process)

            elapsed_final = time.time() - start_time

            log_ffmpeg_end(run_id, -1, elapsed_final, list(stderr_tail))

            _terminate_ffmpeg_via_stdin(process, stdin_lock)

            _force_terminate(process)

            raise KeyboardInterrupt("处理已取消")



        _force_terminate(process, wait_timeout=10, term_timeout=3)

        t_read.join(timeout=1.0)

        t_err.join(timeout=1.0)



        # User terminated via UI button — stop this task and signal queue halt

        if ffmpeg_state.get('terminated'):

            elapsed_final = time.time() - start_time

            log_ffmpeg_end(run_id, process.returncode, elapsed_final, list(stderr_tail))

            if ffmpeg_state.get('notify'):

                _send_notification('MovieEditor', f'任务已终止: {title_prefix}')

            raise FFmpegUserTerminated()



        if process.returncode != 0:

            _reset_ffmpeg_pause(process)

            elapsed_final = time.time() - start_time

            stderr_list = list(stderr_tail)

            log_ffmpeg_end(run_id, process.returncode, elapsed_final, stderr_list)

            if ffmpeg_state.get('notify'):

                _send_notification('MovieEditor - 执行失败', f'FFmpeg 返回码: {process.returncode}\n{title_prefix}')

            msg = f'FFmpeg 执行失败，返回码: {process.returncode}'

            if stderr_list:

                msg += '\n' + '\n'.join(f'  | {line}' for line in stderr_list[-5:])

            raise RuntimeError(msg)



        # Final Render: Completed state

        if finish_title:

            final_title = finish_title

        elif is_last:

            final_title = "渲染完成"

        else:

            final_title = f"{title_prefix} - 已完成" if title_prefix else "已完成"

        live.update(build_interface_lines(last_plain_text, final_title, True, 100, ffmpeg_state, output_file=output_file))



        # 日志：记录成功完成

        elapsed_final = time.time() - start_time

        log_ffmpeg_end(run_id, process.returncode, elapsed_final, list(stderr_tail))



        if ffmpeg_state.get('notify'):

            _send_notification('MovieEditor - 渲染完成', f'{title_prefix}\n{output_file}')



    except KeyboardInterrupt:

        _reset_ffmpeg_pause(process)

        # Ensure FFmpeg subprocess is terminated on Ctrl+C before unregister

        _terminate_ffmpeg_via_stdin(process, stdin_lock)

        _force_terminate(process)

        raise

    finally:

        _reset_ffmpeg_pause(process)

        unregister_child_process(process)