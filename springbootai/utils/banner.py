from springbootai.utils.logger import SpringLogger


def _default_version() -> str:
    # 读取 springbootai 包的 __version__，避免每次发版都要修改本文件
    try:
        import springbootai  # noqa: WPS433 (局部导入避免循环依赖)
        return getattr(springbootai, "__version__", "2.3.11")
    except Exception:  # pragma: no cover - 极端情况下兜底
        return "2.3.11"


class BannerPrinter:
    SPRING_BANNER = """
                _             _                 _      _    ___ 
 ___ _ __  _ __(_)_ __   __ _| |__   ___   ___ | |_   / \\  |_ _|
/ __| '_ \\| '__| | '_ \\ / _` | '_ \\ / _ \\ / _ \\| __| / _ \\  | | 
\\__ \\ |_) | |  | | | | | (_| | |_) | (_) | (_) | |_ / ___ \\ | | 
|___/ .__/|_|  |_|_| |_|\\__, |_.__/ \\___/ \\___/ \\__/_/   \\_\\___|
    |_|                 |___|                                  
    """

    def __init__(self, version: str = None):  # v1.8.7 修复 import 时提前创建 logs/ 目录；v2.2.6 改为动态读取 __version__
        self.version = version or _default_version()
        self.logger = SpringLogger()

    def print_banner(self) -> None:
        print(self.SPRING_BANNER)
        print(f" Spring Framework {self.version} ".center(60, "="))
        print()

    def print_startup_info(self, port: int, context_path: str = "") -> None:
        self.logger.info("Starting Spring application...")
        self.logger.info(f"Server port: {port}")
        self.logger.info(f"Context path: {context_path or '/'}")
        self.logger.info("Application started successfully!")
        print()

    def print_shutdown_info(self) -> None:
        self.logger.info("Shutting down Spring application...")
        self.logger.info("Application stopped successfully!")
