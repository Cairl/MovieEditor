# 主菜单循环 + process_files 入口
import os
import re
import sys

from ui.console import (
    ANSI_ESCAPE, CURSOR_HOME, UI_COLORS, hide_cursor, show_cursor,
    terminate_active_children, _shutdown_requested,
)
from ui.display import (
    MENU_SEPARATOR, menu_item, truncate_name,
    with_ffmpeg_hint, render_screen_menu, run_menu_loop, Action,
    reset_menu_cache,
)
from core.helpers import (
    format_on_off, extract_differential_name, escape_ffmpeg_filter_path,
    format_hms, parse_time_to_seconds, build_resolution_options,
)
from ui.navigation import (
    read_navigation_key, get_selectable_indices,
    get_next_selectable, normalize_selected_index,
)
from ui.dialogs import choose_files, get_video_files_in_dir
from core.ffmpeg import (
    get_video_resolution, get_video_duration, get_audio_streams,
    get_subtitle_streams, run_ffmpeg_with_progress, format_preview_lines,
)
from ui.video import handle_video_settings_menu
from ui.audio import handle_audio_settings_menu
from ui.subtitle import handle_subtitle_settings_menu

_SETTINGS_HANDLERS = {
    '视频设置': handle_video_settings_menu,
    '音频设置': handle_audio_settings_menu,
    '字幕设置': handle_subtitle_settings_menu,
}


