# MovieEditor 均衡优化设计

日期: 2026-05-24

## 概述

对 movie_editor.py（1770 行单文件）进行全面优化，涵盖代码质量、性能、用户体验三个维度。保持单文件架构不变，预计最终 ~1920 行。

## 约束

- 单文件架构：所有逻辑继续集中在 movie_editor.py
- Windows only：依赖 msvcrt、ctypes.windll
- 仅标准库 + ffmpeg/ffprobe CLI

---

## 一、内功 — 代码质量改进

### 1.1 dataclass 替代嵌套 dict

#### 现状

当前 settings 定义在 `process_files()` 内（L1128-1132）：

```python
settings = {
    'video': {'hevc': True, 'resolution': None, 'crop_top': 0, 'crop_left': 0, 'ss': None, 'to': None},
    'audio': {'reencode': True, 'codec': 'copy', 'internal_streams': {}},
    'subtitle': {'mode': 'internal', 'files': [], 'burn_in': False, 'disable': False, 'codec': 'copy', 'internal_streams': {}, 'external_streams': {}},
}
```

全文件共 **115 处** `settings[...]` 访问，分布在以下函数中：

| 函数 | 行号范围 | 访问次数 |
|------|---------|---------|
| `build_crop_filter_text` | L1137-1138 | 4 |
| `build_ffmpeg_command` | L1140-1240 | 22 |
| `calculate_effective_duration` | L1242-1251 | 2 |
| `handle_video_settings_menu` | L1256-1310 | 14 |
| `handle_audio_settings_menu` | L1312-1377 | 10 |
| `handle_subtitle_settings_menu` | L1379-1538 | 30 |
| 主循环 + 逐集处理 | L1540-1739 | 33 |

#### 目标

```python
from dataclasses import dataclass, field, asdict

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

定义位置：文件顶层，在 `UI_COLORS` / `UI_ICONS` 之后（约 L100），与 `MENU_LABEL_WIDTH` 等常量放在一起。

#### 迁移映射

所有 115 处访问按以下模式机械替换：

| 旧写法 | 新写法 |
|--------|--------|
| `settings['video']['hevc']` | `settings.video.hevc` |
| `settings['video']['ss']` | `settings.video.ss` |
| `settings['video']['to']` | `settings.video.to` |
| `settings['video']['crop_top']` | `settings.video.crop_top` |
| `settings['video']['crop_left']` | `settings.video.crop_left` |
| `settings['video']['resolution']` | `settings.video.resolution` |
| `settings['audio']['reencode']` | `settings.audio.reencode` |
| `settings['audio']['codec']` | `settings.audio.codec` |
| `settings['audio']['internal_streams']` | `settings.audio.internal_streams` |
| `settings['audio']['internal_streams'].get(key, True)` | `settings.audio.internal_streams.get(key, True)` |
| `settings['subtitle']['mode']` | `settings.subtitle.mode` |
| `settings['subtitle']['files']` | `settings.subtitle.files` |
| `settings['subtitle']['burn_in']` | `settings.subtitle.burn_in` |
| `settings['subtitle']['disable']` | `settings.subtitle.disable` |
| `settings['subtitle']['codec']` | `settings.subtitle.codec` |
| `settings['subtitle']['internal_streams']` | `settings.subtitle.internal_streams` |
| `settings['subtitle']['external_streams']` | `settings.subtitle.external_streams` |

初始化替换：`settings = {...}` → `settings = AppSettings()`

#### 需特殊处理的场景

1. **赋值语句**（如 `settings['video']['hevc'] = not settings['video']['hevc']`）：dataclass 字段可直接赋值，无需特殊处理
2. **`internal_streams` / `external_streams` 的 `.get()` 调用**：这些仍是普通 dict，`.get()` 用法不变
3. **`asdict(settings)` 序列化**：P3 设置持久化时使用，dataclass 原生支持

#### 验证方法

替换完成后 `python -c "import movie_editor"` 无报错即为通过。所有 dict key 拼写错误都会变成 AttributeError，运行时即可发现。

---

### 1.2 代码分区标记

#### 目标

在单文件内用醒目分隔注释建立逻辑模块感。分区及对应行号范围（基于当前 1770 行）：

| 分区 | 当前行号范围 | 内容 |
|------|-------------|------|
| Windows VT 处理 | L1-25 | import、SetConsoleMode、stdout 重定向 |
| 数据模型 | L27-98（新增） | 全局常量、dataclass 定义 |
| 键盘输入层 | L39-628 | _console_has_input / _console_read_key / read_navigation_key / clear_keyboard_buffer |
| 进程管理 | L115-148 | register/unregister/terminate_child_process |
| 显示工具函数 | L103-226 | truncate_name / get_display_width / trim_to_display_width / pad_display / format_hms / parse_time_to_seconds 等 |
| TUI 渲染层 | L228-498 | build_top_border / render_menu_box / render_preview_box / render_screen_menu / get_selectable_indices / get_next_selectable |
| 菜单组件 | L171-199 | menu_section / menu_item / with_ffmpeg_hint |
| FFmpeg 探针 | L663-758 | get_video_resolution / get_video_duration / _probe_streams_json / get_audio_streams / get_subtitle_streams |
| FFmpeg 执行 | L761-1047 | format_preview_lines / run_ffmpeg_with_progress |
| 文件选择 | L631-660 | choose_files / choose_file / choose_directory / get_video_files_in_dir |
| 主流程 | L1081-1770 | process_files 及其内部函数 |

#### 格式

```python
# ═══════════════════════════════════════════════════════════════
# ═─ 键盘输入层
# ═══════════════════════════════════════════════════════════════
```

注意：分区标记在 P1 阶段添加，后续阶段可能微调行号，但分区逻辑不变。

---

### 1.3 统一菜单按键分发 menu_loop

#### 现状分析

三个菜单处理器有几乎相同的按键处理骨架，每处 12 行重复代码：

```python
# handle_video_settings_menu (L1284-1293)
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

