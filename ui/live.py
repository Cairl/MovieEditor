# 渲染层：rich.Live 全局生命周期封装
# 通过 screen=True 进入备用屏幕缓冲，退出时恢复原始终端，
# 彻底消除"每次交互重绘叠加污染控制台"的问题。
# 同一时刻全局只有一个 Live 实例，菜单/ffmpeg 进度串行复用，
# 内容切换由 update() 完成，rich 自动逐行 diff，无全屏清屏闪烁。
from typing import Optional

from rich.console import Console, Group
from rich.console import RenderableType
from rich.live import Live

# 与 core/ffmpeg.py 的 _PROGRESS_POLL_SEC (0.05s) 对齐
_REFRESH_PER_SECOND = 20

console = Console()
_live: Optional[Live] = None


def is_running() -> bool:
    """备用屏幕（Live）是否处于活跃状态。"""
    return _live is not None


def start_screen(initial_renderable: Optional[RenderableType] = None) -> None:
    """进入备用屏幕缓冲 + 隐藏光标 + 开启 Live。幂等。"""
    global _live
    if _live is None:
        _live = Live(
            initial_renderable if initial_renderable is not None else Group(),
            console=console,
            screen=True,
            refresh_per_second=_REFRESH_PER_SECOND,
            transient=False,
        )
        _live.__enter__()


def update(renderable: RenderableType) -> None:
    """差异化更新整屏内容。rich 自动逐行 diff，只重画变化行。"""
    if _live is not None:
        _live.update(renderable)


def stop_screen() -> None:
    """退出备用屏幕 + 恢复光标。幂等。"""
    global _live
    if _live is not None:
        try:
            _live.__exit__(None, None, None)
        except Exception:
            pass
        _live = None
