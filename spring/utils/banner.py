from spring.utils.logger import SpringLogger


class BannerPrinter:
    SPRING_BANNER = """
                _             _                 _      _    ___ 
 ___ _ __  _ __(_)_ __   __ _| |__   ___   ___ | |_   / \\  |_ _|
/ __| '_ \\| '__| | '_ \\ / _` | '_ \\ / _ \\ / _ \\| __| / _ \\  | | 
\\__ \\ |_) | |  | | | | | (_| | |_) | (_) | (_) | |_ / ___ \\ | | 
|___/ .__/|_|  |_|_| |_|\\__, |_.__/ \\___/ \\___/ \\__/_/   \\_\\___|
    |_|                 |___/                                  
    """

    def __init__(self, version: str = "2.2.0"):  # v1.8.7 修复 import 时提前创建 logs/ 目录
        self.version = version
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
