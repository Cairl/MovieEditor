# 视频设置菜单
from ui.console import UI_COLORS
from ui.display import MENU_SEPARATOR, menu_item, with_ffmpeg_hint, menu_return_item, Action, run_menu_loop
from core.helpers import format_on_off, adjust_time_setting

TIME_ADJUST_STEP = 1   # seconds per LEFT/RIGHT press
CROP_ADJUST_STEP = 2   # pixels per LEFT/RIGHT press


def handle_video_settings_menu(ctx: dict, context_lines: list, allow_episode_nav: bool = False, return_label: str = '返回') -> None:
    settings = ctx['settings']
    first_width = ctx['first_width']
    first_height = ctx['first_height']
    build_crop_filter_text = ctx['build_crop_filter_text']
    update_current_episode = ctx['update_current_episode']

    HW_ENCODERS = ['none', 'nvenc', 'qsv', 'amf']
    HW_LABELS = {'none': 'CPU (默认)', 'nvenc': 'NVIDIA NVENC', 'qsv': 'Intel QSV', 'amf': 'AMD AMF'}
    HW_HINTS = {
        'none': None,
        'nvenc': None,
        'qsv': '-global_quality 23',
        'amf': '-quality balanced',
    }

    def _hevc_hint():
        """Dynamic H.265 hint — just the codec; HW flags live on the encoder row."""
        hw = settings['video'].get('hw_encoder', 'none')
        hevc = settings['video']['hevc']
        if hw == 'nvenc':
            return '-c:v hevc_nvenc' if hevc else '-c:v h264_nvenc'
        elif hw == 'qsv':
            return '-c:v hevc_qsv' if hevc else '-c:v h264_qsv'
        elif hw == 'amf':
            return '-c:v hevc_amf' if hevc else '-c:v h264_amf'
        else:
            return '-c:v hevc -crf 23' if hevc else '-c:v h264'

    def build_menu():
        crop_hint = f"-vf {build_crop_filter_text()}"
        hw = settings['video'].get('hw_encoder', 'none')
        hw_label = HW_LABELS.get(hw, hw)
        hw_hint_text = HW_HINTS.get(hw)
        return [
            with_ffmpeg_hint(menu_item('H.265 编码', format_on_off(settings['video']['hevc'])), _hevc_hint(), settings['video']['hevc']),
            with_ffmpeg_hint(menu_item('硬件编码', hw_label), hw_hint_text, hw != 'none'),
            MENU_SEPARATOR,
            with_ffmpeg_hint(menu_item('开始时间', settings['video']['ss'] or '未设置'), f"-ss {settings['video']['ss']}" if settings['video']['ss'] else None, bool(settings['video']['ss'])),
            with_ffmpeg_hint(menu_item('结束时间', settings['video']['to'] or '未设置'), f"-to {settings['video']['to']}" if settings['video']['to'] else None, bool(settings['video']['to'])),
            MENU_SEPARATOR,
            with_ffmpeg_hint(menu_item('裁剪上下黑边', f"{settings['video']['crop_top']}px" if settings['video']['crop_top'] > 0 else '不裁剪'), crop_hint, settings['video']['crop_top'] > 0),
            with_ffmpeg_hint(menu_item('裁剪左右黑边', f"{settings['video']['crop_left']}px" if settings['video']['crop_left'] > 0 else '不裁剪'), crop_hint, settings['video']['crop_left'] > 0),
            MENU_SEPARATOR,
            menu_return_item(return_label),
            '',
        ]

    def action_handler(key, selected_item, idx_in_sel):
        step = -1 if key in ('LEFT', 'SHIFT_LEFT') else 1
        if idx_in_sel == 0:
            settings['video']['hevc'] = not settings['video']['hevc']
        elif idx_in_sel == 1 and key in ('LEFT', 'RIGHT'):
            hw_list = HW_ENCODERS
            cur_hw = settings['video'].get('hw_encoder', 'none')
            cur_idx = hw_list.index(cur_hw) if cur_hw in hw_list else 0
            new_idx = (cur_idx + step) % len(hw_list)
            settings['video']['hw_encoder'] = hw_list[new_idx]
        elif idx_in_sel == 2 and key in ('LEFT', 'RIGHT', 'SHIFT_LEFT', 'SHIFT_RIGHT'):
            delta = 60 if key in ('SHIFT_LEFT', 'SHIFT_RIGHT') else TIME_ADJUST_STEP
            settings['video']['ss'] = adjust_time_setting(settings['video']['ss'], step * delta)
        elif idx_in_sel == 3 and key in ('LEFT', 'RIGHT', 'SHIFT_LEFT', 'SHIFT_RIGHT'):
            delta = 60 if key in ('SHIFT_LEFT', 'SHIFT_RIGHT') else TIME_ADJUST_STEP
            settings['video']['to'] = adjust_time_setting(settings['video']['to'], step * delta)
        elif idx_in_sel == 4 and key in ('LEFT', 'RIGHT'):
            settings['video']['crop_top'] = max(0, min(max(0, first_height // 4 - 1), settings['video']['crop_top'] + step * CROP_ADJUST_STEP))
        elif idx_in_sel == 5 and key in ('LEFT', 'RIGHT'):
            settings['video']['crop_left'] = max(0, min(max(0, first_width // 4 - 1), settings['video']['crop_left'] + step * CROP_ADJUST_STEP))
        elif idx_in_sel == 6:
            return Action.BREAK
        return None

    run_menu_loop(
        '视频设置', context_lines, build_menu, action_handler,
        allow_episode_nav=allow_episode_nav,
        update_current_episode=update_current_episode,
        current_file_idx_ref=[ctx.get('current_file_idx', 0)],
        no_nav_indices={0, 1, 2, 3, 4, 5},
    )