# handle_audio_settings_menu (L1349-1358) — 完全相同
# handle_subtitle_settings_menu (L1457-1490) — 完全相同 + SHIFT_UP/DOWN
```

此外，剧集导航逻辑也重复三次：

```python
# video (L1277-1283): 仅在非值调整项上导航
if allow_episode_nav and key in ('LEFT', 'RIGHT'):
    sel = get_selectable_indices(vm)
    if v_idx in sel:
        ai = sel.index(v_idx)
        if ai not in (1, 2, 3, 4):
            update_current_episode(...)

# audio (L1346-1348): 无条件导航
if allow_episode_nav and key in ('LEFT', 'RIGHT'):
    update_current_episode(...)

# subtitle (L1454-1456): 无条件导航
if allow_episode_nav and key in ('LEFT', 'RIGHT'):
    update_current_episode(...)
```

#### 目标接口

```python
MenuAction = Literal['break', 'continue', None]

def menu_loop(
    title: str,
    context_lines: list[str],
    build_items: Callable[[], list[str]],
    on_action: Callable[[str, int, list[str]], Optional[MenuAction]],
    allow_episode_nav: bool = False,
    episode_nav_filter: Optional[Callable[[int, list[str]], bool]] = None,
    return_label: str = '返回',
    footer_hint: Optional[str] = None,
) -> None:
```

参数说明：

| 参数 | 类型 | 说明 |
|------|------|------|
| `title` | str | 菜单标题，传给 render_screen_menu |
| `context_lines` | list[str] | 上下文行 |
| `build_items` | Callable | 无参函数，返回当前菜单项列表（每次循环调用，反映最新状态） |
| `on_action` | Callable | `(key, selected_idx, items) → 'break' / 'continue' / None`，处理 LEFT/RIGHT/ENTER |
| `allow_episode_nav` | bool | 是否启用 LEFT/RIGHT 切换剧集 |
| `episode_nav_filter` | Callable | `(action_idx, items) → bool`，返回 True 时该按键用于导航而非传给 on_action。None 表示全部导航 |
| `return_label` | str | 返回按钮文本，menu_loop 自动在末尾添加 |
| `footer_hint` | Optional[str] | 底部提示文本 |

#### menu_loop 内部逻辑

```python
def menu_loop(...) -> None:
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
        # 检查是否选中了返回按钮（最后一个可选项）
        if action_idx == len(selectable) - 1:
            break

        result = on_action(key, action_idx, items)
        if result == 'break':
            break
