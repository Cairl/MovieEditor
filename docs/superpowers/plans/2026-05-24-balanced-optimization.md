# MovieEditor 均衡优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking tracking.

**Goal:** 对 movie_editor.py 进行代码质量、性能、用户体验三维度优化，保持单文件架构。

**Architecture:** 在 1770 行单文件内，通过 dataclass 替代嵌套 dict、提取 menu_loop 框架消除重复代码、添加 ffprobe 缓存和设置持久化、增强批量处理健壮性、新增自动黑边检测。

**Tech Stack:** Python 3.12+（标准库 dataclasses）、ffmpeg/ffprobe CLI、Windows msvcrt/ctypes

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `movie_editor.py` | 修改 | 唯一源文件，所有改动集中于此 |

---

## Task 1: 添加 dataclass 定义和 import

**Files:**
- Modify: `movie_editor.py:1-16` (import 区域)
- Modify: `movie_editor.py:88-100` (常量区域后，插入 dataclass 定义)

- [ ] **Step 1: 添加 dataclass import**

在 `movie_editor.py` 第 5 行 `import json` 后添加：

```python
from dataclasses import dataclass, field, asdict
```

- [ ] **Step 2: 在常量区域后添加 dataclass 定义**

在 `MAX_DISPLAY_NAME_LEN = 40` (L100) 之后、`truncate_name` 函数 (L103) 之前插入：

```python
@dataclass
class VideoSettings:
    hevc: bool = True
    resolution: Optional[str] = None
    crop_top: int = 0
    crop_left: int = 0
    ss: Optional[str] = None
    to: Optional[str] = None

@dataclass
class AudioSettings:
    reencode: bool = True
    codec: str = 'copy'
    internal_streams: dict[str, bool] = field(default_factory=dict)

@dataclass
class SubtitleSettings:
    mode: str = 'internal'
    files: list[str] = field(default_factory=list)
    burn_in: bool = False
    disable: bool = False
    codec: str = 'copy'
    internal_streams: dict[str, bool] = field(default_factory=dict)
    external_streams: dict[str, bool] = field(default_factory=dict)

@dataclass
class AppSettings:
    video: VideoSettings = field(default_factory=VideoSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    subtitle: SubtitleSettings = field(default_factory=SubtitleSettings)
```

- [ ] **Step 3: 验证 import 无报错**

Run: `python -c "from dataclasses import dataclass, field, asdict; print('OK')"`
Expected: `OK`

---

## Task 2: 替换 settings 初始化为 AppSettings

**Files:**
- Modify: `movie_editor.py:1128-1132` (settings dict 初始化)

- [ ] **Step 1: 替换 settings dict 为 AppSettings 实例**

将 L1128-1132：

```python
    settings = {
        'video': {'hevc': True, 'resolution': None, 'crop_top': 0, 'crop_left': 0, 'ss': None, 'to': None},
        'audio': {'reencode': True, 'codec': 'copy', 'internal_streams': {}},
        'subtitle': {'mode': 'internal', 'files': [], 'burn_in': False, 'disable': False, 'codec': 'copy', 'internal_streams': {}, 'external_streams': {}},
    }
```

替换为：

```python
    settings = AppSettings()
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "exec(open('movie_editor.py', encoding='utf-8').read().split('def process_files')[0]); s = AppSettings(); print(s.video.hevc, s.audio.codec, s.subtitle.mode)"`
Expected: `True copy internal`

---

## Task 3: 迁移 build_crop_filter_text 中的 settings 访问

**Files:**
- Modify: `movie_editor.py:1137-1138`

- [ ] **Step 1: 替换 build_crop_filter_text 中的 dict 访问**

将 L1138：

```python
        return f"crop=in_w-{settings['video']['crop_left']*2}:in_h-{settings['video']['crop_top']*2}:{settings['video']['crop_left']}:{settings['video']['crop_top']}"
```

替换为：

```python
        return f"crop=in_w-{settings.video.crop_left*2}:in_h-{settings.video.crop_top*2}:{settings.video.crop_left}:{settings.video.crop_top}"
```

- [ ] **Step 2: 验证无语法错误**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 4: 迁移 build_ffmpeg_command 中的 settings 访问

**Files:**
- Modify: `movie_editor.py:1140-1240`

- [ ] **Step 1: 替换 build_ffmpeg_command 中所有 settings dict 访问**

逐行替换 L1150-L1237 中的所有 `settings['video'][...]` / `settings['audio'][...]` / `settings['subtitle'][...]` 为属性访问。完整替换清单：

