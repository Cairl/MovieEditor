# MovieEditor 项目上下文

## 项目概述

MovieEditor 是一个基于 FFmpeg 的视频处理工具，提供交互式命令行界面 (TUI)。用户可以通过直观的菜单系统配置视频编码参数、处理音频流、管理字幕，并实时预览生成的 FFmpeg 命令。

## 技术栈

- **语言**: Python 3.12+
- **核心依赖**: FFmpeg (ffprobe/ffmpeg 命令行工具)
- **GUI 组件**: tkinter (用于文件选择对话框)
- **平台**: Windows (使用 msvcrt 进行键盘输入处理)

## 主要功能模块

### 1. 视频设置
- H.265/HEVC 或 H.264 编码切换
- 分辨率缩放 (原始、75%、50%、25%)
- 时间剪切 (开始/结束时间)
- 黑边裁剪 (上下/左右)

### 2. 音频设置
- 多音频流管理 (启用/禁用特定流)
- 音频编码格式: copy, aac, mp3, ac3, flac

### 3. 字幕设置
- 内置字幕流管理
- 外部字幕文件导入 (.srt, .ass, .ssa, .vtt, .sup)
- 字幕烧制 (硬字幕嵌入视频)

### 4. FFmpeg 命令预览
- 实时显示将执行的完整 FFmpeg 命令

## 运行方式

```bash
# 方式一：直接运行，通过 GUI 选择文件
python movie_editor.py

# 方式二：命令行传入文件路径
python movie_editor.py "路径/到/视频文件.mp4"
```

## 构建和运行

### 前置要求
1. Python 3.12 或更高版本
2. FFmpeg 已安装并添加到系统 PATH

### 运行命令
```bash
python movie_editor.py
```

### 支持的输入格式
- 视频: .mp4, .mkv, .mov, .avi, .flv, .wmv
- 字幕: .srt, .ass, .ssa, .vtt, .sup

### 输出格式
- 统一输出为 MP4 格式
- 输出文件命名规则: `[FF] 原文件名.mp4`
- 输出位置: 与源文件相同目录

## 用户界面

- **导航**: ↑↓ 选择菜单项，←→ 调整参数，Enter 确认/切换，Backspace 返回
- **进度显示**: 实时显示编码进度、速度、剩余时间
- **命令预览**: 以可视化方式展示 FFmpeg 命令参数

## 代码架构

```
movie_editor.py
├── UI 渲染层
│   ├── ANSI 颜色和样式定义
│   ├── 菜单渲染函数 (render_menu_box, render_screen_menu)
│   └── 进度条渲染 (run_ffmpeg_with_progress)
│
├── FFmpeg 交互层
│   ├── 媒体信息探测 (get_video_resolution, get_video_duration, get_audio_streams, get_subtitle_streams)
│   └── 命令构建 (build_ffmpeg_command)
│
├── 用户输入处理
│   └── 键盘导航 (read_navigation_key)
│
└── 主流程控制
    └── 状态机和菜单循环 (process_files)
```

## 开发约定

- 使用 UTF-8 编码处理标准输入输出
- 子进程管理: 使用 `ACTIVE_CHILD_PROCESSES` 集合跟踪所有子进程，确保退出时正确清理
- 错误处理: FFmpeg 执行失败时显示返回码和错误日志
- 进度追踪: 通过 FFmpeg `-progress pipe:1` 参数获取实时进度

## 关键参数说明

### 视频编码
- H.265: `-c:v hevc -crf 23`
- H.264: `-c:v libx264`

### 元数据
- 保留原始元数据和章节: `-map_metadata 0 -map_chapters 0`
- 添加 handler_name 标记: `-metadata handler_name=@Cairl`

## 文件结构

```
MovieEditor/
├── movie_editor.py    # 主程序文件
├── .gitignore         # Git 忽略规则
└── .git/              # Git 版本控制
```
