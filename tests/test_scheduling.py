"""Tests for springbootai.scheduling module (Scheduler, cron parsing)."""
import asyncio
import time
import threading
import pytest

from springbootai.scheduling.scheduler import Scheduler


class TestSchedulerCreation:
    """Tests for Scheduler initialization and basic properties."""

    def test_scheduler_creation(self):
        """Scheduler should be constructible with no arguments."""
        sched = Scheduler()
        assert sched is not None
        assert len(sched._tasks) == 0


class TestCronParsing:
    """Tests for the internal _parse_cron / _parse_field helpers."""

    def test_parse_field_wildcard(self):
        """'*' should return the full range."""
        sched = Scheduler()
        assert sched._parse_field("*", 0, 59) == list(range(0, 60))

    def test_parse_field_question_mark(self):
        """'?' should also return the full range."""
        sched = Scheduler()
        assert sched._parse_field("?", 0, 59) == list(range(0, 60))

    def test_parse_field_single_value(self):
        """Single numeric value should return list with one item."""
        sched = Scheduler()
        assert sched._parse_field("15", 0, 59) == [15]
        assert sched._parse_field("0", 0, 23) == [0]

    def test_parse_field_range(self):
        """Range 'a-b' should return values a through b inclusive."""
        sched = Scheduler()
        assert sched._parse_field("5-10", 0, 59) == [5, 6, 7, 8, 9, 10]

    def test_parse_field_step(self):
        """Step expression '*/n' or 'a/n' should return values at intervals."""
        sched = Scheduler()
        # */15 minutes -> 0, 15, 30, 45
        assert sched._parse_field("*/15", 0, 59) == [0, 15, 30, 45]
        # 5/10 starting at 5 -> 5, 15, 25, 35, 45, 55
        assert sched._parse_field("5/10", 0, 59) == [5, 15, 25, 35, 45, 55]

    def test_parse_field_comma_list(self):
        """Comma-separated values should be combined and sorted uniquely."""
        sched = Scheduler()
        assert sched._parse_field("1,3,5", 0, 59) == [1, 3, 5]
        # duplicates removed
        assert sched._parse_field("1,1,3,5", 0, 59) == [1, 3, 5]

    def test_parse_cron_invalid_length_returns_default(self):
        """Invalid cron expression length should return default 60s."""
        sched = Scheduler()
        assert sched._parse_cron("* * *") == 60.0  # only 3 fields

    def test_parse_cron_5_field(self):
        """5-field cron (without seconds) should parse without error."""
        sched = Scheduler()
        delay = sched._parse_cron("* * * * *")
        assert isinstance(delay, float)
        assert delay > 0

    def test_parse_cron_6_field(self):
        """6-field cron (with seconds) should parse without error."""
        sched = Scheduler()
        delay = sched._parse_cron("0 * * * * *")
        assert isinstance(delay, float)
        assert delay > 0

    def test_matches_weekday(self):
        """Cron Sunday=0/7 is converted from datetime Monday=0 semantics."""
        sched = Scheduler()
        assert sched._matches_weekday(0, "*") is True
        assert sched._matches_weekday(0, "?") is True
        assert sched._matches_weekday(0, "1") is True  # Monday
        assert sched._matches_weekday(0, "0") is False
        assert sched._matches_weekday(6, "7") is True  # Sunday
        assert sched._matches_weekday(6, "0") is True


