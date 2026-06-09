# 工具函数：时间解析、语言映射、编码映射、分辨率选项
import os
import re
import shutil
from typing import Optional


def truncate_name(name: str, max_len: int = 40) -> str:
    if len(name) <= max_len:
        return name
    if max_len < 10:
        max_len = 10
    return name[:max_len - 3] + '...'


def get_display_name(path_or_name: str) -> str:
    return os.path.basename(path_or_name)


def format_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def parse_time_to_seconds(time_text: Optional[str]) -> Optional[int]:
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


def adjust_time_setting(time_text: Optional[str], delta_seconds: int) -> Optional[str]:
    seconds = parse_time_to_seconds(time_text)
    if seconds is None:
        return None
    new_seconds = max(0, seconds + delta_seconds)
    return format_hms(new_seconds) if new_seconds > 0 else None


def cycle_option(current, options: list, step: int):
    if not options:
        return current
    try:
        idx = options.index(current)
    except ValueError:
        idx = 0
    return options[(idx + step) % len(options)]


def format_on_off(enabled: bool) -> str:
    return '开启' if enabled else '关闭'


def build_resolution_options(src_width: int, src_height: int) -> list:
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


def get_full_language_name(lang_code: str) -> str:
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


def get_subtitle_format_name(codec_name: str) -> str:
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


def extract_differential_name(file_paths: list[str]) -> list[str]:
    """Extract the differentiating part of filenames.
    E.g. ["Breaking.Bad.S01E01.Pilot.xxx.mkv", "Breaking.Bad.S01E02.Cats.xxx.mkv"]
    Returns ["S01E01 Pilot", "S01E02 Cats"]
    Splits by token boundaries (. _ -) to avoid cutting words.
    """
    if len(file_paths) <= 1:
        return [os.path.splitext(os.path.basename(f))[0] for f in file_paths]

    basenames = [os.path.splitext(os.path.basename(f))[0] for f in file_paths]
    tokens_list = [re.split(r'[._\-]+', name) for name in basenames]

    # Find common prefix tokens
    prefix_len = 0
    for i in range(len(tokens_list[0])):
        if all(len(t) > i and t[i] == tokens_list[0][i] for t in tokens_list):
            prefix_len = i + 1
        else:
            break

    # Find common suffix tokens
    suffix_len = 0
    for i in range(1, min(len(t) for t in tokens_list) + 1):
        if all(t[-i] == tokens_list[0][-i] for t in tokens_list):
            suffix_len = i
        else:
            break

    # Extract differential tokens
    result = []
    for tokens in tokens_list:
        end = len(tokens) - suffix_len if suffix_len > 0 else len(tokens)
        diff = tokens[prefix_len:end]
        result.append(' '.join(diff) if diff else ' '.join(tokens))

    return result