```

#### 三个 handler 的迁移

**video handler** — `episode_nav_filter` 限制值调整项不触发导航：

```python
def handle_video_settings_menu(context_lines, allow_episode_nav=False, return_label='返回'):
    def build_items():
        crop_hint = f"-vf {build_crop_filter_text()}"
        return [
            with_ffmpeg_hint(menu_item('H.265 编码', format_on_off(settings.video.hevc)), ...),
            MENU_SEPARATOR,
            with_ffmpeg_hint(menu_item('开始时间', settings.video.ss or '未设置'), ...),
            with_ffmpeg_hint(menu_item('结束时间', settings.video.to or '未设置'), ...),
            MENU_SEPARATOR,
            with_ffmpeg_hint(menu_item('裁剪上下黑边', ...), ...),
            with_ffmpeg_hint(menu_item('裁剪左右黑边', ...), ...),
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

**audio handler** — 无 `episode_nav_filter`（全部项可导航），用 regex 匹配选中行：

```python
def handle_audio_settings_menu(context_lines, allow_episode_nav=False, return_label='返回'):
    def build_items():
        # ... 初始化 internal_streams ...
        items = [
            with_ffmpeg_hint(menu_item('重新编码', ...), ...),
            with_ffmpeg_hint(menu_item('音频编码格式', ...), ...),
            MENU_SEPARATOR,
        ]
        for i, s in enumerate(audio_streams):
            # ... 构建流列表项 ...
            items.append(...)
        return items

    def on_action(key, action_idx, items):
        selected_line = ANSI_ESCAPE.sub('', items[get_selectable_indices(items)[action_idx]]).strip()
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

**subtitle handler** — 最复杂，需支持 SHIFT_UP/DOWN 排序。方案：在 menu_loop 中增加 `on_shift` 回调参数：

```python
def menu_loop(..., on_shift: Optional[Callable[[str, int, list[str]], None]] = None):
    # ...
    if key in ('SHIFT_UP', 'SHIFT_DOWN'):
        if on_shift:
            selectable = get_selectable_indices(items)
            if idx in selectable:
                on_shift(key, selectable.index(idx), items)
        continue
```

subtitle handler 传入 `on_shift` 处理排序逻辑，video/audio 不传（默认 None，SHIFT 键被忽略）。

#### 迁移策略

1. 先实现 `menu_loop` 框架（含 on_shift 参数）
2. 迁移 `handle_video_settings_menu`（最简单，无排序，有 episode_nav_filter）
3. 迁移 `handle_audio_settings_menu`（中等，regex 匹配）
4. 迁移 `handle_subtitle_settings_menu`（最复杂，on_shift 排序）
5. 每步迁移后手动验证对应菜单功能正常

#### 收益

- 消除 ~60-80 行重复的 UP/DOWN/BACKSPACE/导航代码
- 新增菜单页面只需写 `build_items` + `on_action`
- 剧集导航逻辑集中维护，不再三处复制

---

## 二、外功 — 功能与性能改进

### 2.1 ffprobe 结果缓存

#### 现状

`update_current_episode()` (L1114-1122) 每次调用执行 4 次 ffprobe 子进程：

```python
def update_current_episode(idx):
    current_file_idx = idx % len(input_paths)
    first_file = input_paths[current_file_idx]
    first_width, first_height = get_video_resolution(first_file)   # ffprobe #1
    audio_streams = get_audio_streams(first_file)                  # ffprobe #2
    subtitle_streams = get_subtitle_streams(first_file)            # ffprobe #3-4 (内部可能两次)
```

切换剧集时（逐集模式 LEFT/RIGHT），每次触发 3-4 次 ffprobe，耗时约 0.8-1.5s。

批量处理阶段 (L1731-1743) 的循环中，`build_ffmpeg_command` 内部不直接调用 ffprobe，但 `calculate_effective_duration` 调用 `get_video_duration`（ffprobe），每个文件额外 1 次。

#### 目标

在 `process_files()` 内定义缓存字典和访问函数：

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

`update_current_episode()` 改为：

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

`calculate_effective_duration()` 改为从缓存读取 duration：

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

#### 缓存生命周期

- 缓存定义在 `process_files()` 内部，随函数返回自动释放
- 同一文件只探测一次，无论切换多少次
- 无需缓存失效机制：单次运行中视频文件不会变化

#### 收益

- 逐集模式切换剧集：从 ~1s 降至 <50ms（缓存命中）
- 批量处理：N 个文件从 4N 次 ffprobe 降至 4N 次（首次），但 `calculate_effective_duration` 不再额外调用

---

### 2.2 设置持久化

#### 配置文件

- 路径：`%APPDATA%\movie_editor\config.json`
- 获取方式：`os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'movie_editor', 'config.json')`
- 目录不存在时自动创建：`os.makedirs(os.path.dirname(config_path), exist_ok=True)`

#### JSON schema

```json
{
  "version": 1,
  "video": {
    "hevc": true,
    "resolution": null
  },
  "audio": {
    "reencode": true,
    "codec": "copy"
  },
  "subtitle": {
    "mode": "internal",
    "burn_in": false,
    "disable": false,
    "codec": "copy"
  }
}
```

**不持久化的字段**（及其原因）：

| 字段 | 原因 |
|------|------|
| `video.ss` / `video.to` | 逐集模式下每集不同，不应跨会话保留 |
| `video.crop_top` / `video.crop_left` | 逐集模式下每集不同 |
| `video.resolution` | 依赖源视频分辨率，应自动计算 |
| `audio.internal_streams` | 依赖具体文件的流索引 |
| `subtitle.files` | 文件路径跨会话可能失效 |
| `subtitle.internal_streams` | 依赖具体文件的流索引 |
| `subtitle.external_streams` | 依赖导入的字幕文件 |

#### 保存函数

```python
def save_settings(settings: AppSettings, config_path: str) -> None:
    data = asdict(settings)
    data['version'] = 1
    # 移除不持久化的字段
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
```

#### 加载函数

```python
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