class TestFixedRateScheduling:
    """Tests for fixed-rate task execution."""

    def test_fixed_rate_executes_multiple_times(self):
        """A fixed-rate task should execute multiple times within a short window."""
        sched = Scheduler()
        call_count = [0]
        lock = threading.Lock()

        def task():
            with lock:
                call_count[0] += 1

        # Schedule at 50ms interval
        sched.schedule("test-fixed-rate", task, fixed_rate=50, initial_delay=0)

        # Let it run for ~300ms -> should get at least 3-4 executions
        time.sleep(0.35)

        sched.stop("test-fixed-rate")

        # Small delay to let the cancel propagate
        time.sleep(0.1)

        assert call_count[0] >= 3, f"Expected at least 3 executions, got {call_count[0]}"

    def test_stop_prevents_further_execution(self):
        """After stopping a task, it should not execute again."""
        sched = Scheduler()
        call_count = [0]
        lock = threading.Lock()

        def task():
            with lock:
                call_count[0] += 1

        sched.schedule("stop-test", task, fixed_rate=80, initial_delay=0)
        time.sleep(0.2)
        count_at_stop = call_count[0]
        sched.stop("stop-test")
        time.sleep(0.3)

        # Should not have any (or at most 1 in-flight) executions after stop
        assert call_count[0] - count_at_stop <= 1

    def test_stop_nonexistent_task(self):
        """Stopping a non-existent task should not raise."""
        sched = Scheduler()
        sched.stop("does-not-exist")  # should not raise

    def test_stop_all_stops_everything(self):
        """stop_all should cancel all scheduled tasks."""
        sched = Scheduler()
        count1 = [0]
        count2 = [0]

        def task1():
            count1[0] += 1

        def task2():
            count2[0] += 1

        sched.schedule("t1", task1, fixed_rate=50, initial_delay=0)
        sched.schedule("t2", task2, fixed_rate=50, initial_delay=0)
        time.sleep(0.15)
        sched.stop_all()
        time.sleep(0.3)

        # Verify tasks stopped; count after stop should remain stable
        after_stop_1 = count1[0]
        after_stop_2 = count2[0]
        time.sleep(0.2)
        assert count1[0] - after_stop_1 <= 1
        assert count2[0] - after_stop_2 <= 1


class TestFixedDelayScheduling:
    """Tests for fixed-delay task execution."""

    def test_fixed_delay_executes(self):
        """A fixed-delay task should execute at least a few times."""
        sched = Scheduler()
        call_count = [0]

        def task():
            call_count[0] += 1

        sched.schedule("test-fixed-delay", task, fixed_delay=60, initial_delay=0)
        time.sleep(0.35)
        sched.stop("test-fixed-delay")
        time.sleep(0.1)

        assert call_count[0] >= 3


class TestSyncAndAsyncTasks:
    """Tests verifying that both sync and async callables are supported."""

    def test_sync_function_called(self):
        """Sync functions should be invoked."""
        sched = Scheduler()
        done = threading.Event()

        def sync_task():
            done.set()

        sched.schedule("sync", sync_task, fixed_rate=10000, initial_delay=0)
        # Should run very quickly after initial_delay=0
        finished = done.wait(timeout=2.0)
        sched.stop("sync")
        assert finished is True

    def test_async_function_called(self):
        """Async functions (coroutines) should be awaited."""
        sched = Scheduler()
        done = threading.Event()

        async def async_task():
            done.set()

        sched.schedule("async", async_task, fixed_rate=10000, initial_delay=0)
        finished = done.wait(timeout=2.0)
        sched.stop("async")
        assert finished is True

    def test_task_exception_does_not_kill_scheduler(self):
        """A task that raises should not stop subsequent executions."""
        sched = Scheduler()
        call_count = [0]
        failed = [False]

        def flaky_task():
            call_count[0] += 1
            if call_count[0] == 1:
                failed[0] = True
                raise RuntimeError("first call fails on purpose")

        sched.schedule("flaky", flaky_task, fixed_rate=80, initial_delay=0)
        time.sleep(0.35)
        sched.stop("flaky")
        time.sleep(0.1)

        assert failed[0] is True
        assert call_count[0] >= 2, f"Expected scheduler to keep running, got {call_count[0]} calls"


class TestNoScheduleType:
    """Tests for warning when no scheduling type is specified."""

    def test_no_schedule_type_logs_warning(self):
        """Calling schedule without fixed_rate/fixed_delay/cron should not crash."""
        sched = Scheduler()
        # Should not raise, just log a warning internally
        sched.schedule("no-type", lambda: None)
        time.sleep(0.1)
        assert "no-type" not in sched._tasks


def test_scheduler_rejects_invalid_cron_before_starting_worker():
    sched = Scheduler()
    with pytest.raises(ValueError, match="cron expression is invalid"):
        sched.schedule("invalid", lambda: None, cron="*/0 * * * * *")
    assert sched._worker_thread is None
    assert sched._tasks == {}


def test_scheduler_owned_worker_stops_after_last_task():
    sched = Scheduler()
    ran = threading.Event()
    sched.schedule("once", ran.set, fixed_delay=10000)
    assert ran.wait(timeout=2)
    worker = sched._worker_thread
    assert worker is not None and worker.is_alive()
    sched.stop("once")
    assert not worker.is_alive()
    assert sched._worker_thread is None
