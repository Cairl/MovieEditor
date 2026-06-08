# 视频设置菜单
from ui.console import CURSOR_HOME, hide_cursor
from ui.display import MENU_SEPARATOR, menu_item, with_ffmpeg_hint, render_screen_menu
from core.helpers import format_on_off
from ui.navigation import read_navigation_key, get_selectable_indices, get_next_selectable, normalize_selected_index
from core.helpers import adjust_time_setting


def handle_video_settings_menu(ctx: dict, context_lines: list, allow_episode_nav: bool = False, return_label: str = '返回') -> None:
    settings = ctx['settings']
    first_width = ctx['first_width']
    first_height = ctx['first_height']
    build_crop_filter_text = ctx['build_crop_filter_text']
    update_current_episode = ctx['update_current_episode']

    v_idx = 0
    while True:
        print(CURSOR_HOME, end='', flush=True)
        hide_cursor()
        crop_hint = f"-vf {build_crop_filter_text()}"
        vm = [
            with_ffmpeg_hint(menu_item('H.265 编码', format_on_off(settings['video']['hevc'])), '-c:v hevc -crf 23', settings['video']['hevc']),
            MENU_SEPARATOR,
            with_ffmpeg_hint(menu_item('开始时间', settings['video']['ss'] or '未设置'), f"-ss {settings['video']['ss']}" if settings['video']['ss'] else None, bool(settings['video']['ss'])),
            with_ffmpeg_hint(menu_item('结束时间', settings['video']['to'] or '未设置'), f"-to {settings['video']['to']}" if settings['video']['to'] else None, bool(settings['video']['to'])),
            MENU_SEPARATOR,
            with_ffmpeg_hint(menu_item('裁剪上下黑边', f"{settings['video']['crop_top']}px" if settings['video']['crop_top'] > 0 else '不裁剪'), crop_hint, settings['video']['crop_top'] > 0),
            with_ffmpeg_hint(menu_item('裁剪左右黑边', f"{settings['video']['crop_left']}px" if settings['video']['crop_left'] > 0 else '不裁剪'), crop_hint, settings['video']['crop_left'] > 0),
            MENU_SEPARATOR,
            menu_item(return_label),
            '',
        ]
        render_screen_menu('视频设置', context_lines, vm, selected_index=v_idx)
        v_idx = normalize_selected_index(vm, v_idx) or 0
        key = read_navigation_key()
        if allow_episode_nav and key in ('LEFT', 'RIGHT'):
            sel = get_selectable_indices(vm)
            if v_idx in sel:
                ai = sel.index(v_idx)
                if ai not in (1, 2, 3, 4):
                    update_current_episode(ctx['current_file_idx'] + (-1 if key == 'LEFT' else 1))
                    continue
        if key == 'UP':
            v_idx = get_next_selectable(vm, v_idx, -1)
            continue
        if key == 'DOWN':
            v_idx = get_next_selectable(vm, v_idx, 1)
            continue
        if key == 'BACKSPACE':
            break
        if key not in ('LEFT', 'RIGHT', 'ENTER'):
            continue
        sel = get_selectable_indices(vm)
        if v_idx not in sel:
            continue
        ai = sel.index(v_idx)
        step = -1 if key == 'LEFT' else 1
        if ai == 0:
            settings['video']['hevc'] = not settings['video']['hevc']
        elif ai == 1 and key in ('LEFT', 'RIGHT'):
            settings['video']['ss'] = adjust_time_setting(settings['video']['ss'], step * 5)
        elif ai == 2 and key in ('LEFT', 'RIGHT'):
            settings['video']['to'] = adjust_time_setting(settings['video']['to'], step * 5)
        elif ai == 3 and key in ('LEFT', 'RIGHT'):
            settings['video']['crop_top'] = max(0, min(max(0, first_height // 4 - 1), settings['video']['crop_top'] + step * 2))
        elif ai == 4 and key in ('LEFT', 'RIGHT'):
            settings['video']['crop_left'] = max(0, min(max(0, first_width // 4 - 1), settings['video']['crop_left'] + step * 2))
        elif ai == 5:
            break