L1150: `settings['video']['crop_top']` → `settings.video.crop_top` (2处)
L1150: `settings['video']['crop_left']` → `settings.video.crop_left` (2处)
L1153: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams` (1处)
L1156: `settings['audio']['internal_streams']` → `settings.audio.internal_streams` (1处)
L1161: `settings['subtitle']['files']` → `settings.subtitle.files` (1处)
L1161: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams` (1处)
L1163: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in` (1处)
L1163: `settings['subtitle']['disable']` → `settings.subtitle.disable` (1处)
L1164: `settings['subtitle']['mode']` → `settings.subtitle.mode` (1处)
L1168: `settings['subtitle']['mode']` → `settings.subtitle.mode` (1处)
L1175: `settings['audio']['internal_streams']` → `settings.audio.internal_streams` (1处)
L1182: `settings['subtitle']['disable']` → `settings.subtitle.disable` (1处)
L1182: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in` (1处)
L1183: `settings['subtitle']['mode']` → `settings.subtitle.mode` (1处)
L1185: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams` (1处)
L1198: `settings['video']['hevc']` → `settings.video.hevc` (1处)
L1205: `settings['audio']['reencode']` → `settings.audio.reencode` (1处)
L1207: `settings['audio']['codec']` → `settings.audio.codec` (2处)
L1210: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in` (1处)
L1212: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in` (1处)
L1213: `settings['subtitle']['mode']` → `settings.subtitle.mode` (2处)
L1216: `settings['subtitle']['codec']` → `settings.subtitle.codec` (2处)
L1230: `settings['video']['resolution']` → `settings.video.resolution` (3处)
L1234: `settings['video']['ss']` → `settings.video.ss` (2处)
L1236: `settings['video']['to']` → `settings.video.to` (2处)

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 5: 迁移 calculate_effective_duration 和 build_episode_context

**Files:**
- Modify: `movie_editor.py:1242-1254`

- [ ] **Step 1: 替换 calculate_effective_duration 中的 settings 访问**

将 L1243-1244：

```python
        start_sec = parse_time_to_seconds(settings['video']['ss'])
        end_sec = parse_time_to_seconds(settings['video']['to'])
```

替换为：

```python
        start_sec = parse_time_to_seconds(settings.video.ss)
        end_sec = parse_time_to_seconds(settings.video.to)
```

`build_episode_context` (L1253-1254) 无 settings 访问，无需修改。

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 6: 迁移 handle_video_settings_menu 中的 settings 访问

**Files:**
- Modify: `movie_editor.py:1256-1310`

- [ ] **Step 1: 替换 handle_video_settings_menu 中所有 settings dict 访问**

L1263: `settings['video']['hevc']` → `settings.video.hevc` (2处)
L1265: `settings['video']['ss']` → `settings.video.ss` (3处)
L1266: `settings['video']['to']` → `settings.video.to` (3处)
L1268: `settings['video']['crop_top']` → `settings.video.crop_top` (3处)
L1269: `settings['video']['crop_left']` → `settings.video.crop_left` (3处)
L1300: `settings['video']['hevc']` → `settings.video.hevc` (2处)
L1302: `settings['video']['ss']` → `settings.video.ss` (2处)
L1304: `settings['video']['to']` → `settings.video.to` (2处)
L1306: `settings['video']['crop_top']` → `settings.video.crop_top` (2处)
L1308: `settings['video']['crop_left']` → `settings.video.crop_left` (2处)

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 7: 迁移 handle_audio_settings_menu 中的 settings 访问

**Files:**
- Modify: `movie_editor.py:1312-1377`

- [ ] **Step 1: 替换 handle_audio_settings_menu 中所有 settings dict 访问**

L1319: `settings['audio']['internal_streams']` → `settings.audio.internal_streams` (1处)
L1320: `settings['audio']['internal_streams'][key]` → `settings.audio.internal_streams[key]` (1处)
L1321: `settings['audio']['reencode']` → `settings.audio.reencode` (2处)
L1321: `settings['audio']['codec']` → `settings.audio.codec` (1处)
L1322: `settings['audio']['codec']` → `settings.audio.codec` (2处)
L1324: `settings['audio']['reencode']` → `settings.audio.reencode` (2处)
L1325: `settings['audio']['codec']` → `settings.audio.codec` (3处)
L1325: `settings['audio']['reencode']` → `settings.audio.reencode` (1处)
L1331: `settings['audio']['internal_streams']` → `settings.audio.internal_streams` (1处)
L1364: `settings['audio']['reencode']` → `settings.audio.reencode` (2处)
L1367: `settings['audio']['codec']` → `settings.audio.codec` (2处)
L1376: `settings['audio']['internal_streams']` → `settings.audio.internal_streams` (1处)
L1377: `settings['audio']['internal_streams'][skey]` → `settings.audio.internal_streams[skey]` (2处)

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 8: 迁移 handle_subtitle_settings_menu 中的 settings 访问

**Files:**
- Modify: `movie_editor.py:1379-1538`

- [ ] **Step 1: 替换 handle_subtitle_settings_menu 中所有 settings dict 访问**

此函数有约 30 处 settings 访问，按出现顺序替换：

L1386: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams`
L1387: `settings['subtitle']['internal_streams'][key]` → `settings.subtitle.internal_streams[key]`
L1388: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1388: `settings['subtitle']['files']` → `settings.subtitle.files`
L1389: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1390: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams`
L1392: `settings['subtitle']['files']` → `settings.subtitle.files`
L1392: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1394: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1395: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1396: `settings['subtitle']['files']` → `settings.subtitle.files`
L1398: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1399: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1400: `settings['subtitle']['files']` → `settings.subtitle.files`
L1401: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1408: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1425: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams`
L1431: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1433: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1437: `settings['subtitle']['files']` → `settings.subtitle.files`
L1438: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1443: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1445: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1470: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1476: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1477: `settings['subtitle']['files']` → `settings.subtitle.files`
L1479: `settings['subtitle']['files']` → `settings.subtitle.files`
L1480: `settings['subtitle']['files']` → `settings.subtitle.files`
L1482: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1497: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1498: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1499: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams`
L1499: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1499: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1510: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1511: `settings['subtitle']['files']` → `settings.subtitle.files`
L1512: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1512: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1519: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1522: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1523: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams`
L1524: `settings['subtitle']['internal_streams'][k]` → `settings.subtitle.internal_streams[k]`
L1525: `settings['subtitle']['internal_streams'][skey]` → `settings.subtitle.internal_streams[skey]`
L1527: `settings['subtitle']['internal_streams']` → `settings.subtitle.internal_streams`
L1528: `settings['subtitle']['internal_streams'][skey]` → `settings.subtitle.internal_streams[skey]`
L1529: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1530: `settings['subtitle']['files']` → `settings.subtitle.files`
L1532: `settings['subtitle']['burn_in']` → `settings.subtitle.burn_in`
L1533: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1534: `settings['subtitle']['external_streams'][k]` → `settings.subtitle.external_streams[k]`
L1535: `settings['subtitle']['external_streams'][fkey]` → `settings.subtitle.external_streams[fkey]`
L1537: `settings['subtitle']['external_streams']` → `settings.subtitle.external_streams`
L1538: `settings['subtitle']['external_streams'][fkey]` → `settings.subtitle.external_streams[fkey]`

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 9: 迁移主循环和逐集处理中的 settings 访问

