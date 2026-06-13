# MovieEditor — AGENTS.md

## 项目定位

单文件 Python TUI 应用，通过 FFmpeg CLI 实现视频/音频/字幕编辑。支持**电影模式**（单文件）和**剧集模式**（批量目录），提供 ANSI 终端 UI 进行参数配置、FFmpeg 命令预览和实时进度展示。

**入口**: `main.py` (1770 行)
**运行**: `python main.py <file_or_dir> [<file_or_dir>...]`

---

## 核心架构

```
┌──────────────────────────────────────────────────────┐
│  main.py (单文件)                                      │
│                                                        │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │
│  │ 键盘输入层  │  │ TUI 渲染层  │  │  FFmpeg 探针   │  │
│  │ msvcrt     │  │ ANSI box   │  │  ffprobe CLI   │  │
│  │ ctypes     │  │ diff render│  │  subprocess    │  │
│  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘  │
│        │               │                  │           │
│        └───────┬───────┘                  │           │
│                ▼                          │           │
│  ┌──────────────────────┐                 │           │
│  │   菜单系统 (嵌套)     │◄──────────────┘           │
│  │  主菜单 → 设置子菜单  │                              │
│  │  → FFmpeg 命令预览    │                              │
│  └──────────┬───────────┘                              │
│             ▼                                          │
│  ┌──────────────────────┐  ┌────────────────┐         │
│  │  build_ffmpeg_command │  │ run_ffmpeg_    │         │
│  │  (参数组装)           │──│ with_progress  │         │
│  └──────────────────────┘  │ (进度条+shimmer)│         │
│                            └────────────────┘         │
└──────────────────────────────────────────────────────┘
```

## 代码分区

| 分区 | 行号范围 | 职责 |
|------|---------|------|
| Windows VT 处理 | L1-25 | import、SetConsoleMode、stdout/stderr 重定向 |
| 全局常量/UI 定义 | L27-100 | ANSI 颜色、图标、菜单宽度常量 |
| 进程管理 | L115-148 | 子进程注册/注销/终止 |
| 显示工具函数 | L103-226 | truncate_name、get_display_width、trim_to_display_width、pad_display |
| 菜单组件 | L171-199 | menu_section、menu_item、with_ffmpeg_hint |
| TUI 渲染层 | L228-498 | build_top_border、render_menu_box、render_preview_box、render_screen_menu |
| 键盘输入层 | L39-628 | _console_has_input、read_navigation_key、clear_keyboard_buffer |
| 文件选择 | L631-660 | choose_files、choose_file、choose_directory、get_video_files_in_dir |
| FFmpeg 探针 | L663-758 | get_video_resolution/duration、get_audio/subtitle_streams |
| FFmpeg 执行 | L761-1047 | format_preview_lines、run_ffmpeg_with_progress |
| 语言/格式映射 | L1049-1078 | get_full_language_name、get_subtitle_format_name |
| 主流程 | L1081-1770 | process_files 及其所有内部函数 |

## 关键技术细节

### TUI 渲染
- **增量渲染**: `render_menu_box` 使用 `LAST_MENU_LINES` 全局变量做行级 diff，仅更新变化行
- **Shimmer 进度条**: `run_ffmpeg_with_progress` 使用正弦波式颜色渐变动画
- **ANSI 定位**: `\033[H` 光标归位 + `\033[{row};1H` 行定位
- **首次清屏问题**: 首次 `render_menu_box` 清屏后 `LAST_MENU_LINES` 未重置，后续菜单切换可能出现残留行

### 键盘处理
- 使用 `msvcrt.kbhit()` + `msvcrt.getch()` 实现非阻塞键盘读取
- 扩展键 (`\xe0`/`\x00`) 需要连续读取两个字节
- Ctrl+C 通过 `PeekConsoleInputW` + `ReadConsoleInputW` 在内核层捕获，不触发 Python 的 KeyboardInterrupt
- Shift 状态通过 `GetKeyState(0x10)` 检测

### Settings 数据结构
- **当前**: 三层嵌套 dict (`settings['video']['hevc']`)，全文件 115 处访问
- **已有优化计划**: docs/ 中有详细 dataclass 迁移方案（VideoSettings/AudioSettings/SubtitleSettings/AppSettings）

