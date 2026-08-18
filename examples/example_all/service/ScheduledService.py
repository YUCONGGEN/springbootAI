"""
定时任务服务 — 测试 @Scheduled (fixed_rate, fixed_delay, cron)
"""
from springbootai.annotations.core import Component, Scheduled, Slf4j


@Slf4j
@Component
class ScheduledService:
    """@Scheduled 定时任务服务"""

    def __init__(self):
        self.fixed_rate_count = 0
        self.fixed_delay_count = 0
        self.cron_count = 0

    @Scheduled(fixed_rate=10000)
    def fixed_rate_task(self):
        """每10秒执行 — @Scheduled(fixed_rate=10000)"""
        self.fixed_rate_count += 1
        self.logger.info(f"[fixed_rate] 执行 #{self.fixed_rate_count} 次")

    @Scheduled(fixed_delay=8000, initial_delay=2000)
    def fixed_delay_task(self):
        """每8秒执行(等上一次完成) — @Scheduled(fixed_delay=8000)"""
        self.fixed_delay_count += 1
        self.logger.info(f"[fixed_delay] 执行 #{self.fixed_delay_count} 次")

    @Scheduled(cron="0/15 * * * * *")
    def cron_task(self):
        """每15秒执行 — @Scheduled(cron='0/15 * * * * *')"""
        self.cron_count += 1
        self.logger.info(f"[cron] 执行 #{self.cron_count} 次")

    def get_stats(self) -> dict:
        return {
            "fixed_rate": self.fixed_rate_count,
            "fixed_delay": self.fixed_delay_count,
            "cron": self.cron_count,
        }
