"""
日志和进度显示工具
"""
import sys

# 强制 UTF-8 编码，防止 Windows GBK 崩溃
try:
    if hasattr(sys.stdout, 'buffer') and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
try:
    if hasattr(sys.stderr, 'buffer') and hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


class Logger:
    """简单的带颜色日志输出"""

    # ANSI 颜色码
    COLORS = {
        "reset": "\033[0m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "cyan": "\033[96m",
        "red": "\033[91m",
        "bold": "\033[1m",
    }

    @staticmethod
    def _color(text: str, color: str) -> str:
        return f"{Logger.COLORS.get(color, '')}{text}{Logger.COLORS['reset']}"

    @classmethod
    def info(cls, msg: str):
        print(f"  {cls._color('[i]', 'blue')} {msg}")

    @classmethod
    def success(cls, msg: str):
        print(f"  {cls._color('[OK]', 'green')} {msg}")

    @classmethod
    def warn(cls, msg: str):
        print(f"  {cls._color('[!]', 'yellow')} {msg}")

    @classmethod
    def error(cls, msg: str):
        print(f"  {cls._color('[X]', 'red')} {msg}")

    @classmethod
    def debug(cls, msg: str):
        """调试日志（默认不显示，保留供兼容调用）"""
        pass

    @classmethod
    def step(cls, step_num: int, total: int, msg: str):
        """显示步骤进度"""
        print(f"\n{cls._color(f'[{step_num}/{total}]', 'bold')} {msg}")

    @classmethod
    def title(cls, msg: str):
        """显示标题"""
        print(f"\n{cls._color('=' * 50, 'cyan')}")
        print(f"{cls._color(msg, 'bold')}")
        print(f"{cls._color('=' * 50, 'cyan')}")


# 全局实例
log = Logger()
