# 音频设置菜单
import re
from ui.console import CURSOR_HOME, hide_cursor, ANSI_ESCAPE
from ui.display import MENU_SEPARATOR, menu_item, with_ffmpeg_hint, render_screen_menu
from core.helpers import format_on_off
from ui.navigation import read_navigation_key, get_selectable_indices, get_next_selectable, normalize_selected_index
from core.helpers import cycle_option


def handle_audio_settings_menu(ctx: dict, context_lines: list, allow_episode_nav: bool = False, return_label: str = '返回') -> None:
    settings = ctx['settings']
    audio_streams = ctx['audio_streams']
    update_current_episode = ctx['update_current_episode']
    audio_codec_options = ctx['audio_codec_options']

    a_idx = 0
    while True:
        print(CURSOR_HOME, end='', flush=True)
        hide_cursor()
        for s in audio_streams:
            key = str(s['index'])
            if key not in settings['audio']['internal_streams']:
                settings['audio']['internal_streams'][key] = True
        codec_hint = None if (settings['audio']['reencode'] and settings['audio']['codec'] != 'copy') else ("-c:a copy" if not settings['audio']['reencode'] else None)
        codec_name = '默认' if settings['audio']['codec'] == 'copy' else settings['audio']['codec'].upper()
        am = [
            with_ffmpeg_hint(menu_item('重新编码', format_on_off(settings['audio']['reencode'])), codec_hint, not settings['audio']['reencode']),
            with_ffmpeg_hint(menu_item('音频编码格式', codec_name), f"-c:a {settings['audio']['codec']}" if settings['audio']['reencode'] and settings['audio']['codec'] != 'copy' else None, settings['audio']['reencode'] and settings['audio']['codec'] != 'copy'),
            MENU_SEPARATOR,
        ]
        max_a_idx_w = max((len(str(s['rel_index'] + 1)) for s in audio_streams), default=1)
        for i, s in enumerate(audio_streams):
            key = str(s['index'])
            enabled = settings['audio']['internal_streams'].get(key, True)
            status = format_on_off(enabled)
            channels = f"{s['channels']}ch" if s['channels'] else '2ch'
            padded_idx = str(s['rel_index'] + 1).ljust(max_a_idx_w)
            line = f"#{padded_idx} | {s['codec'].upper()} | {channels} | {s['language']} : {status}"
            hint = f"-map 0:a:{s['rel_index']}" if enabled else None
            am.append(with_ffmpeg_hint(line, hint, bool(hint)))
        am.extend([
            MENU_SEPARATOR,
            menu_item(return_label),
            '',
        ])
        render_screen_menu('音频设置', context_lines, am, selected_index=a_idx)
        a_idx = normalize_selected_index(am, a_idx) or 0
        key = read_navigation_key()
        if allow_episode_nav and key in ('LEFT', 'RIGHT'):
            update_current_episode(ctx['current_file_idx'] + (-1 if key == 'LEFT' else 1))
            continue
        if key == 'UP':
            a_idx = get_next_selectable(am, a_idx, -1)
            continue
        if key == 'DOWN':
            a_idx = get_next_selectable(am, a_idx, 1)
            continue
        if key == 'BACKSPACE':
            break
        if key not in ('LEFT', 'RIGHT', 'ENTER'):
            continue
        selectable = get_selectable_indices(am)
        if a_idx not in selectable:
            continue
        selected_line = ANSI_ESCAPE.sub('', am[a_idx]).strip()
        if re.search(r'重新编码\s*:', selected_line):
            settings['audio']['reencode'] = not settings['audio']['reencode']
        elif re.search(r'音频编码格式\s*:', selected_line):
            if key in ('LEFT', 'RIGHT'):
                settings['audio']['codec'] = cycle_option(settings['audio']['codec'], audio_codec_options, -1 if key == 'LEFT' else 1)
        elif re.search(r'返回', selected_line):
            break
        else:
            idx_in_sel = selectable.index(a_idx)
            if idx_in_sel >= 2:
                stream_pos = idx_in_sel - 2
                if 0 <= stream_pos < len(audio_streams):
                    skey = str(audio_streams[stream_pos]['index'])
                    cur = settings['audio']['internal_streams'].get(skey, True)
                    settings['audio']['internal_streams'][skey] = not cur