### FFmpeg 命令组装
- `-ignore_unknown` 跳过 data/attachment 流
- 字幕烧录使用 `subtitles=` filter，路径中的 `\` 和 `:` 需转义
- 音频流使用相对索引 `0:a:{rel_index}` 映射
- MP4 输出默认使用 `mov_text` 字幕编码
- `-ss`/`-to` 放在输出文件前作为输出选项

## 依赖

| 依赖 | 说明 |
|------|------|
| Python 3.10+ | 使用 `tuple[...]` 类型注解 |
| ffmpeg/ffprobe | 必须在 PATH 中 |
| msvcrt | Windows only |
| ctypes | Windows API (SetConsoleMode, GetKeyState) |
| tkinter | 文件选择对话框 (仅 `filedialog`) |

## 运行方式

```bash
# 电影模式（单文件）
python main.py "C:\path\to\movie.mp4"

# 剧集模式（目录）
python main.py "D:\TV\Season1"

# 多目录混合
python main.py "D:\TV\S01" "D:\TV\S02"
```

## 已知问题与注意事项

1. **单文件架构**: 1770 行全部在 `main.py`，`process_files()` 内部嵌套定义了 20+ 个闭包函数
2. **settings 用嵌套 dict**: 类型无检查，key 拼写错误运行时才暴露
3. **菜单循环重复**: 三个 settings 子菜单 (video/audio/subtitle) 有 60-80 行重复的按键分发骨架
4. **ffprobe 重复调用**: `update_current_episode()` 每次调用 3-4 次 ffprobe，逐集切换约 0.8-1.5s
5. **无设置持久化**: 每次启动重置所有配置
6. **tkinter 主线程限制**: 文件选择对话框创建 `tk.Tk()` 实例后立即销毁，多显示器环境下可能闪烁
7. **Windows only**: `msvcrt`、`ctypes.windll`、`SetConsoleMode` 无法跨平台

## 代码审查要点

### 优点
- ANSI 终端 UI 实现精致，支持增量渲染和 shimmer 动画
- 进程管理完善：`ACTIVE_CHILD_PROCESSES` + `atexit` + `terminate_active_children()`
- Ctrl+C 处理优雅，在内核输入缓冲区层面拦截
- 字幕支持全面：内部/外部、烧录/内封、排序
- 批量处理支持逐集模式与统筹模式
- 自然排序 (`re.split(r'(\d+)', x)`) 保证 S01E01 排在 S01E10 前

### 可改进项
| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | dataclass 替代嵌套 dict | 115 处 `settings[...]` 访问 → 属性访问，已有详细迁移方案 |
| P1 | 提取 menu_loop 框架 | 消除三个子菜单 60-80 行重复代码 |
| P2 | ffprobe 结果缓存 | `_probe_cache` 字典，逐集切换从 ~1s 降至 <50ms |
| P2 | 设置持久化 | `%APPDATA%\movie_editor\config.json`，不持久化 per-file 字段 |
| P3 | 代码分区标记 | 在单文件内添加 `═══ 分区名 ═══` 注释提升可读性 |
| P3 | `get_subtitle_streams` 两次 ffprobe | 先 JSON 探针，再 `-hide_banner -i` 捕获 stderr 中的别名，可合并 |
| P3 | `_probe_streams_json` 内部 try-except 有 fallback 重复逻辑 | 失败时重试去掉 `-probesize`/`-analyzeduration`，逻辑完全复制 |

---

## 代码审查详细报告（两轮 Claude Code Review）

### 审查概览

| 类别 | CRITICAL | HIGH | MEDIUM | LOW | 总计 |
|------|----------|------|--------|-----|------|
| 安全 | 0 | 1 | 1 | 1 | 3 |
| Bug & 逻辑错误 | 0 | 5 | 6 | 4 | 15 |
| 代码质量 | 0 | 2 | 5 | 3 | 10 |
| 性能 | 0 | 1 | 3 | 1 | 5 |
| 可维护性 | 0 | 0 | 4 | 2 | 6 |
| Simplifier 回归 | 2 | 1 | 2 | 2 | 7 |
| **合计** | **2** | **10** | **21** | **13** | **46** |

### CRITICAL — Simplifier 引入的回归

#### N-1: `video.py` 从错误模块导入 `format_on_off`（ImportError 崩溃）
- **文件**: `ui/video.py:2`
- **描述**: `from ui.display import ..., format_on_off, ...` 但 `format_on_off` 定义在 `core/helpers.py`，不在 `ui/display.py`
- **后果**: 用户打开视频设置时直接 `ImportError` 崩溃
- **修复**: 改为 `from core.helpers import format_on_off, adjust_time_setting`

#### N-2: `run_menu_loop` 无条件拦截 LEFT/RIGHT（视频/音频设置键盘失灵）
- **文件**: `ui/display.py:396-399`
- **描述**: `run_menu_loop` 在 `allow_episode_nav=True` 时无条件 intercept LEFT/RIGHT 用于集数导航
- **后果**: 视频设置中的时间调节（±5s）、裁切调节（±2px）和音频编码格式切换全部失效
- **原因**: `video.py` 定义了 `guarded_update` 函数但从未传入 `run_menu_loop`，且 `guarded_update` 本身引用了未导入的 `get_selectable_indices`
- **修复**: `run_menu_loop` 需增加回调判断当前菜单项是否消费 LEFT/RIGHT；或在视频/音频菜单中传入 `guarded_update` 替代 `update_current_episode`

### HIGH — 功能性 Bug

#### B-3: 批量模式使用过时的流信息
- **文件**: `ui/app.py:379-391`
- **描述**: 批量处理循环中 `audio_streams` 和 `subtitle_streams` 是闭包变量，来自最后一次 `update_current_episode()` 的结果，而非每个文件自己的流信息
- **后果**: 若剧集间流布局不同（数量/索引不同），FFmpeg 会映射错误的流或报错
- **修复**: 在 `for i, path in enumerate(input_paths):` 循环内调用 `get_audio_streams(path)` 和 `get_subtitle_streams(path)`

#### B-6: 外挂字幕烧录只用 basename，不含完整路径
- **文件**: `ui/app.py:123`
- **描述**: `subtitles={os.path.basename(settings['subtitle']['files'][0])}` — FFmpeg 的 `subtitles=` filter 按工作目录解析路径，只用文件名几乎必然找不到文件
- **附加问题**: 路径中的 `\`、`:`、`'`、`[`、`]` 未做 FFmpeg 转义
- **修复**: 使用完整绝对路径并转义: `escaped = full_path.replace('\\', '\\\\').replace(':', '\\\\:').replace("'", "\\\\'")`

