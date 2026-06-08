# FFmpeg 运行日志：每次执行记录完整上下文，用于调试
import os
import json
import logging
from datetime import datetime
from typing import Optional


def _get_log_dir() -> str:
    """日志目录：程序所在目录下的 log/"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base, 'log')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _make_logger() -> logging.Logger:
    logger = logging.getLogger('ffmpeg_runner')
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    log_dir = _get_log_dir()
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(log_dir, f'ffmpeg_{today}.log')

    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def log_ffmpeg_start(
    command: list[str],
    input_file: Optional[str],
    output_file: Optional[str],
    total_duration: float,
    title_prefix: str,
    video_info: Optional[dict] = None,
) -> str:
    """记录 FFmpeg 启动信息，返回本次运行 ID。"""
    logger = _make_logger()
    run_id = datetime.now().strftime('%H%M%S_%f')[:12]

    logger.info(f'===== FFmpeg 开始 [{run_id}] =====')
    logger.info(f'任务: {title_prefix or "(无标题)"}')
    logger.info(f'输入: {input_file}')
    logger.info(f'输出: {output_file}')
    logger.info(f'预计时长: {total_duration:.2f}s')
    logger.info(f'命令: {" ".join(command)}')

    if video_info:
        logger.info(f'视频信息: {json.dumps(video_info, ensure_ascii=False)}')

    logger.debug(f'命令详情:')
    for i, token in enumerate(command):
        logger.debug(f'  [{i:3d}] {token}')

    return run_id


def log_ffmpeg_progress(
    run_id: str,
    current_ms: int,
    total_duration: float,
    speed: float,
    elapsed: float,
) -> None:
    """记录进度（定期调用，避免日志爆炸）。"""
    logger = _make_logger()
    curr_sec = current_ms / 1_000_000
    pct = (curr_sec / total_duration * 100) if total_duration > 0 else 0
    logger.debug(
        f'[{run_id}] 进度: {curr_sec:.1f}s/{total_duration:.1f}s '
        f'({pct:.1f}%) | 速度: {speed:.2f}x | 用时: {elapsed:.1f}s'
    )


def log_ffmpeg_end(
    run_id: str,
    returncode: int,
    elapsed: float,
    stderr_lines: list[str],
) -> None:
    """记录 FFmpeg 结束信息。"""
    logger = _make_logger()
    status = '成功' if returncode == 0 else '失败'
    logger.info(f'[{run_id}] 结束: {status} (返回码 {returncode}) | 用时: {elapsed:.1f}s')

    if stderr_lines:
        logger.warning(f'[{run_id}] stderr 输出 ({len(stderr_lines)} 行):')
        for line in stderr_lines[-20:]:  # 最多保留最后 20 行
            logger.warning(f'  {line}')

    logger.info(f'===== FFmpeg 结束 [{run_id}] =====\n')


def log_ffmpeg_error(run_id: str, error: Exception) -> None:
    """记录异常。"""
    logger = _make_logger()
    logger.error(f'[{run_id}] 异常: {type(error).__name__}: {error}')
