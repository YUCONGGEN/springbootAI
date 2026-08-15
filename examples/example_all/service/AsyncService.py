"""
异步服务 — 测试 @Async 和 @AsyncResult
"""
import time
from spring.annotations.core import Service, Slf4j, Async, PostConstruct


@Slf4j
@Service
class AsyncService:
    """@Async 异步执行服务"""

    def __init__(self):
        self.completed_tasks = []

    @PostConstruct
    def init(self):
        self.logger.info("AsyncService 初始化完成")

    @Async
    def async_task(self, task_name: str):
        """@Async — 异步执行不阻塞"""
        time.sleep(0.3)
        self.completed_tasks.append(task_name)
        self.logger.info(f"Async task '{task_name}' completed")
        return f"Result of {task_name}"

    def batch_async_tasks(self, count: int) -> list:
        """批量提交异步任务"""
        results = []
        for i in range(count):
            task_name = f"task_{i+1}"
            result = self.async_task(task_name)
            results.append({"task": task_name, "submitted": True})
        return results

    def get_stats(self) -> dict:
        return {"completed": len(self.completed_tasks), "tasks": self.completed_tasks}