#### 集成位置

- **加载**：`process_files()` 开头，`settings = AppSettings()` 之后：
  ```python
  config_path = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'movie_editor', 'config.json')
  settings = load_settings(config_path)
  ```
- **保存**：主循环正常退出时（用户在主菜单按 BACKSPACE 或选择退出），在 `show_cursor()` 之前调用 `save_settings(settings, config_path)`
- **不保存的场景**：Ctrl+C 中断、RuntimeError 异常退出

---

### 2.3 自动黑边检测

#### 实现函数

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
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        crops = []
        for line in result.stderr.splitlines():
            match = re.search(r'crop=(\d+):(\d+):(\d+):(\d+)', line)
            if match:
                crops.append(tuple(map(int, match.groups())))
        if not crops:
            return 0, 0
        # 取最后一次 cropdetect 输出（最稳定）
        w, h, x, y = crops[-1]
        src_w, src_h = get_video_resolution(file_path)
        if src_w == 0 or src_h == 0:
            return 0, 0
        crop_top = y
        crop_left = x
        # 验证：裁剪值不应超过源尺寸的 1/4
        if crop_top > src_h // 4 or crop_left > src_w // 4:
            return 0, 0
        return crop_top, crop_left
    except (subprocess.SubprocessError, ValueError):
        return 0, 0
```

#### 菜单集成

在 `handle_video_settings_menu` 的 `build_items` 中，在「裁剪左右黑边」后增加一项：

```python
menu_item('自动检测黑边'),
```

对应 `on_action` 中新增：

```python
elif action_idx == 5:  # 自动检测黑边
    if key in ('RIGHT', 'ENTER'):
        crop_top, crop_left = detect_crop(first_file)
        if crop_top > 0 or crop_left > 0:
            settings.video.crop_top = crop_top
            settings.video.crop_left = crop_left
```

注意：`action_idx == 5` 是「自动检测黑边」，原来的「返回」按钮由 `menu_loop` 自动添加，不再占 action_idx。

#### 边界情况

- **检测失败**（返回 0,0）：设置不变，用户可手动调整
- **检测值过大**（超过 1/4 源尺寸）：视为误检，返回 0,0
- **PGS/图形字幕视频**：cropdetect 可能受字幕影响，但用户仍可手动微调
- **逐集模式**：检测基于当前剧集文件，每集可独立检测

---

### 2.4 批量处理增强

#### 2.4.1 跳过已完成文件

在批量处理循环 (L1731-1743) 中，编码前检查输出文件：

```python
for i, path in enumerate(input_paths):
    # ... 构建 command ...
    out_path = command[-1]
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        # 跳过已有输出文件
        continue
    # ... 正常编码 ...
