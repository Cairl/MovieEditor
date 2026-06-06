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
