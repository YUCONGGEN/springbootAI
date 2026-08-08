from spring.utils.logger import SpringLogger


class BannerPrinter:
    SPRING_BANNER = """
  ____             _       _          ____  _   _   ____    _    ____  
 / ___|  ___   ___| |_ ___| |__      / ___|| | | | / ___|  / \\  |  _ \\ 
 \\___ \\ / _ \\ / __| __/ __| '_ \\     \\___ \\| |_| | \\___ \\ / _ \\ | |_) |
  ___) | (_) | (__| || (__| | | |     ___) |  _  |  ___) / ___ \\|  __/ 
 |____/ \\___/ \\___|\\__\\___|_| |_|    |____/|_| |_| |____/_/   \\_\\_|    
                                                                        
    """

    def __init__(self, version: str = "0.1.0"):
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
