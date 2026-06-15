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

from ui.console import (
    ANSI_ESCAPE, hide_cursor, show_cursor, register_child_process,
    unregister_child_process, _shutdown_requested, UI_COLORS,
    _console_has_input, _console_read_key,
)
from ui.display import get_display_width, trim_to_display_width, reset_menu_cache
from core.helpers import format_hms
from core.logger import log_ffmpeg_start, log_ffmpeg_progress, log_ffmpeg_end, log_ffmpeg_error

class FFmpegUserTerminated(Exception):
    """Raised when the user explicitly terminates ffmpeg via the UI terminate button."""
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
            print(f"\033[31m错误: ffprobe 未找到，请确保 FFmpeg 已安装并在 PATH 中\033[0m", file=sys.stderr)
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
    lines = [f'  {command[0]}']
    i = 1
    
    while i < len(command):
        token = str(command[i])
        
        if token.startswith('-'):
            line = f'    {token}'
            if i + 1 < len(command) and not str(command[i + 1]).startswith('-'):
                arg = str(command[i + 1])
                if any(c.isspace() for c in arg):
                    arg = f'"{arg}"'
                line += f' {arg}'
                i += 1
            lines.append(line)
        else:
            lines.append(f'    {token}')
        i += 1
    
    return lines



def _build_progress_line(text, width, is_finished):
    """Build a single progress text line with proper padding."""
    indent = '  '
    inner_w = width - 2
    if is_finished:
        p_display = f"\033[38;2;205;214;244m\033[1m{text}\033[0m"
        plain_len = get_display_width(text)
    else:
        p_display = f"\033[38;2;205;214;244m{text}\033[0m"
        plain_len = get_display_width(text)
    pad_len = max(0, inner_w - len(indent) - plain_len)
    return f"  │{indent}{p_display}{' ' * pad_len}│"


_BAR_WIDTH = 20