def process_files() -> None:
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
            for arg in sys.argv[1:]:
                if os.path.isfile(arg):
                    input_paths = [arg]
                    break
    else:
        return

    if not input_paths:
        print('未发现可处理的文件')
        return

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
    series_edit_mode = 'batch'

    settings = {
        'video': {'hevc': True, 'resolution': None, 'crop_top': 0, 'crop_left': 0, 'ss': None, 'to': None},
        'audio': {'reencode': True, 'codec': 'copy', 'internal_streams': {}},
        'subtitle': {'mode': 'internal', 'files': [], 'burn_in': False, 'disable': False, 'codec': 'copy', 'internal_streams': {}, 'external_streams': {}},
    }

    audio_codec_options = ['copy', 'aac', 'mp3', 'ac3', 'flac']

    def reset_video_trim():
        settings['video']['ss'] = None
        settings['video']['to'] = None
        settings['video']['crop_top'] = 0
        settings['video']['crop_left'] = 0

    def build_crop_filter_text():
        return f"crop=in_w-{settings['video']['crop_left']*2}:in_h-{settings['video']['crop_top']*2}:{settings['video']['crop_left']}:{settings['video']['crop_top']}"

    def build_ffmpeg_command(input_file, audio_streams, subtitle_streams, series_mode=False, external_subtitle=None):
        if series_mode:
            out_dir = os.path.join(os.path.dirname(input_file), 'Edited')
            out_path = os.path.join(out_dir, os.path.splitext(os.path.basename(input_file))[0] + '.mp4')
        else:
            out_path = os.path.join(os.path.dirname(input_file), '[FF] ' + os.path.splitext(os.path.basename(input_file))[0] + '.mp4')

        cmd = ['ffmpeg', '-y', '-hide_banner', '-ignore_unknown', '-i', input_file]
        vf_filters = []

        if settings['video']['crop_top'] > 0 or settings['video']['crop_left'] > 0:
            vf_filters.append(build_crop_filter_text())

        selected_internal_sub = [i for i, s in enumerate(subtitle_streams) if settings['subtitle']['internal_streams'].get(str(s['index']), True)]
        selected_external_sub = []
        if external_subtitle:
            selected_external_sub = [0]

        for i, s in enumerate(audio_streams):
            key = str(s['index'])
            if settings['audio']['internal_streams'].get(key, True):
                cmd.extend(['-map', f"0:a:{s['rel_index']}"])

        if settings['subtitle']['burn_in'] and (subtitle_streams or selected_external_sub):
            if settings['subtitle']['mode'] == 'internal' and selected_internal_sub:
                sub_idx = selected_internal_sub[0]
                vf_filters.append(f"subtitles=input:si={subtitle_streams[sub_idx]['rel_index']}")
            elif settings['subtitle']['mode'] == 'external' and selected_external_sub:
                # Use full absolute path with FFmpeg filter escaping
                sub_path = external_subtitle if external_subtitle else settings['subtitle']['files'][0]
                vf_filters.append(f"subtitles={escape_ffmpeg_filter_path(os.path.abspath(sub_path))}")
        elif not settings['subtitle']['disable']:
            if settings['subtitle']['mode'] == 'internal':
                for pos in selected_internal_sub:
                    cmd.extend(['-map', f"0:s:{subtitle_streams[pos]['rel_index']}"])
            elif settings['subtitle']['mode'] == 'external' and external_subtitle:
                cmd.extend(['-i', external_subtitle, '-map', '1:s:0'])

        if settings['video']['hevc']:
            cmd.extend(['-c:v', 'libx265', '-crf', '23'])
        else:
            cmd.extend(['-c:v', 'libx264'])

        if not settings['audio']['reencode']:
            cmd.extend(['-c:a', 'copy'])
        elif settings['audio']['codec'] != 'copy':
            cmd.extend(['-c:a', settings['audio']['codec']])

        if settings['subtitle']['burn_in']:
            cmd.append('-sn')
        else:
            has_subtitle_stream = (settings['subtitle']['mode'] == 'internal' and len(selected_internal_sub) > 0) or (settings['subtitle']['mode'] == 'external' and len(selected_external_sub) > 0)
            if has_subtitle_stream:
                cmd.extend(['-c:s', 'mov_text' if settings['subtitle']['codec'] == 'copy' else settings['subtitle']['codec']])

        cmd.extend([
            '-map_metadata', '0',
            '-map_chapters', '0',
            '-metadata', 'handler_name=@Cairl'
        ])

        if vf_filters:
            cmd.extend(['-vf', ','.join(vf_filters)])
        if settings['video']['resolution']:
            cmd.extend(['-s', settings['video']['resolution'], '-aspect', settings['video']['resolution'].replace('x', ':')])

        if settings['video']['ss']:
            cmd.extend(['-ss', settings['video']['ss']])
        if settings['video']['to']:
            cmd.extend(['-to', settings['video']['to']])

        cmd.append(out_path)
        return cmd

    def calculate_effective_duration(file_path: str) -> float:
        start_sec = parse_time_to_seconds(settings['video']['ss'])
        end_sec = parse_time_to_seconds(settings['video']['to'])
        file_duration = get_video_duration(file_path)
        calc_duration = float(file_duration)
        if end_sec is not None and end_sec > 0:
            calc_duration = float(end_sec)
        if start_sec is not None and start_sec > 0:
            calc_duration -= float(start_sec)
        return max(0.0, calc_duration)

    def build_episode_context() -> list:
        diff_names = extract_differential_name(input_paths)
        ep_name = diff_names[current_file_idx] if current_file_idx < len(diff_names) else os.path.basename(first_file)
        return [f"当前: {ep_name} ({current_file_idx+1}/{len(input_paths)})"]

    ctx = {
        'settings': settings,
        'audio_streams': audio_streams,
        'subtitle_streams': subtitle_streams,
        'first_width': first_width,
        'first_height': first_height,
        'update_current_episode': update_current_episode,
        'current_file_idx': current_file_idx,
        'audio_codec_options': audio_codec_options,
        'build_crop_filter_text': build_crop_filter_text,
        'choose_files': choose_files,
    }

    def refresh_ctx():
        ctx['audio_streams'] = audio_streams
        ctx['subtitle_streams'] = subtitle_streams
        ctx['first_width'] = first_width
        ctx['first_height'] = first_height
        ctx['current_file_idx'] = current_file_idx

    main_index = 0
    while True:
        if _shutdown_requested.is_set():
            break
        hide_cursor()
        refresh_ctx()

        context = []

        menu = []
        if is_series_mode:
            edit_mode_label = '统筹编辑' if series_edit_mode == 'batch' else '逐集编辑'
            menu.append(menu_item(f'编辑模式: {edit_mode_label}'))
            if series_edit_mode == 'per_episode':
                diff_names = extract_differential_name(input_paths)
                menu.append(menu_item(f'当前选择: {diff_names[current_file_idx]}'))
            menu.append(MENU_SEPARATOR)

        menu.extend([
            menu_item('视频设置'),
            menu_item('音频设置'),
            menu_item('字幕设置'),
            MENU_SEPARATOR,
            f'{UI_COLORS["green"]}\033[1m{menu_item("开始处理")}{UI_COLORS["reset"]}',
            menu_item('预览 FFmpeg 命令'),
            '',
        ])
        render_screen_menu(mode_title, context, menu, selected_index=main_index)
        main_index = normalize_selected_index(menu, main_index) or 0
        k = read_navigation_key()
        if k in ('LEFT', 'RIGHT'):
            selected_line = ANSI_ESCAPE.sub('', menu[main_index]).strip() if main_index < len(menu) else ''
            if is_series_mode and '当前选择' in selected_line:
                update_current_episode(current_file_idx + (-1 if k == 'LEFT' else 1))
                reset_video_trim()
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

        selected_line = ANSI_ESCAPE.sub('', menu[main_index]).strip()
        selected_plain = re.sub(r'\s*─+\s*$', '', selected_line).strip()

        if '开始处理' in selected_plain:
            if is_series_mode and series_edit_mode == 'per_episode':
                def clamped_update_episode(idx):
                    if 0 <= idx < len(input_paths):
                        update_current_episode(idx)

                def ep_build_menu():
                    return [
                        menu_item('确认处理当前集'),
                        menu_item('视频设置'),
                        menu_item('音频设置'),
                        menu_item('字幕设置'),
                        MENU_SEPARATOR,
                        menu_item('返回菜单'),
                        '',
                    ]

                def ep_action_handler(key, selected_item, idx_in_sel):
                    if '确认处理当前集' in selected_item:
                        os.makedirs(os.path.join(os.path.dirname(first_file), 'Edited'), exist_ok=True)
                        ext_sub = None
                        if settings['subtitle']['mode'] == 'external' and settings['subtitle']['files']:
                            if current_file_idx < len(settings['subtitle']['files']):
                                ext_sub = settings['subtitle']['files'][current_file_idx]
                        command = build_ffmpeg_command(first_file, audio_streams, subtitle_streams, series_mode=True, external_subtitle=ext_sub)
                        _batch_diff = extract_differential_name(input_paths)
                        prefix = _batch_diff[current_file_idx] if current_file_idx < len(_batch_diff) else os.path.splitext(os.path.basename(first_file))[0]
                        run_ffmpeg_with_progress(command, calculate_effective_duration(first_file), title_prefix=prefix)
                        return 'DONE'
                    elif '返回菜单' in selected_item:
                        return Action.BREAK
                    for label, handler in _SETTINGS_HANDLERS.items():
                        if label in selected_item:
                            refresh_ctx()
                            handler(ctx, [], allow_episode_nav=True)
                            break
                    return None

                for i in range(len(input_paths)):
                    update_current_episode(i)
                    reset_video_trim()
                    result = run_menu_loop(
                        '逐集处理', build_episode_context, ep_build_menu, ep_action_handler,
                        allow_episode_nav=True,
                        update_current_episode=clamped_update_episode,
                        current_file_idx_ref=[current_file_idx],
                    )
                    # BACKSPACE (None) or "返回菜单" (Action.BREAK) → return to main menu
                    if result is None or result == Action.BREAK:
                        break
                    main_index = 0
                reset_menu_cache()  # force full redraw after per-episode FFmpeg
            else:
                break
        elif '编辑模式' in selected_plain:
            series_edit_mode = 'batch' if series_edit_mode == 'per_episode' else 'per_episode'
        elif any(label in selected_plain for label in _SETTINGS_HANDLERS):
            allow_ep_nav = is_series_mode and series_edit_mode == 'per_episode'
            refresh_ctx()
            for label, handler in _SETTINGS_HANDLERS.items():
                if label in selected_plain:
                    handler(ctx, [], allow_episode_nav=allow_ep_nav, return_label='返回菜单')
                    break
            reset_menu_cache()  # force full redraw after settings menu
        elif '预览 FFmpeg 命令' in selected_plain:
            def build_preview_context():
                ext_sub = None
                if is_series_mode and settings['subtitle']['mode'] == 'external' and settings['subtitle']['files']:
                    if current_file_idx < len(settings['subtitle']['files']):
                        ext_sub = settings['subtitle']['files'][current_file_idx]
                preview_command = build_ffmpeg_command(first_file, audio_streams, subtitle_streams, series_mode=is_series_mode, external_subtitle=ext_sub)
                cmd_lines = format_preview_lines(preview_command, input_file=first_file, output_file=preview_command[-1])
                ctx = [f"{UI_COLORS['muted']}{cl}{UI_COLORS['reset']}" for cl in cmd_lines]
                ctx.append('')
                return ctx

            allow_ep_nav = is_series_mode and series_edit_mode == 'per_episode'
            run_menu_loop(
                '预览 FFmpeg 命令', build_preview_context,
                lambda: [MENU_SEPARATOR, menu_item('返回菜单'), ''],
                lambda k, s, i: Action.BREAK if '返回菜单' in s and k == 'ENTER' else None,
                allow_episode_nav=allow_ep_nav,
                update_current_episode=update_current_episode,
                current_file_idx_ref=[current_file_idx],
            )
            reset_menu_cache()

    if _shutdown_requested.is_set():
        show_cursor()
        return
    show_cursor()
    try:
        total_count = len(input_paths)
        for i, path in enumerate(input_paths):
            if is_series_mode:
                os.makedirs(os.path.join(os.path.dirname(path), 'Edited'), exist_ok=True)

            # Probe per-file streams to avoid stale data from last update_current_episode()
            file_audio_streams = get_audio_streams(path)
            file_subtitle_streams = get_subtitle_streams(path)

            ext_sub = None
            if is_series_mode and settings['subtitle']['mode'] == 'external':
                if i < len(settings['subtitle']['files']):
                    ext_sub = settings['subtitle']['files'][i]

            command = build_ffmpeg_command(path, file_audio_streams, file_subtitle_streams, series_mode=is_series_mode, external_subtitle=ext_sub)
            _diff_all = extract_differential_name(input_paths)
            prefix = _diff_all[i] if i < len(_diff_all) else os.path.splitext(os.path.basename(path))[0]
            run_ffmpeg_with_progress(command, calculate_effective_duration(path), title_prefix=prefix)

        read_navigation_key()

    except KeyboardInterrupt:
        show_cursor()
        print('\n\n操作已取消')
        terminate_active_children()
    except (OSError, RuntimeError) as e:
        show_cursor()
        print(f'\n发生错误: {e}')