```

此为默认行为。如需强制覆盖，在主菜单增加「强制覆盖」开关：

```python
# settings 中新增
@dataclass
class VideoSettings:
    ...
    force_overwrite: bool = False
```

主菜单中增加对应项。当 `force_overwrite = True` 时跳过上述检查。

#### 2.4.2 总进度显示

当前 `run_ffmpeg_with_progress` 的 `title_prefix` 参数已支持自定义前缀。批量处理循环中已有：

```python
prefix = f"[{i+1}/{total_count}] {truncate_name(os.path.basename(path))}"
```

无需修改 `run_ffmpeg_with_progress`，只需确保逐集处理模式 (L1599-1666) 中也使用相同格式：

```python
prefix = f"[{current_file_idx+1}/{len(input_paths)}] {truncate_name(os.path.basename(first_file))}"
```

当前逐集模式的 prefix (L1650) 缺少总进度，需补上。

#### 2.4.3 错误重试

在批量处理循环中，`run_ffmpeg_with_progress` 失败时抛出 `RuntimeError`。当前行为是整个循环中止。

改进：捕获 RuntimeError，显示内联错误菜单：

```python
for i, path in enumerate(input_paths):
    # ... 跳过检查 ...
    while True:
        try:
            command = build_ffmpeg_command(...)
            prefix = f"[{i+1}/{total_count}] ..."
            run_ffmpeg_with_progress(command, calculate_effective_duration(path), title_prefix=prefix)
            break  # 成功，跳出重试循环
        except RuntimeError as e:
            error_msg = str(e)
            # 显示错误菜单
            retry_items = [
                menu_item('重试当前文件'),
                menu_item('跳过，继续下一个'),
                menu_item('中止全部'),
            ]
            # 用 menu_loop 或简单键盘循环让用户选择
            choice = show_error_menu(error_msg, retry_items)
            if choice == 0:
                continue  # 重试
            elif choice == 1:
                break  # 跳过
            else:
                return  # 中止
```

`show_error_menu` 实现为简单的 TUI 菜单，显示错误信息 + 三个选项，用 UP/DOWN/ENTER 选择。

---

## 三、实施优先级

| 阶段 | 内容 | 预计改动量 | 依赖 | 验证方法 |
|------|------|-----------|------|---------|
| P1-a | dataclass 替代 settings dict | 净减 ~20 行 | 无 | `python -c "import movie_editor"` 无报错 |
| P1-b | 代码分区标记 | 净增 ~30 行 | 无 | 视觉检查 |
| P2-a | ffprobe 缓存 | 净增 ~25 行 | P1-a | 逐集模式切换剧集无延迟 |
| P2-b | 统一菜单按键分发 menu_loop | 净减 ~60 行 | P1-a | 三个子菜单功能不变 |
| P3-a | 设置持久化 | 净增 ~60 行 | P1-a | 修改 hevc→False，重启后仍为 False |
| P3-b | 批量处理增强（跳过/总进度/重试） | 净增 ~80 行 | P2-a | 批量处理 3 个文件，中间一个故意失败 |
| P4 | 自动黑边检测 | 净增 ~40 行 | P2-b | 对有黑边的视频检测并填入值 |

总计：约净增 150 行，最终文件 ~1920 行。

## 四、风险控制

- **P1-a 纯重构**：dataclass 替换后功能行为零变化，115 处访问点机械替换，遗漏会触发 AttributeError
- **P2-b 渐进迁移**：menu_loop 先迁移 video handler 验证，再迁移 audio/subtitle
- **P3-a 容错加载**：JSON 缺字段或格式错误时静默回退默认值，不影响启动
- **P3-b 错误重试**：默认行为不变（失败中止），重试菜单是新增的 catch 分支
- **P4 检测结果不强制**：自动检测填入设置后用户可手动微调或清零