def _build_progress_bar(pct, width):
    """Build a visual progress bar line. pct is 0-100."""
    indent = '  '
    inner_w = width - 2
    filled = int(_BAR_WIDTH * min(pct, 100) / 100)
    empty = _BAR_WIDTH - filled
    bar = f"\033[38;2;137;180;250m{'█' * filled}\033[38;2;108;112;134m{'░' * empty}\033[0m"
    bar_vis = 2 + _BAR_WIDTH  # │ + bar + │
    pad = ' ' * max(0, inner_w - len(indent) - bar_vis)
    return f"  │{indent}│{bar}│{pad}│"


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

    hide_cursor()
    last_plain_text = '正在初始化进程...'
    
    # State for UI rendering
    last_term_size = (0, 0)

    # Layout constants
    PROGRESS_ROW_IDX = 3  # 1-based ANSI line number
    STATUS_ROW_IDX = 4
    BAR_ROW_IDX = 5

    ffmpeg_state = {
        'paused': False,
        'terminated': False,
        'selected_button': 0,  # 0=pause/resume, 1=terminate
    }
    stdin_lock = threading.Lock()

    def _check_key_input():
        """Non-blocking keyboard check for button navigation (LEFT/RIGHT/ENTER)."""
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
                        ffmpeg_state['selected_button'] = min(1, ffmpeg_state['selected_button'] + 1)
                continue
            if key in (b'\r', b'\n'):  # ENTER
                btn = ffmpeg_state['selected_button']
                if btn == 0:  # Pause / Resume
                    now_paused = _toggle_ffmpeg_pause(process)
                    ffmpeg_state['paused'] = now_paused
                elif btn == 1:  # Terminate
                    if not ffmpeg_state['terminated']:
                        ffmpeg_state['terminated'] = True
                        if ffmpeg_state['paused']:
                            _reset_ffmpeg_pause(process)
                            ffmpeg_state['paused'] = False
                        _terminate_ffmpeg_via_stdin(process, stdin_lock)
                continue

    def draw_full_interface(progress_text, title, is_finished, pct=0, ffmpeg_state=None):
        term_w, term_h = shutil.get_terminal_size((120, 30))
        width = max(70, min(120, term_w - 2))
        inner_width = width - 4
        
        # Truncate command lines if they are too many for the current terminal height
        display_cmd = cmd_lines_raw
        max_cmd_lines = max(3, term_h - 13)
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
        lines.append(_build_progress_line(progress_text, width, is_finished))
        
        # Status / pause indicator
        if ffmpeg_state and ffmpeg_state.get('paused') and not is_finished:
            status_text = '⏸ 已暂停 — 进程已挂起，CPU 利用率为零'
            status_display = f"\033[38;2;249;226;175m{status_text}\033[0m"
            status_plain_len = get_display_width(status_text)
            status_pad = ' ' * max(0, width - 4 - status_plain_len)
            lines.append(f"  │  {status_display}{status_pad}│")
        else:
            lines.append(_build_progress_bar(pct if not is_finished else 100, width))

        lines.append(f"  │{' ' * (width - 2)}│") # Padding

        # Command Lines
        for line in display_cmd:
            plain = ANSI_ESCAPE.sub('', line)
            trunc = trim_to_display_width(plain, inner_width - 2)
            colored = f"{UI_COLORS['muted']}{trunc}{UI_COLORS['reset']}"
            pad = ' ' * max(0, width - 2 - get_display_width(trunc))
            lines.append(f"  │{colored}{pad}│")

        lines.append(f"  │{' ' * (width - 2)}│") # Bottom padding

        # Control buttons row
        if ffmpeg_state and not is_finished:
            is_paused = ffmpeg_state.get('paused', False)
            selected_btn = ffmpeg_state.get('selected_button', 0)

            pause_label = '恢复' if is_paused else '暂停'
            terminate_label = '终止'

            def _style_btn(label, is_sel):
                if is_sel:
                    return f"\033[48;2;69;71;90m\033[38;2;137;180;250m {label} \033[0m"
                return f"{UI_COLORS['muted']} {label} {UI_COLORS['reset']}"

            btn_pause = _style_btn(pause_label, selected_btn == 0)
            btn_terminate = _style_btn(terminate_label, selected_btn == 1)

            # Padding: leading 2 spaces + " label " + 4 gap + " label "
            fixed_vis = 2 + get_display_width(pause_label) + 2 + 4 + get_display_width(terminate_label) + 2
            btn_pad = ' ' * max(0, (width - 2) - fixed_vis)
            lines.append(f"  │  {btn_pause}    {btn_terminate}{btn_pad}│")
            lines.append(f"  │{' ' * (width - 2)}│")

        lines.append(f"  ╰{'─' * (width - 2)}╯")

        sys.stdout.write('\033[2J\033[H')
        reset_menu_cache()
        sys.stdout.write('\n'.join(lines) + '\n')
        sys.stdout.flush()

        return (term_w, term_h)

    try:
        progress_tag = f' ({episode_progress})' if episode_progress else ''
        display_title = f"正在运行{progress_tag}: {title_prefix}" if title_prefix else f"正在运行{progress_tag}"
        last_term_size = draw_full_interface(last_plain_text, display_title, False, 0, ffmpeg_state)
        last_width = max(70, min(120, last_term_size[0] - 2)) if isinstance(last_term_size, tuple) else 118
        cur_pct = 0.0
        last_selected_button = ffmpeg_state.get('selected_button', 0)
        
        while not state['done']:
            # 非阻塞键盘检测
            _check_key_input()

            # 检查退出信号
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

            # 暂停时更新标题
            is_paused_now = ffmpeg_state['paused']
            if is_paused_now:
                display_title_eff = f"⏸ 已暂停{progress_tag}: {title_prefix}" if title_prefix else f"⏸ 已暂停{progress_tag}"
            else:
                display_title_eff = display_title

            cur_selected = ffmpeg_state.get('selected_button', 0)
            button_changed = cur_selected != last_selected_button
            last_selected_button = cur_selected

            current_term_size = shutil.get_terminal_size((120, 30))
            content_height = len(cmd_lines_raw) + 10
            is_too_tall = content_height > current_term_size.lines

            width = max(70, min(120, current_term_size.columns - 2))
            if current_term_size != last_term_size or is_too_tall or width != last_width or button_changed:
                last_term_size = draw_full_interface(plain_text, display_title_eff, False, cur_pct, ffmpeg_state)
                last_width = max(70, min(120, current_term_size.columns - 2))
            else:
                line_str = _build_progress_line(plain_text, width, False)
                print(f'\033[{PROGRESS_ROW_IDX};1H{line_str}\033[K', end='', flush=True)
                if is_paused_now:
                    status_text = '⏸ 已暂停 — 进程已挂起，CPU 利用率为零'
                    status_display = f"\033[38;2;249;226;175m{status_text}\033[0m"
                    status_plain_len = get_display_width(status_text)
                    status_pad = ' ' * max(0, width - 4 - status_plain_len)
                    status_line = f"  │  {status_display}{status_pad}│"
                    print(f'\033[{STATUS_ROW_IDX};1H{status_line}\033[K', end='', flush=True)
                else:
                    bar_str = _build_progress_bar(cur_pct, width)
                    print(f'\033[{STATUS_ROW_IDX};1H\033[K', end='', flush=True)
                    print(f'\033[{BAR_ROW_IDX};1H{bar_str}\033[K', end='', flush=True)

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
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            raise KeyboardInterrupt("处理已取消")

        process.wait()
        t_read.join(timeout=1.0)
        t_err.join(timeout=1.0)

        # User terminated via UI button — stop this task and signal queue halt
        if ffmpeg_state.get('terminated'):
            elapsed_final = time.time() - start_time
            log_ffmpeg_end(run_id, process.returncode, elapsed_final, list(stderr_tail))
            raise FFmpegUserTerminated()

        if process.returncode != 0:
            _reset_ffmpeg_pause(process)
            elapsed_final = time.time() - start_time
            stderr_list = list(stderr_tail)
            log_ffmpeg_end(run_id, process.returncode, elapsed_final, stderr_list)
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
        draw_full_interface(last_plain_text, final_title, True, 100, ffmpeg_state)

        # 日志：记录成功完成
        elapsed_final = time.time() - start_time
        log_ffmpeg_end(run_id, process.returncode, elapsed_final, list(stderr_tail))

    except KeyboardInterrupt:
        _reset_ffmpeg_pause(process)
        # Ensure FFmpeg subprocess is terminated on Ctrl+C before unregister
        _terminate_ffmpeg_via_stdin(process, stdin_lock)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        show_cursor()
        raise
    finally:
        _reset_ffmpeg_pause(process)
        show_cursor()
        unregister_child_process(process)

