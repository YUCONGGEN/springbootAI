from spring.annotations.core import Component, Scheduled, Slf4j


@Slf4j
@Component
class ScheduledTasks:
    """定时任务类 - 测试 @Scheduled"""
    
    def __init__(self):
        self.fixed_rate_count = 0
        self.fixed_delay_count = 0
        self.cron_count = 0
    
    @Scheduled(fixed_rate=5000)
    def fixed_rate_task(self):
        """每5秒执行一次 - 测试 fixed_rate"""
        self.fixed_rate_count += 1
        self.logger.info(f"Fixed rate task executed {self.fixed_rate_count} times")
    
    @Scheduled(fixed_delay=3000, initial_delay=1000)
    def fixed_delay_task(self):
        """每3秒执行一次(上次完成后) - 测试 fixed_delay"""
        self.fixed_delay_count += 1
        self.logger.info(f"Fixed delay task executed {self.fixed_delay_count} times")
    
    @Scheduled(cron="0/10 * * * * *")
    def cron_task(self):
        """每10秒执行一次 - 测试 cron 表达式"""
        self.cron_count += 1
        self.logger.info(f"Cron task executed {self.cron_count} times")
    
    def get_stats(self):
        """获取任务执行统计"""
        return {
            "fixed_rate_count": self.fixed_rate_count,
            "fixed_delay_count": self.fixed_delay_count,
            "cron_count": self.cron_count
        }
