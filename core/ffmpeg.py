# FFmpeg 相关：探测函数、命令构建、进度 UI
import os
import re
import sys
import time
import shutil
import threading
import subprocess
from collections import deque
from typing import Optional

from ui.console import (
    ANSI_ESCAPE, hide_cursor, register_child_process,
    unregister_child_process, _shutdown_requested, UI_COLORS,
)
from ui.display import get_display_width, trim_to_display_width
from core.helpers import format_hms
from core.logger import log_ffmpeg_start, log_ffmpeg_progress, log_ffmpeg_end, log_ffmpeg_error

# ---- 探测函数 ----
def get_video_resolution(file_path: str) -> tuple[int, int]:
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        out = result.stdout.strip()
        if not out:
            return 0, 0
        w, h = map(int, out.split(','))
        return w, h
    except (subprocess.SubprocessError, ValueError):
        return 0, 0


def get_video_duration(file_path: str) -> float:
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace')
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return 0


def _probe_streams_json(file_path: str, selector: str, entries: str) -> list[dict]:
    try:
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-probesize', '50M', '-analyzeduration', '100M',
            '-select_streams', selector,
            '-show_entries', entries,
            '-of', 'json', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, check=True)
        stdout_text = result.stdout.decode('utf-8', errors='replace')
        data = json.loads(stdout_text or '{}')
        return data.get('streams', [])
    except (subprocess.SubprocessError, json.JSONDecodeError, UnicodeDecodeError):
        try:
            cmd = ['ffprobe', '-v', 'quiet', '-select_streams', selector, '-show_entries', entries, '-of', 'json', file_path]
            result = subprocess.run(cmd, capture_output=True, check=True)
            stdout_text = result.stdout.decode('utf-8', errors='replace')
            data = json.loads(stdout_text or '{}')
            return data.get('streams', [])
        except (subprocess.SubprocessError, json.JSONDecodeError, UnicodeDecodeError):
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
    except (subprocess.SubprocessError, UnicodeDecodeError):
        for s in streams:
            s['raw_display_name'] = s['codec']
            
    return streams


def format_preview_lines(command: list[str], input_file: Optional[str] = None, output_file: Optional[str] = None) -> list[str]:
    def replace_path(token):
        text = str(token)
        if input_file and text == input_file:
            return '<input>'
        if output_file and text == output_file:
            return '<output>'
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


# ---- 进度 UI ----
def run_ffmpeg_with_progress(command: list[str], total_duration: float, title_prefix: str = '') -> None:
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
    cmd_lines_raw = format_preview_lines(command, input_file, output_file)

    # 日志：记录启动信息
    run_id = log_ffmpeg_start(command, input_file, output_file, total_duration, title_prefix)

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
                        except (ValueError, IndexError):
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

    def get_shimmer_text(text, offset):
        C_DIM = '\033[38;2;108;112;134m'
        C_MID = '\033[38;2;186;194;222m'
        C_BRIGHT = '\033[38;2;205;214;244m\033[1m'
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
             p_display = f"\033[38;2;205;214;244m\033[1m{text}\033[0m"
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

            # 日志：每 3 秒记录一次进度
            if int(now * 1000) % 3000 < 60 and has_started:
                log_ffmpeg_progress(run_id, state['current_ms'], total_duration, spd, elapsed)
            time.sleep(0.05)
            if process.poll() is not None and not state['done']:
                state['done'] = True

        if _shutdown_requested.is_set():
            try:
                process.terminate()
                process.wait(timeout=2)
            except OSError:
                try:
                    process.kill()
                except OSError:
                    pass
            raise KeyboardInterrupt("处理已取消")

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