**Files:**
- Modify: `movie_editor.py:1540-1739`

- [ ] **Step 1: 替换主循环和逐集处理中所有 settings dict 访问**

L1574: `settings['video']['ss']` → `settings.video.ss`
L1575: `settings['video']['to']` → `settings.video.to`
L1576: `settings['video']['crop_top']` → `settings.video.crop_top`
L1577: `settings['video']['crop_left']` → `settings.video.crop_left`
L1601: `settings['video']['ss']` → `settings.video.ss`
L1602: `settings['video']['to']` → `settings.video.to`
L1603: `settings['video']['crop_top']` → `settings.video.crop_top`
L1604: `settings['video']['crop_left']` → `settings.video.crop_left`
L1646: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1646: `settings['subtitle']['files']` → `settings.subtitle.files`
L1647: `settings['subtitle']['files']` → `settings.subtitle.files`
L1648: `settings['subtitle']['files']` → `settings.subtitle.files`
L1697: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1697: `settings['subtitle']['files']` → `settings.subtitle.files`
L1698: `settings['subtitle']['files']` → `settings.subtitle.files`
L1699: `settings['subtitle']['files']` → `settings.subtitle.files`
L1737: `settings['subtitle']['mode']` → `settings.subtitle.mode`
L1737: `settings['subtitle']['files']` → `settings.subtitle.files`
L1738: `settings['subtitle']['files']` → `settings.subtitle.files`
L1739: `settings['subtitle']['files']` → `settings.subtitle.files`

