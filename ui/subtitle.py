# 字幕设置菜单
import re
import os
from ui.console import UI_COLORS
from ui.display import MENU_SEPARATOR, menu_item, with_ffmpeg_hint, pad_display, get_display_width, menu_return_item, Action, run_menu_loop
from core.helpers import truncate_name, get_full_language_name, format_on_off


def handle_subtitle_settings_menu(ctx: dict, context_lines: list, allow_episode_nav: bool = False, return_label: str = '返回') -> None:
    settings = ctx['settings']
    subtitle_streams = ctx['subtitle_streams']
    update_current_episode = ctx['update_current_episode']
    choose_files_fn = ctx['choose_files']

    def build_menu():
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
                import_hint = f"-vf subtitles={truncate_name(os.path.basename(settings['subtitle']['files'][selected_external_idx]))}"
            elif not settings['subtitle']['burn_in'] and enabled_external_idx:
                import_hint = '-i <字幕文件> -map N:s:0'
        disable_status = format_on_off(settings['subtitle']['disable'])
        disable_hint = '-sn' if settings['subtitle']['disable'] else None
        sm = [
            with_ffmpeg_hint(menu_item('烧制字幕', burn_status), burn_hint, bool(burn_hint)),
            with_ffmpeg_hint(menu_item('导入字幕', import_value), import_hint, bool(import_hint)),
            with_ffmpeg_hint(menu_item('关闭所有字幕', disable_status), disable_hint, bool(disable_hint)),
            MENU_SEPARATOR,
        ]
        if settings['subtitle']['mode'] == 'internal':
            max_idx_w = max((len(str(s['rel_index'] + 1)) for s in subtitle_streams), default=1)
            max_label_w = 0
            subtitle_items_data = []
            for pos, s in enumerate(subtitle_streams):
                padded_idx = str(s['rel_index'] + 1).ljust(max_idx_w)
                raw_name = s['raw_display_name']
                lang_name = get_full_language_name(s['language'])
                if s['title'] and s['title'].lower() != lang_name.lower():
                    sub_display_name = f"{lang_name}, {s['title']}"
                else:
                    sub_display_name = lang_name
                full_label = f"#{padded_idx} .{raw_name} - {sub_display_name}"
                max_label_w = max(max_label_w, get_display_width(full_label))
                subtitle_items_data.append((pos, s, full_label))
            for pos, s, full_label in subtitle_items_data:
                key = str(s['index'])
                enabled = settings['subtitle']['internal_streams'].get(key, True)
                status = format_on_off(enabled)
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
                line = menu_item(f"[{i}] {truncate_name(os.path.basename(f))}", status)
                hint = None
                if enabled:
                    if settings['subtitle']['burn_in'] and selected_external_idx == i:
                        hint = f"-vf subtitles={truncate_name(os.path.basename(f))}"
                    elif not settings['subtitle']['burn_in']:
                        hint = f"-i {truncate_name(os.path.basename(f))} -map N:s:0"
                sm.append(with_ffmpeg_hint(line, hint, bool(hint)))
        sm.extend([MENU_SEPARATOR, menu_return_item(return_label), ''])
        return sm

    def action_handler(key, selected_item, idx_in_sel):
        if key in ('SHIFT_UP', 'SHIFT_DOWN'):
            pos = idx_in_sel - 3
            if settings['subtitle']['mode'] == 'internal':
                if 0 <= pos < len(subtitle_streams):
                    target_idx = pos - 1 if key == 'SHIFT_UP' else pos + 1
                    if 0 <= target_idx < len(subtitle_streams):
                        subtitle_streams[pos], subtitle_streams[target_idx] = subtitle_streams[target_idx], subtitle_streams[pos]
            elif settings['subtitle']['mode'] == 'external':
                if 0 <= pos < len(settings['subtitle']['files']):
                    target_idx = pos - 1 if key == 'SHIFT_UP' else pos + 1
                    if 0 <= target_idx < len(settings['subtitle']['files']):
                        files = settings['subtitle']['files']
                        files[pos], files[target_idx] = files[target_idx], files[pos]
                        states = settings['subtitle']['external_streams']
                        s1, s2 = str(pos), str(target_idx)
                        v1, v2 = states.get(s1, True), states.get(s2, True)
                        states[s1], states[s2] = v2, v1
            return Action.CONTINUE

        if re.search(r'烧制字幕\s*:', selected_item):
            settings['subtitle']['burn_in'] = not settings['subtitle']['burn_in']
            if settings['subtitle']['burn_in']:
                d = settings['subtitle']['internal_streams'] if settings['subtitle']['mode'] == 'internal' else settings['subtitle']['external_streams']
                first_enabled = next((k for k in d if d[k]), None)
                for k in d:
                    d[k] = (k == first_enabled)
        elif re.search(r'导入字幕\s*:', selected_item):
            if key in ('RIGHT', 'ENTER'):
                files = choose_files_fn('选择字幕文件', [('字幕文件', '*.srt *.ass *.ssa *.vtt *.sup'), ('所有文件', '*.*')])
                if files:
                    settings['subtitle']['mode'] = 'external'
                    settings['subtitle']['files'] = files
                    settings['subtitle']['external_streams'] = {str(i): (not settings['subtitle']['burn_in'] or i == 0) for i in range(len(files))}
        elif re.search(r'关闭所有字幕\s*:', selected_item):
            new_disable = not settings['subtitle']['disable']
            settings['subtitle']['disable'] = new_disable
            d = settings['subtitle']['internal_streams'] if settings['subtitle']['mode'] == 'internal' else settings['subtitle']['external_streams']
            for k in d:
                d[k] = not new_disable
        elif re.search(r'返回', selected_item):
            return Action.BREAK
        elif idx_in_sel >= 3:
            pos = idx_in_sel - 3
            streams_dict = None
            stream_key = None
            if settings['subtitle']['mode'] == 'internal' and 0 <= pos < len(subtitle_streams):
                streams_dict = settings['subtitle']['internal_streams']
                stream_key = str(subtitle_streams[pos]['index'])
            elif settings['subtitle']['mode'] == 'external' and 0 <= pos < len(settings['subtitle']['files']):
                streams_dict = settings['subtitle']['external_streams']
                stream_key = str(pos)
            if streams_dict is not None:
                if settings['subtitle']['burn_in']:
                    for k in streams_dict:
                        streams_dict[k] = (k == stream_key)
                    settings['subtitle']['disable'] = False
                else:
                    new_val = not streams_dict.get(stream_key, True)
                    streams_dict[stream_key] = new_val
                    if new_val:
                        settings['subtitle']['disable'] = False
        return None

    run_menu_loop(
        '字幕设置', context_lines, build_menu, action_handler,
        allow_episode_nav=allow_episode_nav,
        update_current_episode=update_current_episode,
        current_file_idx_ref=[ctx.get('current_file_idx', 0)],
        no_nav_indices={1},
    )
