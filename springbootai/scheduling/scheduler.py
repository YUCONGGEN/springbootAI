from typing import Dict, Callable
import asyncio
import time
import logging
import threading


class Scheduler:
    def __init__(self):
        # 存储任务信息: {task_id: {'task': asyncio.Task, 'loop': asyncio.AbstractEventLoop}}
        self._tasks: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._logger = logging.getLogger("Spring.Scheduler")

    def schedule(self, task_id: str, func: Callable, **kwargs) -> None:
        fixed_rate = kwargs.get('fixed_rate')
        fixed_delay = kwargs.get('fixed_delay')
        cron = kwargs.get('cron')
        initial_delay = kwargs.get('initial_delay', 0)

        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                # 如果有事件循环但未运行，创建新线程运行
                def run_loop():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    task = None
                    if fixed_rate:
                        task = loop.create_task(self._schedule_fixed_rate(task_id, func, fixed_rate, initial_delay))
                    elif fixed_delay:
                        task = loop.create_task(self._schedule_fixed_delay(task_id, func, fixed_delay, initial_delay))
                    elif cron:
                        task = loop.create_task(self._schedule_cron(task_id, func, cron, initial_delay))
                    
                    if task:
                        with self._lock:
                            self._tasks[task_id] = {'task': task, 'loop': loop}
                    
                    loop.run_forever()
                
                thread = threading.Thread(target=run_loop, daemon=True)
                thread.start()
                return
        except RuntimeError:
            # 没有事件循环，创建新线程运行
            def run_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                task = None
                if fixed_rate:
                    task = loop.create_task(self._schedule_fixed_rate(task_id, func, fixed_rate, initial_delay))
                elif fixed_delay:
                    task = loop.create_task(self._schedule_fixed_delay(task_id, func, fixed_delay, initial_delay))
                elif cron:
                    task = loop.create_task(self._schedule_cron(task_id, func, cron, initial_delay))
                
                if task:
                    with self._lock:
                        self._tasks[task_id] = {'task': task, 'loop': loop}
                
                loop.run_forever()
            
            thread = threading.Thread(target=run_loop, daemon=True)
            thread.start()
            return

        # 有运行中的事件循环
        loop = asyncio.get_event_loop()
        task = None
        if fixed_rate:
            task = asyncio.create_task(self._schedule_fixed_rate(task_id, func, fixed_rate, initial_delay))
        elif fixed_delay:
            task = asyncio.create_task(self._schedule_fixed_delay(task_id, func, fixed_delay, initial_delay))
        elif cron:
            task = asyncio.create_task(self._schedule_cron(task_id, func, cron, initial_delay))
        else:
            self._logger.warning(f"No scheduling type specified for task: {task_id}")
        
        if task:
            with self._lock:
                self._tasks[task_id] = {'task': task, 'loop': loop}

    async def _schedule_fixed_rate(self, task_id: str, func: Callable, rate_ms: int, initial_delay: int) -> None:
        await asyncio.sleep(initial_delay / 1000)
        
        while True:
            # 检查任务是否已被取消
            with self._lock:
                task_info = self._tasks.get(task_id)
                if task_info is None or task_info['task'].done():
                    break
            
            start_time = time.time()
            try:
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    func()
            except Exception as e:
                self._logger.error(f"Scheduled task {task_id} failed: {str(e)}")
            
            elapsed_ms = (time.time() - start_time) * 1000
            sleep_time = max(0, rate_ms - elapsed_ms) / 1000
            await asyncio.sleep(sleep_time)

    async def _schedule_fixed_delay(self, task_id: str, func: Callable, delay_ms: int, initial_delay: int) -> None:
        await asyncio.sleep(initial_delay / 1000)
        
        while True:
            # 检查任务是否已被取消
            with self._lock:
                task_info = self._tasks.get(task_id)
                if task_info is None or task_info['task'].done():
                    break
            
            try:
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    func()
            except Exception as e:
                self._logger.error(f"Scheduled task {task_id} failed: {str(e)}")
            
            await asyncio.sleep(delay_ms / 1000)

    async def _schedule_cron(self, task_id: str, func: Callable, cron_expr: str, initial_delay: int) -> None:
        await asyncio.sleep(initial_delay / 1000)
        
        while True:
            # 检查任务是否已被取消
            with self._lock:
                task_info = self._tasks.get(task_id)
                if task_info is None or task_info['task'].done():
                    break
            
            try:
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    func()
            except Exception as e:
                self._logger.error(f"Scheduled task {task_id} failed: {str(e)}")
            
            await asyncio.sleep(self._parse_cron(cron_expr))

    def _parse_cron(self, cron_expr: str) -> float:
        import datetime
        
        parts = cron_expr.split()
        
        if len(parts) == 5:
            second = '*'
            minute, hour, day, month, weekday = parts
        elif len(parts) == 6:
            second, minute, hour, day, month, weekday = parts
        else:
            self._logger.warning(f"Invalid cron expression: {cron_expr}")
            return 60.0
        
        try:
            now = datetime.datetime.now()
            next_run = now + datetime.timedelta(seconds=1)
            
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
        
        except Exception as e:
            self._logger.error(f"Failed to parse cron expression '{cron_expr}': {str(e)}")
            return 60.0
    
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
            return value == day
        
        return False

    def stop(self, task_id: str) -> None:
        with self._lock:
            if task_id not in self._tasks:
                return
            
            task_info = self._tasks[task_id]
            task = task_info['task']
            loop = task_info['loop']
            
            if not task.done():
                try:
                    # 使用 call_soon_threadsafe 安全地跨线程取消任务
                    if loop.is_running():
                        loop.call_soon_threadsafe(task.cancel)
                    else:
                        task.cancel()
                except Exception as e:
                    self._logger.error(f"Failed to cancel task {task_id}: {str(e)}")
            
            del self._tasks[task_id]
            self._logger.info(f"Scheduled task {task_id} stopped")

    def stop_all(self) -> None:
        with self._lock:
            task_ids = list(self._tasks.keys())
        
        for task_id in task_ids:
            self.stop(task_id)
        
        self._logger.info(f"All {len(task_ids)} scheduled tasks stopped")