#### B-1+B-2: 导航函数重复定义（✅ 已修复）
- **文件**: `ui/display.py` vs `ui/navigation.py`
- **描述**: `get_selectable_indices`、`get_next_selectable`、`normalize_selected_index` 在两个模块中重复定义，且行为不一致（`display.py` 版本过滤 `CONTEXT_MARKER`，`navigation.py` 版本不过滤）
- **状态**: Simplifier 第一轮已修复 — `display.py` 删除重复定义，改为从 `navigation.py` 导入；`navigation.py` 已加入 `CONTEXT_MARKER` 过滤

#### R-1: 音频设置 LEFT/RIGHT 在 per-episode 模式下无条件导航集数
- **文件**: `ui/audio.py:48-50`
- **描述**: `if allow_episode_nav and key in ('LEFT', 'RIGHT'): ... continue` 无条件拦截，导致音频编码格式的 LEFT/RIGHT 切换不可达
- **修复**: 与 N-2 同源，需统一菜单框架的 LEFT/RIGHT 分发逻辑

### MEDIUM — 需关注

| ID | 文件 | 类别 | 描述 |
|---|---|---|---|
| R-2 | `ui/app.py` | Bug | `settings` dict 会累积所有已探测文件的流条目，不清理 |
| R-3 | `core/ffmpeg.py` | 可靠性 | ffprobe 子进程无 `timeout` 参数，损坏文件/网络路径会导致永久挂起 |
| R-4 | `core/ffmpeg.py` | 日志 | `log_ffmpeg_end`/`log_ffmpeg_error` 已导入但从未调用，日志无完成记录 |
| R-6 | `ui/app.py:121-123` | Bug | 字幕 filter 路径未做 FFmpeg 转义（`\` → `\\\\`，`:` → `\\:`） |
| R-8 | `core/ffmpeg.py:44-58` | 错误处理 | ffprobe 错误被静默吞掉（含 `FileNotFoundError`），用户无反馈 |
| Q-1 | `ui/app.py:33-405` | 结构 | `process_files()` 370+ 行，含 8+ 嵌套闭包、4 层嵌套循环 |
| Q-2 | `ui/display.py:136-319` | 结构 | `render_menu_box()` 183 行，应拆分 |
| Q-3 | `core/ffmpeg.py:152-413` | 结构 | `run_ffmpeg_with_progress()` 261 行含 6 嵌套函数 |
| Q-4 | `ui/app.py:78-82` | 类型安全 | settings 用嵌套 dict，key 拼写错误无检查 |
| Q-8 | `ui/app.py:180-191` | 抽象 | `ctx` dict 是 ad-hoc "上帝对象"，混合数据、函数、计算状态 |
| N-3 | `ui/video.py:46` | 死代码 | `guarded_update` 引用未导入的 `get_selectable_indices`，调用会 NameError |
| N-4 | `ui/display.py:338-418` | 死代码 | `run_menu_loop` + `Action` 仅被有 bug 的 video.py 使用 |
| P-1 | `ui/app.py:64-71` | 性能 | 无 ffprobe 缓存，每集切换 3-5 次子进程（~0.8-1.5s） |
| P-2 | `core/ffmpeg.py:81-117` | 性能 | `get_subtitle_streams` 两次 ffprobe 调用可合并 |

### LOW — 可酌情处理

| ID | 文件 | 描述 |
|---|---|---|
| S-1 | `debug_main.py:3` | 硬编码个人路径和站点名（`www.BTHDTV.com`），不应入库 |
| R-5 | `ui/app.py:377-401` | 批量完成后光标未 `show_cursor()` |
| R-7 | `ui/app.py:113-116` | 所有音频流取消时缺少 `-an` 标志 |
| R-9 | `core/ffmpeg.py:100` | 字幕别名正则不匹配含连字符的语言码（如 `pt-BR`） |
| R-10 | `ui/console.py:22-23` | `LAST_MENU_LINES`/`LAST_PREVIEW_LINES` 在 console.py 中是死代码 |
| R-11 | `ui/app.py:152` | 硬编码 `handler_name=@Cairl` 元数据 |
| R-12 | `core/helpers.py:23-38` | `parse_time_to_seconds(None)` 返回 0 但 `parse_time_to_seconds("invalid")` 返回 None，API 不一致 |
| R-13 | `ui/console.py:1` | 中文注释乱码（UTF-8 被当作 GBK 解码后再编码） |
| R-14 | `core/ffmpeg.py:236` | shimmer 波浪用 `len()` 而非显示宽度，CJK 字符位置偏移 |
| R-15 | `ui/console.py:112` | `Popen.terminate` 作为 unbound method 调用，可用但非常规 |
| N-5 | `ui/display.py:5-7` | `import time` 和 `from enum import Enum` 未使用 |
| N-6 | `ui/console.py:80-84` | UI 常量（`_is_separator` 等）不应放在 I/O 模块中 |
| Q-5 | `ui/display.py:218` | `headers_before` 原为 O(n²) 计算（✅ 已修复为 O(n)） |
| Q-6 | `ui/console.py:51-64` | ctypes 结构体在每次 `_check_console_ctrl()` 调用时重建 |
| Q-7 | 多处 | 魔法数字（`step * 5`、`alpha = 0.1`、`deque(maxlen=10)` 等） |

### Top 5 修复优先级（影响 × 修复难度）

1. **N-1** — `video.py` 导入错误 → 1 行改动，修复崩溃
2. **N-2 + R-1** — LEFT/RIGHT 键分发逻辑 → 统一菜单框架，修复设置菜单失灵
3. **B-3** — 批量流信息过时 → 循环内加探测调用，修复批量输出错误
4. **B-6** — 外挂字幕路径 → 用完整路径 + 转义，修复字幕烧录失败
5. **P-1** — ffprobe 缓存 → 加 `_probe_cache` dict，每集切换 ~1s → <50ms

---

## Simplifier 改动记录（两轮 Claude Code）

### 第一轮（9 文件，净减 83 行）

| 文件 | 改动 |
|------|------|
| `ui/display.py` (-125/+36) | 提取 `_render_title_segment()` 消除左右标题重复渲染；删除重复导航函数改为从 `navigation.py` 导入；`_is_separator()` 提取为共享函数；`headers_before` O(n²) → O(n) |
| `ui/subtitle.py` (-56/+28) | internal/external 字幕流选择合并为 `streams_dict + stream_key` 逻辑；`burn_in` 切换用 `next()` 替代标志变量 |
| `ui/console.py` (-37/+26) | `terminate_active_children()` 用循环消除重复代码；提取 `TITLE_MARKER`/`CONTEXT_MARKER`/`_is_separator()` |
| `ui/dialogs.py` (-26/+11) | 提取 `_tk_dialog()` 通用函数，三个对话框各缩减为 1 行 |
| `core/ffmpeg.py` (-23/+14) | `_probe_streams_json` 重试逻辑用 `for extra_args in [...]` 循环替代嵌套 try-except |
| `ui/app.py` (-23/+19) | 提取 `reset_video_trim()`；`elif not burn_in` → `else`；字幕 codec 简化为三元表达式 |
| `ui/navigation.py` (-8/+6) | 导入 `CONTEXT_MARKER`/`_is_separator`，`get_selectable_indices` 加入 context line 过滤 |
| `ui/audio.py` | 合并重复 import |
| `core/helpers.py` (-4) | 删除未使用的 `get_display_name()` |

### 第二轮（10 文件，累计净减 98 行）

| 文件 | 第二轮新增改动 |
|------|---------------|
| `core/ffmpeg.py` (+116/-47) | 提取 `_get_shimmer_text()` 和 `_build_progress_line()` 为模块级函数（从闭包中提取） |
| `ui/app.py` (+72/-23) | 提取 `build_preview_context()`；FFmpeg 预览循环改用 `run_menu_loop` |
| `ui/display.py` (+201) | 新增 `run_menu_loop()` 通用菜单框架 + `Action` 枚举（⚠️ 存在 N-2 回归） |
| `ui/video.py` (+61) | 改用 `run_menu_loop` 框架（⚠️ 存在 N-1/N-2 回归） |
| `ui/audio.py` (+70) | 简化字幕流选择逻辑 |
| `ui/subtitle.py` (+157) | 大幅简化字幕流选择和 burn_in 切换逻辑 |

### Simplifier 净效果

- **消除 8 处代码重复**（导航函数、tkinter 对话框、进程终止、标题渲染等）
- **O(n²) → O(n)** 性能优化（`headers_before` 计算）
- **修复 B-1 bug**（导航函数不一致）
- **引入 2 个 CRITICAL 回归**（N-1 ImportError、N-2 LEFT/RIGHT 键失灵）
- **所有修改保持功能等价**（除回归外），ANSI TUI 行为不变

---

## 第三轮审查（Round 3）

### 新发现

#### NEW-1: CRITICAL — `current_file_idx_ref` 陈旧引用导致子菜单集数导航失效
- **文件**: `ui/display.py:371`, `ui/video.py:48`, `ui/audio.py:59`, `ui/subtitle.py:154`
- **描述**: 每次调用 `run_menu_loop` 时传入 `current_file_idx_ref=[ctx.get('current_file_idx', 0)]`，创建的是一个**新列表**，捕获的是调用时刻的整数值。`run_menu_loop` 内部读取 `current_file_idx_ref[0]` 做导航，但 `update_current_episode` 通过 `nonlocal` 更新闭包变量 `current_file_idx`，**不会**更新 `current_file_idx_ref[0]`
- **后果**: 用户在子菜单中连续按 LEFT/RIGHT 时，每次导航都基于**原始**索引，而非当前索引。按两次 RIGHT 只会前进一集而非两集
- **修复**: `run_menu_loop` 中 `update_current_episode` 后同步引用：`current_file_idx_ref[0] = new_idx`

#### NEW-2: CRITICAL — N-1 扩展到 `audio.py` 和 `subtitle.py`
- **文件**: `ui/audio.py:3`, `ui/subtitle.py:5`
- **描述**: AGENTS.md N-1 只记录了 `video.py` 从错误模块导入 `format_on_off`，但 `audio.py` 和 `subtitle.py` 有**完全相同**的错误导入
- **后果**: 打开**任何**设置菜单（视频/音频/字幕）都会触发 `ImportError` 崩溃
- **修复**: 三个文件都改为 `from core.helpers import format_on_off`

#### NEW-3: HIGH — `build_preview_context` 中变量遮蔽外部 `ctx` dict
- **文件**: `ui/app.py:342`
- **描述**: 内部闭包 `ctx = [...]` 遮蔽了外部的 `ctx` settings dict。虽然 Python 作用域规则使其技术上安全，但易引起混淆
- **修复**: 重命名为 `preview_lines`

#### NEW-5: MEDIUM — `render_menu_box` 第一个菜单项永远不会高亮
- **文件**: `ui/display.py:191-193, 205`
- **描述**: `headers_before_selected` 计算包含 `selected_index` 位置的 header，导致 `0 + 1 == 0` 为 False，第一个菜单项无法高亮
- **修复**: 改为 `parsed_lines[:selected_index]`（去掉 +1）

#### NEW-6: MEDIUM — `no_nav_indices` 机制是死代码（同 N-2）
- **文件**: `ui/display.py:399-407`
- **描述**: 当 `skip_nav=True` 时，`continue` 仍然执行，LEFT/RIGHT 永远无法到达 `action_handler`

#### NEW-7: LOW — `LAST_MENU_LINES` 在不同渲染上下文间未重置
- **文件**: `ui/display.py:14, 287-302`
- **描述**: `render_preview_box` 做了全屏清除但未重置 `LAST_MENU_LINES`，返回菜单后首次增量渲染可能异常

#### NEW-8: LOW — 字幕重排后 `rel_index` 不变但依赖隐式不变量
- **文件**: `ui/subtitle.py:89-103`, `ui/app.py:119-126`
- **描述**: SHIFT_UP/DOWN 重排字幕后 `rel_index` 不变，`build_ffmpeg_command` 用 `rel_index` 做映射是正确的，但依赖隐式不变量未文档化

#### NEW-9: LOW — 逐集模式处理完所有集后无完成提示
- **文件**: `ui/app.py:253-317`
- **描述**: 处理完所有集后 `current_file_idx` 停在最后一集，再次点击"开始处理"会用最后一集的 settings 重新处理所有集

### 已修复确认
- **B-1+B-2** ✅ 导航函数重复定义已修复
- **Q-5** ✅ `headers_before` O(n²) 已优化为 O(n)
- **N-3** ✅ `guarded_update` 死代码已移除

### 纠正
- **N-4** ❌ 非死代码 — `run_menu_loop` 被 audio.py、subtitle.py、app.py 多处使用
- **S-1** ❌ `debug_main.py` 在当前代码库中不存在

### 第三轮总计

| 严重度 | 数量 | ID |
|--------|------|-----|
| CRITICAL | 6 | N-1(仍存在), N-2(仍存在), NEW-1, NEW-2, B-3(仍存在), B-6(仍存在) |
| HIGH | 4 | R-1(仍存在), NEW-3, R-6(=B-6), R-3(仍存在) |
| MEDIUM | 12 | NEW-5, NEW-6, R-2, R-4, R-8, Q-1, Q-2, Q-3, Q-4, Q-8, P-1, P-2 |
| LOW | 16 | NEW-4, NEW-7, NEW-8, NEW-9, R-7, R-9, R-10, R-11, R-12, R-13, R-14, R-15, N-5, N-6, Q-7 |
| **合计** | **38** | +3 已修复, +2 非适用 |

### 修复优先级（更新）

1. **N-1 + NEW-2** — 修复 video.py / audio.py / subtitle.py 的 `format_on_off` 导入 → 3 个单行改动，修复打开任何设置菜单的崩溃
2. **N-2 + NEW-6** — 修复 `run_menu_loop` LEFT/RIGHT 分发：`skip_nav=True` 时 fall through 到 `action_handler` → 2 行改动，恢复所有设置键盘控制
3. **NEW-1** — 同步 `current_file_idx_ref[0]` → 1 行添加，修复子菜单集数导航
4. **B-3** — 批量循环内重新探测流 → 每种流 2 行添加
5. **B-6** — 外挂字幕用完整路径 + FFmpeg 转义