- [ ] **Step 2: 全量验证 — 无残留 settings[ 访问**

Run: `python -c "content=open('movie_editor.py',encoding='utf-8').read(); count=content.count(\"settings['\"); print(f'Remaining settings dict accesses: {count}')"`
Expected: `Remaining settings dict accesses: 0`

- [ ] **Step 3: 验证完整 import**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('Syntax OK')"`
Expected: `Syntax OK`

---

## Task 10: 添加代码分区标记

**Files:**
- Modify: `movie_editor.py` (多处插入)

- [ ] **Step 1: 在以下位置插入分区标记**

在 import 区域结束后（`sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')` 之后）插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 全局常量与数据模型
# ═══════════════════════════════════════════════════════════════
```

在 `_console_has_input` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 键盘输入层
# ═══════════════════════════════════════════════════════════════
```

在 `register_child_process` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 进程管理
# ═══════════════════════════════════════════════════════════════
```

在 `hide_cursor` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 显示工具函数
# ═══════════════════════════════════════════════════════════════
```

在 `menu_section` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 菜单组件
# ═══════════════════════════════════════════════════════════════
```

在 `build_top_border` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ TUI 渲染层
# ═══════════════════════════════════════════════════════════════
```

在 `get_video_resolution` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ FFmpeg 探针
# ═══════════════════════════════════════════════════════════════
```

在 `format_preview_lines` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ FFmpeg 执行
# ═══════════════════════════════════════════════════════════════
```

在 `choose_files` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 文件选择
# ═══════════════════════════════════════════════════════════════
```

在 `process_files` 函数前插入：

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 主流程
# ═══════════════════════════════════════════════════════════════
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 11: 实现 ffprobe 缓存

**Files:**
- Modify: `movie_editor.py` (process_files 函数内部)

- [ ] **Step 1: 在 process_files() 内、update_current_episode 之前添加缓存**

在 `update_current_episode` 函数定义之前插入：

```python
    _probe_cache: dict[str, dict] = {}

    def get_cached_probe(file_path: str) -> dict:
        if file_path not in _probe_cache:
            _probe_cache[file_path] = {
                'resolution': get_video_resolution(file_path),
                'duration': get_video_duration(file_path),
                'audio': get_audio_streams(file_path),
                'subtitle': get_subtitle_streams(file_path),
            }
        return _probe_cache[file_path]
```

- [ ] **Step 2: 改写 update_current_episode 使用缓存**

将 `update_current_episode` 函数体替换为：

```python
    def update_current_episode(idx):
        nonlocal current_file_idx, first_file, first_width, first_height, audio_streams, subtitle_streams, resolution_options
        current_file_idx = idx % len(input_paths)
        first_file = input_paths[current_file_idx]
        probe = get_cached_probe(first_file)
        first_width, first_height = probe['resolution']
        audio_streams = probe['audio']
        subtitle_streams = probe['subtitle']
        resolution_options = build_resolution_options(first_width, first_height)
```

- [ ] **Step 3: 改写 calculate_effective_duration 使用缓存**

将 `calculate_effective_duration` 函数体替换为：

```python
    def calculate_effective_duration(file_path: str) -> float:
        start_sec = parse_time_to_seconds(settings.video.ss)
        end_sec = parse_time_to_seconds(settings.video.to)
        probe = get_cached_probe(file_path)
        file_duration = probe['duration']
        calc_duration = float(file_duration)
        if end_sec is not None and end_sec > 0:
            calc_duration = float(end_sec)
        if start_sec is not None and start_sec > 0:
            calc_duration -= float(start_sec)
        return max(0.0, calc_duration)
```

- [ ] **Step 4: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 12: 实现 menu_loop 框架

**Files:**
- Modify: `movie_editor.py` (在菜单组件分区后、TUI 渲染层前插入)

- [ ] **Step 1: 在菜单组件分区末尾、TUI 渲染层分区标记之前插入 menu_loop**

```python
def menu_loop(
    title: str,
    context_lines: list[str],
    build_items: Callable[[], list[str]],
    on_action: Callable[[str, int, list[str]], Optional[str]],
    allow_episode_nav: bool = False,
    episode_nav_filter: Optional[Callable[[int, list[str]], bool]] = None,
    on_shift: Optional[Callable[[str, int, list[str]], None]] = None,
    return_label: str = '返回',
    footer_hint: Optional[str] = None,
) -> None:
    idx = 0
    while True:
        items = build_items()
        items.append(MENU_SEPARATOR)
        items.append(menu_item(return_label))
        items.append('')
        render_screen_menu(title, context_lines, items, selected_index=idx, footer_hint=footer_hint)
        idx = normalize_selected_index(items, idx) or 0
        key = read_navigation_key()

        if key == 'UP':
            idx = get_next_selectable(items, idx, -1)
            continue
        if key == 'DOWN':
            idx = get_next_selectable(items, idx, 1)
            continue
        if key == 'BACKSPACE':
            break

        if key in ('SHIFT_UP', 'SHIFT_DOWN'):
            if on_shift:
                selectable = get_selectable_indices(items)
                if idx in selectable:
                    on_shift(key, selectable.index(idx), items)
            continue

        if allow_episode_nav and key in ('LEFT', 'RIGHT'):
            selectable = get_selectable_indices(items)
            if idx in selectable:
                action_idx = selectable.index(idx)
                should_nav = (episode_nav_filter is None) or episode_nav_filter(action_idx, items)
                if should_nav:
                    update_current_episode(current_file_idx + (-1 if key == 'LEFT' else 1))
                    continue

        if key not in ('LEFT', 'RIGHT', 'ENTER'):
            continue

        selectable = get_selectable_indices(items)
        if idx not in selectable:
            continue

        action_idx = selectable.index(idx)
        if action_idx == len(selectable) - 1:
            break

        result = on_action(key, action_idx, items)
        if result == 'break':
            break
```

注意：此函数需要 `Callable` 类型，需在 import 区域添加 `from typing import Optional, Callable`。

- [ ] **Step 2: 添加 Callable import**

在 `from typing import Optional` 行改为：

```python
from typing import Optional, Callable
```

- [ ] **Step 3: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 13: 迁移 handle_video_settings_menu 到 menu_loop

**Files:**
- Modify: `movie_editor.py` (handle_video_settings_menu 函数)

- [ ] **Step 1: 重写 handle_video_settings_menu**

将整个 `handle_video_settings_menu` 函数替换为：

```python
    def handle_video_settings_menu(context_lines: list[str], allow_episode_nav: bool = False, return_label: str = '返回') -> None:
        def build_items():
            crop_hint = f"-vf {build_crop_filter_text()}"
            return [
                with_ffmpeg_hint(menu_item('H.265 编码', format_on_off(settings.video.hevc)), '-c:v hevc -crf 23', settings.video.hevc),
                MENU_SEPARATOR,
                with_ffmpeg_hint(menu_item('开始时间', settings.video.ss or '未设置'), f"-ss {settings.video.ss}" if settings.video.ss else None, bool(settings.video.ss)),
                with_ffmpeg_hint(menu_item('结束时间', settings.video.to or '未设置'), f"-to {settings.video.to}" if settings.video.to else None, bool(settings.video.to)),
                MENU_SEPARATOR,
                with_ffmpeg_hint(menu_item('裁剪上下黑边', f"{settings.video.crop_top}px" if settings.video.crop_top > 0 else '不裁剪'), crop_hint, settings.video.crop_top > 0),
                with_ffmpeg_hint(menu_item('裁剪左右黑边', f"{settings.video.crop_left}px" if settings.video.crop_left > 0 else '不裁剪'), crop_hint, settings.video.crop_left > 0),
            ]

        def on_action(key, action_idx, items):
            step = -1 if key == 'LEFT' else 1
            if action_idx == 0:
                settings.video.hevc = not settings.video.hevc
            elif action_idx == 1 and key in ('LEFT', 'RIGHT'):
                settings.video.ss = adjust_time_setting(settings.video.ss, step * 5)
            elif action_idx == 2 and key in ('LEFT', 'RIGHT'):
                settings.video.to = adjust_time_setting(settings.video.to, step * 5)
            elif action_idx == 3 and key in ('LEFT', 'RIGHT'):
                settings.video.crop_top = max(0, min(max(0, first_height // 4 - 1), settings.video.crop_top + step * 2))
            elif action_idx == 4 and key in ('LEFT', 'RIGHT'):
                settings.video.crop_left = max(0, min(max(0, first_width // 4 - 1), settings.video.crop_left + step * 2))

        menu_loop('视频设置', context_lines, build_items, on_action,
                  allow_episode_nav=allow_episode_nav,
                  episode_nav_filter=lambda ai, _: ai not in (1, 2, 3, 4),
                  return_label=return_label)
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 14: 迁移 handle_audio_settings_menu 到 menu_loop

**Files:**
- Modify: `movie_editor.py` (handle_audio_settings_menu 函数)

- [ ] **Step 1: 重写 handle_audio_settings_menu**

将整个 `handle_audio_settings_menu` 函数替换为：

```python
    def handle_audio_settings_menu(context_lines: list[str], allow_episode_nav: bool = False, return_label: str = '返回') -> None:
        def build_items():
            for s in audio_streams:
                key = str(s['index'])
                if key not in settings.audio.internal_streams:
                    settings.audio.internal_streams[key] = True
            codec_hint = None if (settings.audio.reencode and settings.audio.codec != 'copy') else ("-c:a copy" if not settings.audio.reencode else None)
            codec_name = '默认' if settings.audio.codec == 'copy' else settings.audio.codec.upper()
            items = [
                with_ffmpeg_hint(menu_item('重新编码', format_on_off(settings.audio.reencode)), codec_hint, not settings.audio.reencode),
                with_ffmpeg_hint(menu_item('音频编码格式', codec_name), f"-c:a {settings.audio.codec}" if settings.audio.reencode and settings.audio.codec != 'copy' else None, settings.audio.reencode and settings.audio.codec != 'copy'),
                MENU_SEPARATOR,
            ]
            max_a_idx_w = max((len(str(s['rel_index'] + 1)) for s in audio_streams), default=1)
            for i, s in enumerate(audio_streams):
                key = str(s['index'])
                enabled = settings.audio.internal_streams.get(key, True)
                status = format_on_off(enabled)
                channels = f"{s['channels']}ch" if s['channels'] else '2ch'
                padded_idx = str(s['rel_index'] + 1).ljust(max_a_idx_w)
                line = f"#{padded_idx} | {s['codec'].upper()} | {channels} | {s['language']} : {status}"
                hint = f"-map 0:a:{s['rel_index']}" if enabled else None
                items.append(with_ffmpeg_hint(line, hint, bool(hint)))
            return items

        def on_action(key, action_idx, items):
            selectable = get_selectable_indices(items)
            selected_line = ANSI_ESCAPE.sub('', items[selectable[action_idx]]).strip()
            if re.search(r'重新编码\s*:', selected_line):
                settings.audio.reencode = not settings.audio.reencode
            elif re.search(r'音频编码格式\s*:', selected_line):
                if key in ('LEFT', 'RIGHT'):
                    settings.audio.codec = cycle_option(settings.audio.codec, audio_codec_options, -1 if key == 'LEFT' else 1)
            else:
                stream_pos = action_idx - 2
                if 0 <= stream_pos < len(audio_streams):
                    skey = str(audio_streams[stream_pos]['index'])
                    cur = settings.audio.internal_streams.get(skey, True)
                    settings.audio.internal_streams[skey] = not cur

        menu_loop('音频设置', context_lines, build_items, on_action,
                  allow_episode_nav=allow_episode_nav,
                  return_label=return_label)
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 15: 迁移 handle_subtitle_settings_menu 到 menu_loop

**Files:**
- Modify: `movie_editor.py` (handle_subtitle_settings_menu 函数)

- [ ] **Step 1: 重写 handle_subtitle_settings_menu**

将整个 `handle_subtitle_settings_menu` 函数替换为：

```python
    def handle_subtitle_settings_menu(context_lines: list[str], allow_episode_nav: bool = False, return_label: str = '返回') -> None:
        def build_items():
            for s in subtitle_streams:
                key = str(s['index'])
                if key not in settings.subtitle.internal_streams:
                    settings.subtitle.internal_streams[key] = True
            if settings.subtitle.mode == 'external' and not settings.subtitle.files:
                settings.subtitle.mode = 'internal'
            enabled_internal_pos = [pos for pos, s in enumerate(subtitle_streams) if settings.subtitle.internal_streams.get(str(s['index']), True)]
            selected_internal_pos = enabled_internal_pos[0] if enabled_internal_pos else None
            enabled_external_idx = [i for i in range(len(settings.subtitle.files)) if settings.subtitle.external_streams.get(str(i), True)]
            selected_external_idx = enabled_external_idx[0] if enabled_external_idx else None
            burn_status = format_on_off(settings.subtitle.burn_in)
            burn_hint = '-sn' if settings.subtitle.burn_in else None
            import_value = f"{len(settings.subtitle.files)} 个文件" if settings.subtitle.files else '未导入'
            import_hint = None
            if settings.subtitle.mode == 'external':
                if settings.subtitle.burn_in and selected_external_idx is not None:
                    import_hint = f"-vf subtitles={truncate_name(os.path.basename(settings.subtitle.files[selected_external_idx]))}"
                elif not settings.subtitle.burn_in and enabled_external_idx:
                    import_hint = '-i <字幕文件> -map N:s:0'
            items = [
                with_ffmpeg_hint(menu_item('烧制字幕', burn_status), burn_hint, bool(burn_hint)),
                with_ffmpeg_hint(menu_item('导入字幕', import_value), import_hint, bool(import_hint)),
                MENU_SEPARATOR,
            ]
            if settings.subtitle.mode == 'internal':
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
                    enabled = settings.subtitle.internal_streams.get(key, True)
                    status = format_on_off(enabled)
                    padded_full_label = pad_display(full_label, max_label_w)
                    line = f"{padded_full_label} : {status}"
                    hint = None
                    if enabled:
                        if settings.subtitle.burn_in and selected_internal_pos == pos:
                            hint = f"-vf subtitles=input:si={s['rel_index']}"
                        elif not settings.subtitle.burn_in:
                            hint = f"-map 0:s:{s['rel_index']}"
                    items.append(with_ffmpeg_hint(line, hint, bool(hint)))
            else:
                for i, f in enumerate(settings.subtitle.files):
                    enabled = settings.subtitle.external_streams.get(str(i), True)
                    status = format_on_off(enabled)
                    line = menu_item(f"[{i}] {truncate_name(os.path.basename(f))}", status)
                    hint = None
                    if enabled:
                        if settings.subtitle.burn_in and selected_external_idx == i:
                            hint = f"-vf subtitles={truncate_name(os.path.basename(f))}"
                        elif not settings.subtitle.burn_in:
                            hint = f"-i {truncate_name(os.path.basename(f))} -map N:s:0"
                    items.append(with_ffmpeg_hint(line, hint, bool(hint)))
            return items

        def on_action(key, action_idx, items):
            selectable = get_selectable_indices(items)
            selected_line = ANSI_ESCAPE.sub('', items[selectable[action_idx]]).strip()
            if re.search(r'烧制字幕\s*:', selected_line):
                settings.subtitle.burn_in = not settings.subtitle.burn_in
                if settings.subtitle.burn_in:
                    d = settings.subtitle.internal_streams if settings.subtitle.mode == 'internal' else settings.subtitle.external_streams
                    found = False
                    for k in list(d.keys()):
                        if d[k] and not found:
                            found = True
                        else:
                            d[k] = False
            elif re.search(r'导入字幕\s*:', selected_line):
                if key in ('RIGHT', 'ENTER'):
                    files = choose_files('选择字幕文件', [('字幕文件', '*.srt *.ass *.ssa *.vtt *.sup'), ('所有文件', '*.*')])
                    if files:
                        settings.subtitle.mode = 'external'
                        settings.subtitle.files = files
                        settings.subtitle.external_streams = {str(i): (not settings.subtitle.burn_in or i == 0) for i in range(len(files))}
            else:
                idx_in_sel = action_idx
                if idx_in_sel >= 2:
                    pos = idx_in_sel - 2
                    if settings.subtitle.mode == 'internal':
                        if 0 <= pos < len(subtitle_streams):
                            skey = str(subtitle_streams[pos]['index'])
                            if settings.subtitle.burn_in:
                                for k in settings.subtitle.internal_streams:
                                    settings.subtitle.internal_streams[k] = False
                                settings.subtitle.internal_streams[skey] = True
                            else:
                                cur = settings.subtitle.internal_streams.get(skey, True)
                                settings.subtitle.internal_streams[skey] = not cur
                    elif settings.subtitle.mode == 'external':
                        if 0 <= pos < len(settings.subtitle.files):
                            fkey = str(pos)
                            if settings.subtitle.burn_in:
                                for k in settings.subtitle.external_streams:
                                    settings.subtitle.external_streams[k] = False
                                settings.subtitle.external_streams[fkey] = True
                            else:
                                cur = settings.subtitle.external_streams.get(fkey, True)
                                settings.subtitle.external_streams[fkey] = not cur

        def on_shift(key, action_idx, items):
            if action_idx >= 2:
                pos = action_idx - 2
                if settings.subtitle.mode == 'internal':
                    if 0 <= pos < len(subtitle_streams):
                        target_idx = pos - 1 if key == 'SHIFT_UP' else pos + 1
                        if 0 <= target_idx < len(subtitle_streams):
                            subtitle_streams[pos], subtitle_streams[target_idx] = subtitle_streams[target_idx], subtitle_streams[pos]
                elif settings.subtitle.mode == 'external':
                    if 0 <= pos < len(settings.subtitle.files):
                        target_idx = pos - 1 if key == 'SHIFT_UP' else pos + 1
                        if 0 <= target_idx < len(settings.subtitle.files):
                            files = settings.subtitle.files
                            files[pos], files[target_idx] = files[target_idx], files[pos]
                            states = settings.subtitle.external_streams
                            s1, s2 = str(pos), str(target_idx)
                            v1, v2 = states.get(s1, True), states.get(s2, True)
                            states[s1], states[s2] = v2, v1

        menu_loop('字幕设置', context_lines, build_items, on_action,
                  allow_episode_nav=allow_episode_nav,
                  on_shift=on_shift,
                  return_label=return_label,
                  footer_hint='↑↓ 选择   Shift+↑↓ 排序   Enter 执行')
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 16: 实现设置持久化

**Files:**
- Modify: `movie_editor.py` (文件选择分区后、主流程分区前插入函数)

- [ ] **Step 1: 在文件选择分区后插入 save_settings 和 load_settings 函数**

```python
def save_settings(settings: AppSettings, config_path: str) -> None:
    data = asdict(settings)
    data['version'] = 1
    for key in ('ss', 'to', 'crop_top', 'crop_left', 'resolution'):
        data['video'].pop(key, None)
    for key in ('internal_streams',):
        data['audio'].pop(key, None)
    for key in ('files', 'internal_streams', 'external_streams'):
        data['subtitle'].pop(key, None)
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except (IOError, OSError):
        pass


def load_settings(config_path: str) -> AppSettings:
    settings = AppSettings()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('version') != 1:
            return settings
        for section_key in ('video', 'audio', 'subtitle'):
            section_data = data.get(section_key, {})
            section_obj = getattr(settings, section_key)
            for field_name, value in section_data.items():
                if hasattr(section_obj, field_name):
                    setattr(section_obj, field_name, value)
    except (IOError, OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return settings
```

- [ ] **Step 2: 在 process_files() 中集成加载**

在 `settings = AppSettings()` 之后添加：

```python
        config_path = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'movie_editor', 'config.json')
        settings = load_settings(config_path)
```

注意：这行替换原来的 `settings = AppSettings()`。

- [ ] **Step 3: 在主循环退出时保存设置**

在 `process_files()` 函数末尾，`show_cursor()` 之前添加：

```python
    save_settings(settings, config_path)
```

注意：只在正常退出路径（主循环 break 后）保存，不在 KeyboardInterrupt 或 RuntimeError 路径保存。当前代码结构中，主循环 break 后执行到 L1729 `show_cursor()`，保存调用应在其之前。

- [ ] **Step 4: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 17: 批量处理增强 — 跳过已完成文件 + 总进度 + 错误重试

**Files:**
- Modify: `movie_editor.py` (process_files 内部，批量处理循环)

- [ ] **Step 1: 在 VideoSettings 中添加 force_overwrite 字段**

在 VideoSettings dataclass 中添加：

```python
    force_overwrite: bool = False
```

- [ ] **Step 2: 在主菜单中添加强制覆盖选项**

在主菜单构建代码中（`menu_item('FFmpeg 命令预览')` 之前）添加：

```python
            menu_item('强制覆盖', format_on_off(settings.video.force_overwrite)),
```

并在主循环的按键处理中添加对应逻辑（在 `'FFmpeg 命令预览'` 判断之前）：

```python
        elif '强制覆盖' in selected_plain:
            settings.video.force_overwrite = not settings.video.force_overwrite
```

- [ ] **Step 3: 实现错误重试菜单函数**

在 FFmpeg 执行分区中添加：

```python
def show_error_menu(error_msg: str) -> int:
    hide_cursor()
    lines = [
        f"{UI_COLORS['title']}编码错误{UI_COLORS['reset']}",
        MENU_SEPARATOR,
        f"{UI_COLORS['muted']}{trim_to_display_width(error_msg, 80)}{UI_COLORS['reset']}",
        MENU_SEPARATOR,
        menu_item('重试当前文件'),
        menu_item('跳过，继续下一个'),
        menu_item('中止全部'),
        '',
    ]
    idx = 0
    while True:
        render_screen_menu('错误', [], lines, selected_index=idx)
        idx = normalize_selected_index(lines, idx) or 0
        key = read_navigation_key()
        if key == 'UP':
            idx = get_next_selectable(lines, idx, -1)
            continue
        if key == 'DOWN':
            idx = get_next_selectable(lines, idx, 1)
            continue
        if key == 'ENTER':
            selectable = get_selectable_indices(lines)
            if idx in selectable:
                return selectable.index(idx) - 2
        if key == 'BACKSPACE':
            return 2
```

- [ ] **Step 4: 改写批量处理循环，添加跳过和重试逻辑**

将 `process_files()` 末尾的批量处理循环（当前代码从 `show_cursor()` 后开始）替换为：

```python
    show_cursor()
    try:
        total_count = len(input_paths)
        for i, path in enumerate(input_paths):
            if is_series_mode:
                os.makedirs(os.path.join(os.path.dirname(path), 'Edited'), exist_ok=True)

            ext_sub = None
            if is_series_mode and settings.subtitle.mode == 'external':
                if i < len(settings.subtitle.files):
                    ext_sub = settings.subtitle.files[i]

            command = build_ffmpeg_command(path, audio_streams, subtitle_streams, series_mode=is_series_mode, external_subtitle=ext_sub)
            out_path = command[-1]

            if not settings.video.force_overwrite and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                continue

            while True:
                try:
                    prefix = f"[{i+1}/{total_count}] {truncate_name(os.path.basename(path))}"
                    run_ffmpeg_with_progress(command, calculate_effective_duration(path), title_prefix=prefix)
                    break
                except RuntimeError as e:
                    choice = show_error_menu(str(e))
                    if choice == 0:
                        continue
                    elif choice == 1:
                        break
                    else:
                        return

        read_navigation_key()

    except KeyboardInterrupt:
        show_cursor()
        print('\n\n操作已取消')
        terminate_active_children()
    except (OSError, RuntimeError) as e:
        show_cursor()
        print(f'\n发生错误: {e}')
```

- [ ] **Step 5: 修复逐集处理模式的总进度显示**

在逐集处理模式中（`'确认处理当前集'` 分支），将 L1650 的 prefix：

```python
                            prefix = f"[{current_file_idx+1}/{len(input_paths)}] {truncate_name(os.path.basename(first_file))}"
```

此行已包含总进度格式，无需修改。确认即可。

- [ ] **Step 6: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 18: 实现自动黑边检测

**Files:**
- Modify: `movie_editor.py` (FFmpeg 探针分区添加 detect_crop 函数)
- Modify: `movie_editor.py` (handle_video_settings_menu 的 build_items 和 on_action)

- [ ] **Step 1: 在 FFmpeg 探针分区中添加 detect_crop 函数**

在 `get_subtitle_streams` 函数之后插入：

```python
def detect_crop(file_path: str) -> tuple[int, int]:
    duration = get_video_duration(file_path)
    seek_time = max(0, duration / 2) if duration > 0 else 0
    cmd = [
        'ffmpeg', '-y', '-hide_banner',
        '-ss', str(int(seek_time)),
        '-i', file_path,
        '-frames:v', '5',
        '-vf', 'cropdetect=limit=24:round=2',
        '-f', 'null', '-'
    ]
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
        crops = []
        for line in result.stderr.splitlines():
            match = re.search(r'crop=(\d+):(\d+):(\d+):(\d+)', line)
            if match:
                crops.append(tuple(map(int, match.groups())))
        if not crops:
            return 0, 0
        w, h, x, y = crops[-1]
        src_w, src_h = get_video_resolution(file_path)
        if src_w == 0 or src_h == 0:
            return 0, 0
        crop_top = y
        crop_left = x
        if crop_top > src_h // 4 or crop_left > src_w // 4:
            return 0, 0
        return crop_top, crop_left
    except (subprocess.SubprocessError, ValueError):
        return 0, 0
```

- [ ] **Step 2: 在 handle_video_settings_menu 的 build_items 中添加自动检测项**

在 `build_items` 返回列表中，裁剪左右黑边之后添加：

```python
                MENU_SEPARATOR,
                menu_item('自动检测黑边'),
```

完整的 build_items 返回值变为：

```python
            return [
                with_ffmpeg_hint(menu_item('H.265 编码', format_on_off(settings.video.hevc)), '-c:v hevc -crf 23', settings.video.hevc),
                MENU_SEPARATOR,
                with_ffmpeg_hint(menu_item('开始时间', settings.video.ss or '未设置'), f"-ss {settings.video.ss}" if settings.video.ss else None, bool(settings.video.ss)),
                with_ffmpeg_hint(menu_item('结束时间', settings.video.to or '未设置'), f"-to {settings.video.to}" if settings.video.to else None, bool(settings.video.to)),
                MENU_SEPARATOR,
                with_ffmpeg_hint(menu_item('裁剪上下黑边', f"{settings.video.crop_top}px" if settings.video.crop_top > 0 else '不裁剪'), crop_hint, settings.video.crop_top > 0),
                with_ffmpeg_hint(menu_item('裁剪左右黑边', f"{settings.video.crop_left}px" if settings.video.crop_left > 0 else '不裁剪'), crop_hint, settings.video.crop_left > 0),
                MENU_SEPARATOR,
                menu_item('自动检测黑边'),
            ]
```

- [ ] **Step 3: 在 on_action 中添加自动检测处理**

在 on_action 函数中，`elif action_idx == 4` 之后添加：

```python
            elif action_idx == 5 and key in ('RIGHT', 'ENTER'):
                crop_top, crop_left = detect_crop(first_file)
                if crop_top > 0 or crop_left > 0:
                    settings.video.crop_top = crop_top
                    settings.video.crop_left = crop_left
```

- [ ] **Step 4: 更新 episode_nav_filter**

由于新增了 action_idx 5（自动检测黑边），episode_nav_filter 需要更新：

```python
                  episode_nav_filter=lambda ai, _: ai not in (1, 2, 3, 4, 5),
```

自动检测黑边项不应触发剧集导航（LEFT/RIGHT 应传给 on_action 执行检测）。

- [ ] **Step 5: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

## Task 19: 最终验证

- [ ] **Step 1: 完整语法检查**

Run: `python -c "import ast; ast.parse(open('movie_editor.py', encoding='utf-8').read()); print('Syntax OK')"`

- [ ] **Step 2: 确认无残留 settings[ 访问**

Run: `python -c "content=open('movie_editor.py',encoding='utf-8').read(); count=content.count(\"settings['\"); print(f'Remaining: {count}')"`
Expected: `Remaining: 0`

- [ ] **Step 3: 确认 dataclass 定义完整**

Run: `python -c "exec(open('movie_editor.py',encoding='utf-8').read().split('def _console_has_input')[0]); s=AppSettings(); print(s.video.hevc, s.audio.codec, s.subtitle.mode, s.video.force_overwrite)"`
Expected: `True copy internal False`

- [ ] **Step 4: 确认新增函数存在**

Run: `python -c "content=open('movie_editor.py',encoding='utf-8').read(); assert 'def menu_loop' in content; assert 'def detect_crop' in content; assert 'def save_settings' in content; assert 'def load_settings' in content; assert 'def show_error_menu' in content; assert 'def get_cached_probe' in content; print('All functions present')"`
Expected: `All functions present`

- [ ] **Step 5: 确认分区标记存在**

Run: `python -c "content=open('movie_editor.py',encoding='utf-8').read(); markers=['键盘输入层','进程管理','显示工具函数','菜单组件','TUI 渲染层','FFmpeg 探针','FFmpeg 执行','文件选择','主流程']; missing=[m for m in markers if f'═─ {m}' not in content]; print('All markers present' if not missing else f'Missing: {missing}')"`
Expected: `All markers present`
