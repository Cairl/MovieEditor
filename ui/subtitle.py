# 字幕设置菜单
import re
import os
from ui.console import CURSOR_HOME, hide_cursor, ANSI_ESCAPE
from ui.display import MENU_SEPARATOR, menu_item, with_ffmpeg_hint, render_screen_menu, pad_display, get_display_width
from core.helpers import format_on_off
from ui.navigation import read_navigation_key, get_selectable_indices, get_next_selectable, normalize_selected_index
from core.helpers import truncate_name, get_full_language_name


def handle_subtitle_settings_menu(ctx: dict, context_lines: list, allow_episode_nav: bool = False, return_label: str = '返回') -> None:
    settings = ctx['settings']
    subtitle_streams = ctx['subtitle_streams']
    update_current_episode = ctx['update_current_episode']
    choose_files_fn = ctx['choose_files']

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
            subtitle_items_data = []
            max_idx_w = max((len(str(s['rel_index'] + 1)) for s in subtitle_streams), default=1)
            max_label_w = 0
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
        sm.extend([MENU_SEPARATOR, menu_item(return_label), ''])
        render_screen_menu('字幕设置', context_lines, sm, selected_index=s_idx)
        s_idx = normalize_selected_index(sm, s_idx) or 0
        key = read_navigation_key()
        if allow_episode_nav and key in ('LEFT', 'RIGHT'):
            update_current_episode(ctx['current_file_idx'] + (-1 if key == 'LEFT' else 1))
            continue
        if key == 'UP':
            s_idx = get_next_selectable(sm, s_idx, -1)
            continue
        if key == 'DOWN':
            s_idx = get_next_selectable(sm, s_idx, 1)
            continue
        if key in ('SHIFT_UP', 'SHIFT_DOWN'):
            selectable = get_selectable_indices(sm)
            if s_idx not in selectable:
                continue
            idx_in_sel = selectable.index(s_idx)
            if idx_in_sel >= 3:
                pos = idx_in_sel - 3
                if settings['subtitle']['mode'] == 'internal':
                    if 0 <= pos < len(subtitle_streams):
                        target_idx = pos - 1 if key == 'SHIFT_UP' else pos + 1
                        if 0 <= target_idx < len(subtitle_streams):
                            subtitle_streams[pos], subtitle_streams[target_idx] = subtitle_streams[target_idx], subtitle_streams[pos]
                            s_idx = selectable[selectable.index(s_idx) + (target_idx - pos)]
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
                            s_idx = selectable[selectable.index(s_idx) + (target_idx - pos)]
            continue
        if key == 'BACKSPACE':
            break
        if key not in ('LEFT', 'RIGHT', 'ENTER'):
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
                for k in list(d.keys()):
                    if d[k] and not found:
                        found = True
                    else:
                        d[k] = False
        elif re.search(r'导入字幕\s*:', selected_line):
            if key in ('RIGHT', 'ENTER'):
                files = choose_files_fn('选择字幕文件', [('字幕文件', '*.srt *.ass *.ssa *.vtt *.sup'), ('所有文件', '*.*')])
                if files:
                    settings['subtitle']['mode'] = 'external'
                    settings['subtitle']['files'] = files
                    settings['subtitle']['external_streams'] = {str(i): (not settings['subtitle']['burn_in'] or i == 0) for i in range(len(files))}
        elif re.search(r'关闭所有字幕\s*:', selected_line):
            new_disable = not settings['subtitle']['disable']
            settings['subtitle']['disable'] = new_disable
            d = settings['subtitle']['internal_streams'] if settings['subtitle']['mode'] == 'internal' else settings['subtitle']['external_streams']
            for k in d:
                d[k] = not new_disable
        elif re.search(r'返回', selected_line):
            break
        else:
            idx_in_sel = selectable.index(s_idx)
            if idx_in_sel >= 3:
                pos = idx_in_sel - 3
                if settings['subtitle']['mode'] == 'internal':
                    if 0 <= pos < len(subtitle_streams):
                        skey = str(subtitle_streams[pos]['index'])
                        if settings['subtitle']['burn_in']:
                            for k in settings['subtitle']['internal_streams']:
                                settings['subtitle']['internal_streams'][k] = False
                            settings['subtitle']['internal_streams'][skey] = True
                            settings['subtitle']['disable'] = False
                        else:
                            cur = settings['subtitle']['internal_streams'].get(skey, True)
                            new_val = not cur
                            settings['subtitle']['internal_streams'][skey] = new_val
                            if new_val:
                                settings['subtitle']['disable'] = False
                elif settings['subtitle']['mode'] == 'external':
                    if 0 <= pos < len(settings['subtitle']['files']):
                        fkey = str(pos)
                        if settings['subtitle']['burn_in']:
                            for k in settings['subtitle']['external_streams']:
                                settings['subtitle']['external_streams'][k] = False
                            settings['subtitle']['external_streams'][fkey] = True
                            settings['subtitle']['disable'] = False
                        else:
                            cur = settings['subtitle']['external_streams'].get(fkey, True)
                            new_val = not cur
                            settings['subtitle']['external_streams'][fkey] = new_val
                            if new_val:
                                settings['subtitle']['disable'] = False
