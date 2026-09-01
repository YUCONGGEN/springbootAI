from typing import Dict, Callable
import asyncio
import time
import logging
import threading
import inspect

from springbootai.logging.context import safe_log_field


class Scheduler:
    def __init__(self):
        # 存储任务信息: {task_id: {'task': asyncio.Task, 'loop': asyncio.AbstractEventLoop}}
        self._tasks: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._logger = logging.getLogger("Spring.Scheduler")
        self._worker_loop = None
        self._worker_thread = None
        self._worker_ready = threading.Event()

    def _worker_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._worker_loop = loop
            self._worker_thread = threading.current_thread()
            self._worker_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(
                    *pending, return_exceptions=True))
            loop.close()
            with self._lock:
                if self._worker_loop is loop:
                    self._worker_loop = None
                    self._worker_thread = None
                self._worker_ready.clear()

    def _ensure_worker_loop(self):
        with self._lock:
            if (self._worker_loop is not None
                    and self._worker_loop.is_running()
                    and self._worker_thread is not None
                    and self._worker_thread.is_alive()):
                return self._worker_loop
            self._worker_ready.clear()
            thread = threading.Thread(
                target=self._worker_main,
                name="SpringScheduler",
                daemon=True,
            )
            self._worker_thread = thread
            thread.start()
        if not self._worker_ready.wait(timeout=5):
            raise RuntimeError("Scheduler event loop failed to start")
        with self._lock:
            if self._worker_loop is None:
                raise RuntimeError("Scheduler event loop failed to initialize")
            return self._worker_loop

    async def _invoke(self, func: Callable) -> None:
        if inspect.iscoroutinefunction(func):
            await func()
            return
        result = await asyncio.to_thread(func)
        if inspect.isawaitable(result):
            await result

    def schedule(self, task_id: str, func: Callable, **kwargs) -> None:
        fixed_rate = kwargs.get('fixed_rate')
        fixed_delay = kwargs.get('fixed_delay')
        cron = kwargs.get('cron')
        initial_delay = kwargs.get('initial_delay', 0)
        if not task_id or not str(task_id).strip():
            raise ValueError("Scheduler task_id must not be empty")
        if not callable(func):
            raise TypeError("Scheduler func must be callable")
        kinds = sum(value is not None for value in (
            fixed_rate, fixed_delay, cron))
        if kinds == 0:
            self._logger.warning(
                "No scheduling type specified task=%s",
                safe_log_field(task_id),
            )
            return
        if kinds != 1:
            raise ValueError(
                "Specify exactly one of fixed_rate, fixed_delay or cron")
        try:
            initial_delay = float(initial_delay)
        except (TypeError, ValueError) as exc:
            raise ValueError("Scheduler initial_delay must be numeric") from exc
        if initial_delay < 0:
            raise ValueError("Scheduler initial_delay must not be negative")
        if fixed_rate is not None:
            fixed_rate = float(fixed_rate)
            if fixed_rate <= 0:
                raise ValueError("Scheduler fixed_rate must be greater than zero")
            coroutine = self._schedule_fixed_rate(
                task_id, func, fixed_rate, initial_delay)
        elif fixed_delay is not None:
            fixed_delay = float(fixed_delay)
            if fixed_delay <= 0:
                raise ValueError("Scheduler fixed_delay must be greater than zero")
            coroutine = self._schedule_fixed_delay(
                task_id, func, fixed_delay, initial_delay)
        else:
            if len(str(cron).split()) not in {5, 6}:
                raise ValueError("Scheduler cron expression must have 5 or 6 fields")
            self._validate_cron_expression(str(cron))
            coroutine = self._schedule_cron(
                task_id, func, str(cron), initial_delay)

        # Replacing an ID is explicit and never leaves an orphan task behind.
        self.stop(task_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._ensure_worker_loop()
            task = asyncio.run_coroutine_threadsafe(coroutine, loop)
            owned = True
        else:
            task = loop.create_task(coroutine, name=f"scheduler:{task_id}")
            owned = False
        with self._lock:
            self._tasks[task_id] = {
                'task': task, 'loop': loop, 'owned_loop': owned,
            }

    async def _schedule_fixed_rate(self, task_id: str, func: Callable, rate_ms: int, initial_delay: int) -> None:
        await asyncio.sleep(initial_delay / 1000)
        
        while True:
            start_time = time.monotonic()
            try:
                await self._invoke(func)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.error(
                    "Scheduled task %s failed error_type=%s",
                    task_id, type(exc).__name__,
                )
            
            elapsed_ms = (time.monotonic() - start_time) * 1000
            sleep_time = max(0, rate_ms - elapsed_ms) / 1000
            await asyncio.sleep(sleep_time)

    async def _schedule_fixed_delay(self, task_id: str, func: Callable, delay_ms: int, initial_delay: int) -> None:
        await asyncio.sleep(initial_delay / 1000)
        
        while True:
            try:
                await self._invoke(func)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.error(
                    "Scheduled task %s failed error_type=%s",
                    task_id, type(exc).__name__,
                )
            
            await asyncio.sleep(delay_ms / 1000)

    async def _schedule_cron(self, task_id: str, func: Callable, cron_expr: str, initial_delay: int) -> None:
        await asyncio.sleep(initial_delay / 1000)
        
        while True:
            # Cron schedules wait for their first matching instant; registering
            # a future schedule must never execute the task immediately.
            await asyncio.sleep(self._parse_cron(cron_expr))
            try:
                await self._invoke(func)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.error(
                    "Scheduled task %s failed error_type=%s",
                    task_id, type(exc).__name__,
                )
            
    def _parse_cron(self, cron_expr: str) -> float:
        import datetime
        
        parts = cron_expr.split()
        
        if len(parts) == 5:
            # Traditional five-field cron fires at second zero.
            second = '0'
            minute, hour, day, month, weekday = parts
        elif len(parts) == 6:
            second, minute, hour, day, month, weekday = parts
        else:
            self._logger.warning(
                "Invalid cron expression=%s", safe_log_field(cron_expr))
            return 60.0
        
        try:
            now = datetime.datetime.now()
            next_run = (now + datetime.timedelta(seconds=1)).replace(
                microsecond=0)
            
            # 解析所有字段的可能值
            seconds = self._parse_field(second, 0, 59)
            minutes = self._parse_field(minute, 0, 59)
            hours = self._parse_field(hour, 0, 23)
            days = self._parse_field(day, 1, 31)
            months = self._parse_field(month, 1, 12)
            
            # 获取当前月份的最大天数
            def get_max_day(year, m):
                if m == 2:
                    if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
                        return 29
                    return 28
                if m in [4, 6, 9, 11]:
                    return 30
                return 31
            
            # 从当前时间开始查找下一个匹配时间
            while True:
                # 检查月份
                if next_run.month not in months:
                    # 跳转到下一个匹配月份的第一天
                    next_month_found = False
                    for m in months:
                        if m > next_run.month:
                            next_run = next_run.replace(month=m, day=1, hour=0, minute=0, second=0)
                            next_month_found = True
                            break
                    if not next_month_found:
                        # 下一年的第一个匹配月份
                        if months:
                            next_run = next_run.replace(year=next_run.year + 1, month=months[0], day=1, hour=0, minute=0, second=0)
                        else:
                            return 60.0
                    continue
                
                # 检查日期
                max_day = get_max_day(next_run.year, next_run.month)
                valid_days = [d for d in days if d <= max_day]
                
                if next_run.day not in valid_days:
                    # 跳转到下一个匹配日期
                    next_day_found = False
                    for d in valid_days:
                        if d > next_run.day:
                            next_run = next_run.replace(day=d, hour=0, minute=0, second=0)
                            next_day_found = True
                            break
                    if not next_day_found:
                        # 跳转到下一个月
                        next_month_found = False
                        for m in months:
                            if m > next_run.month:
                                next_run = next_run.replace(month=m, day=1, hour=0, minute=0, second=0)
                                next_month_found = True
                                break
                        if not next_month_found:
                            if months:
                                next_run = next_run.replace(year=next_run.year + 1, month=months[0], day=1, hour=0, minute=0, second=0)
                            else:
                                return 60.0
                    continue
                
                # 检查星期
                if weekday != '*' and weekday != '?':
                    if not self._matches_weekday(next_run.weekday(), weekday):
                        # 跳到下一天
                        next_run = next_run + datetime.timedelta(days=1)
                        next_run = next_run.replace(hour=0, minute=0, second=0)
                        continue
                
                # 检查小时
                if next_run.hour not in hours:
                    # 跳转到下一个匹配小时
                    next_hour_found = False
                    for h in hours:
                        if h > next_run.hour:
                            next_run = next_run.replace(hour=h, minute=0, second=0)
                            next_hour_found = True
                            break
                    if not next_hour_found:
                        # 跳转到下一天
                        next_run = next_run + datetime.timedelta(days=1)
                        next_run = next_run.replace(hour=0, minute=0, second=0)
                    continue
                
                # 检查分钟
                if next_run.minute not in minutes:
                    # 跳转到下一个匹配分钟
                    next_minute_found = False
                    for m in minutes:
                        if m > next_run.minute:
                            next_run = next_run.replace(minute=m, second=0)
                            next_minute_found = True
                            break
                    if not next_minute_found:
                        # 跳转到下一小时
                        next_run = next_run + datetime.timedelta(hours=1)
                        next_run = next_run.replace(minute=0, second=0)
                    continue
                
                # 检查秒
                if next_run.second in seconds:
                    # 找到匹配时间
                    delta = (next_run - now).total_seconds()
                    return max(0, delta)
                
                # 跳转到下一个匹配秒
                next_second_found = False
                for s in seconds:
                    if s > next_run.second:
                        next_run = next_run.replace(second=s)
                        next_second_found = True
                        break
                if not next_second_found:
                    # 跳转到下一分钟
                    next_run = next_run + datetime.timedelta(minutes=1)
                    next_run = next_run.replace(second=0)
                
                # 防止无限循环
                if (next_run - now).total_seconds() > 365 * 24 * 3600:
                    return 60.0
        
        except Exception as exc:
            self._logger.error(
                "Failed to parse cron expression=%s error_type=%s",
                safe_log_field(cron_expr), type(exc).__name__,
            )
            return 60.0

    def _validate_cron_expression(self, cron_expr: str) -> None:
        parts = cron_expr.split()
        if len(parts) == 5:
            fields = ((parts[0], 0, 59), (parts[1], 0, 23),
                      (parts[2], 1, 31), (parts[3], 1, 12))
            weekday = parts[4]
        else:
            fields = ((parts[0], 0, 59), (parts[1], 0, 59),
                      (parts[2], 0, 23), (parts[3], 1, 31),
                      (parts[4], 1, 12))
            weekday = parts[5]
        try:
            if any(not self._parse_field(expr, low, high)
                   for expr, low, high in fields):
                raise ValueError
            if weekday not in {"*", "?"}:
                day = int(weekday)
                if day < 0 or day > 7:
                    raise ValueError
        except (TypeError, ValueError, ZeroDivisionError):
            raise ValueError("Scheduler cron expression is invalid") from None
    
    def _parse_field(self, expr: str, min_val: int, max_val: int) -> list:
        """解析 cron 字段表达式，返回所有可能的取值"""
        if expr == '*' or expr == '?':
            return list(range(min_val, max_val + 1))
        
        result = []
        for part in expr.split(','):
            if '/' in part:
                # 处理 step 表达式，如 */5 或 0/5
                step_parts = part.split('/')
                if len(step_parts) == 2:
                    start_str, step_str = step_parts
                    start = int(start_str) if start_str != '*' else min_val
                    step = int(step_str)
                    for val in range(start, max_val + 1, step):
                        if val >= min_val:
                            result.append(val)
            elif '-' in part:
                # 处理范围表达式，如 1-5
                range_parts = part.split('-')
                if len(range_parts) == 2:
                    start = int(range_parts[0])
                    end = int(range_parts[1])
                    for val in range(start, end + 1):
                        if min_val <= val <= max_val:
                            result.append(val)
            elif part.isdigit():
                # 处理单个值
                val = int(part)
                if min_val <= val <= max_val:
                    result.append(val)
        
        return sorted(set(result))
    
    def _matches_field(self, value: int, expr: str, min_val: int, max_val: int) -> bool:
        if expr == '*' or expr == '?':
            return True
        
        # 处理 */5 或 0/5 格式（从起始值开始每隔step执行）
        if '/' in expr:
            parts = expr.split('/')
            if len(parts) == 2:
                start = int(parts[0]) if parts[0] != '*' else min_val
                step = int(parts[1])
                return (value - start) % step == 0 and value >= start
        
        if expr.isdigit():
            return value == int(expr)
        
        if '-' in expr:
            parts = expr.split('-')
            if len(parts) == 2:
                return min_val <= int(parts[0]) <= value <= int(parts[1]) <= max_val
        
        return False

    def _matches_weekday(self, value: int, expr: str) -> bool:
        if expr == '*' or expr == '?':
            return True
        
        if expr.isdigit():
            day = int(expr)
            if day == 7:
                day = 0
            # datetime.weekday(): Monday=0; cron: Sunday=0/7, Monday=1.
            cron_value = (value + 1) % 7
            return cron_value == day
        
        return False

    def stop(self, task_id: str) -> None:
        with self._lock:
            task_info = self._tasks.pop(task_id, None)
            if task_info is None:
                return
            task = task_info['task']
            loop = task_info['loop']
            should_stop_worker = (
                task_info.get('owned_loop', False)
                and not any(info.get('owned_loop', False)
                            for info in self._tasks.values())
            )

        if not task.done():
            try:
                if task_info.get('owned_loop', False):
                    task.cancel()
                elif loop.is_running():
                    loop.call_soon_threadsafe(task.cancel)
                else:
                    task.cancel()
            except Exception as exc:
                self._logger.error(
                    "Failed to cancel task %s error_type=%s",
                    task_id, type(exc).__name__,
                )
        if should_stop_worker:
            self._shutdown_worker()
        self._logger.info("Scheduled task %s stopped", task_id)

    def _shutdown_worker(self) -> None:
        with self._lock:
            loop = self._worker_loop
            thread = self._worker_thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if (thread is not None and thread.is_alive()
                and threading.current_thread() is not thread):
            thread.join(timeout=5)
            if thread.is_alive():
                self._logger.error("Scheduler worker did not stop within timeout")

    def stop_all(self) -> None:
        with self._lock:
            task_items = list(self._tasks.items())
            self._tasks.clear()

        for task_id, task_info in task_items:
            task = task_info['task']
            loop = task_info['loop']
            if not task.done():
                try:
                    if task_info.get('owned_loop', False):
                        task.cancel()
                    elif loop.is_running():
                        loop.call_soon_threadsafe(task.cancel)
                    else:
                        task.cancel()
                except Exception as exc:
                    self._logger.error(
                        "Failed to cancel task %s error_type=%s",
                        task_id, type(exc).__name__,
                    )
        self._shutdown_worker()
        self._logger.info("All %s scheduled tasks stopped", len(task_items))
