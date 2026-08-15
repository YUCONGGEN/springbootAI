"""Spring Batch 批处理框架测试"""
import csv
import os

import pytest

from spring.batch import (
    BatchStatus,
    CsvItemReader,
    CsvItemWriter,
    ExitStatus,
    FunctionItemProcessor,
    FunctionItemWriter,
    GeneratorItemReader,
    ItemProcessor,
    ItemReader,
    ItemWriter,
    Job,
    JobExecution,
    JobLauncher,
    ListItemReader,
    ListItemWriter,
    Step,
    StepExecution,
)


class TestReaders:
    """读取器测试"""

    def test_list_reader(self):
        reader = ListItemReader([1, 2, 3])
        assert list(reader.read()) == [1, 2, 3]

    def test_generator_reader(self):
        def gen():
            for i in range(5):
                yield i * 10

        reader = GeneratorItemReader(gen)
        assert list(reader.read()) == [0, 10, 20, 30, 40]

    def test_csv_reader(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")

        reader = CsvItemReader(str(csv_file), header=True)
        rows = list(reader.read())
        assert len(rows) == 2
        assert rows[0] == ['Alice', '30']
        assert rows[1] == ['Bob', '25']

    def test_csv_reader_no_header(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("Alice,30\nBob,25\n", encoding="utf-8")

        reader = CsvItemReader(str(csv_file), header=False)
        rows = list(reader.read())
        assert len(rows) == 2


class TestProcessors:
    """处理器测试"""

    def test_default_processor(self):
        p = ItemProcessor()
        assert p.process("test") == "test"

    def test_function_processor(self):
        p = FunctionItemProcessor(lambda x: x * 2)
        assert p.process(5) == 10

    def test_processor_filter(self):
        """返回 None 表示过滤"""
        p = FunctionItemProcessor(lambda x: x if x > 2 else None)
        assert p.process(1) is None
        assert p.process(3) == 3


class TestWriters:
    """写入器测试"""

    def test_list_writer(self):
        w = ListItemWriter()
        w.write([1, 2, 3])
        w.write([4, 5])
        assert w.items == [1, 2, 3, 4, 5]

    def test_function_writer(self):
        collected = []
        w = FunctionItemWriter(collected.extend)
        w.write([1, 2])
        assert collected == [1, 2]

    def test_csv_writer(self, tmp_path):
        csv_file = tmp_path / "out.csv"
        w = CsvItemWriter(str(csv_file), header=['name', 'age'])
        w.write([['Alice', '30'], ['Bob', '25']])

        with open(csv_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'name,age' in content
        assert 'Alice,30' in content
        assert 'Bob,25' in content


class TestStep:
    """步骤测试"""

    def test_step_basic(self):
        reader = ListItemReader([1, 2, 3, 4, 5])
        processor = FunctionItemProcessor(lambda x: x * 2)
        writer = ListItemWriter()
        step = Step('test_step', reader, processor, writer, chunk_size=2)

        execution = JobExecution('test_job', 1)
        step_execution = step.execute(execution)

        assert step_execution.status == BatchStatus.COMPLETED
        assert step_execution.read_count == 5
        assert step_execution.write_count == 5
        assert step_execution.commit_count == 3  # 2+2+1
        assert writer.items == [2, 4, 6, 8, 10]

    def test_step_with_filter(self):
        """Processor 返回 None 过滤记录"""
        reader = ListItemReader([1, 2, 3, 4, 5])
        processor = FunctionItemProcessor(lambda x: x if x % 2 == 0 else None)
        writer = ListItemWriter()
        step = Step('filter_step', reader, processor, writer, chunk_size=10)

        execution = JobExecution('test_job', 1)
        step.execute(execution)

        assert writer.items == [2, 4]
        assert step_execution_read_count(execution) == 5
        assert step_execution_write_count(execution) == 2

    def test_step_no_writer(self):
        """无 Writer 时仍正常执行"""
        reader = ListItemReader([1, 2, 3])
        processor = FunctionItemProcessor(lambda x: x * 2)
        step = Step('no_writer_step', reader, processor, None, chunk_size=2)

        execution = JobExecution('test_job', 1)
        step_execution = step.execute(execution)
        assert step_execution.status == BatchStatus.COMPLETED

    def test_step_chunk_boundary(self):
        """chunk_size 正好整除"""
        reader = ListItemReader([1, 2, 3, 4])
        writer = ListItemWriter()
        step = Step('chunk_step', reader, None, writer, chunk_size=2)

        execution = JobExecution('test_job', 1)
        step_execution = step.execute(execution)
        assert step_execution.commit_count == 2

    def test_step_failure(self):
        """步骤失败时抛异常"""
        class FailingProcessor(ItemProcessor):
            def process(self, item):
                if item == 3:
                    raise ValueError("intentional failure")
                return item

        reader = ListItemReader([1, 2, 3, 4])
        step = Step('fail_step', reader, FailingProcessor(), ListItemWriter(), chunk_size=2)

        execution = JobExecution('test_job', 1)
        with pytest.raises(ValueError):
            step.execute(execution)

    def test_step_retry(self):
        """重试策略"""
        attempts = []

        class RetryableProcessor(ItemProcessor):
            def process(self, item):
                attempts.append(item)
                if len(attempts) < 3:
                    raise ConnectionError("transient error")
                return item * 10

        reader = ListItemReader([1])
        step = Step(
            'retry_step', reader, RetryableProcessor(), ListItemWriter(),
            chunk_size=10,
            retry_limit=3,
            retryable_exceptions=[ConnectionError],
        )

        execution = JobExecution('test_job', 1)
        step_execution = step.execute(execution)
        assert step_execution.retry_count == 2
        assert step_execution.status == BatchStatus.COMPLETED

    def test_step_skip(self):
        """跳过策略"""
        class SkippableProcessor(ItemProcessor):
            def process(self, item):
                if item == 2:
                    raise ValueError("bad item")
                return item

        reader = ListItemReader([1, 2, 3])
        step = Step(
            'skip_step', reader, SkippableProcessor(), ListItemWriter(),
            chunk_size=10,
            skip_limit=1,
            skippable_exceptions=[ValueError],
        )

        execution = JobExecution('test_job', 1)
        step_execution = step.execute(execution)
        assert step_execution.skip_count == 1
        assert step_execution.status == BatchStatus.COMPLETED


def step_execution_read_count(execution):
    return execution.step_executions[-1].read_count


def step_execution_write_count(execution):
    return execution.step_executions[-1].write_count


class TestJob:
    """作业测试"""

    def test_job_single_step(self):
        reader = ListItemReader([1, 2, 3])
        writer = ListItemWriter()
        step = Step('s1', reader, None, writer, chunk_size=10)
        job = Job('test_job', [step])

        launcher = JobLauncher()
        execution = launcher.run(job)

        assert execution.status == BatchStatus.COMPLETED
        assert execution.exit_status == ExitStatus.COMPLETED
        assert len(execution.step_executions) == 1
        assert writer.items == [1, 2, 3]

    def test_job_multiple_steps(self):
        """多步骤顺序执行"""
        reader1 = ListItemReader([1, 2, 3])
        writer1 = ListItemWriter()
        step1 = Step('s1', reader1, None, writer1, chunk_size=10)

        reader2 = ListItemReader([10, 20, 30])
        writer2 = ListItemWriter()
        step2 = Step('s2', reader2, None, writer2, chunk_size=10)

        job = Job('multi_job', [step1, step2])
        launcher = JobLauncher()
        execution = launcher.run(job)

        assert execution.status == BatchStatus.COMPLETED
        assert len(execution.step_executions) == 2
        assert writer1.items == [1, 2, 3]
        assert writer2.items == [10, 20, 30]

    def test_job_stops_on_step_failure(self):
        """步骤失败时作业停止"""
        reader1 = ListItemReader([1, 2, 3])
        writer1 = ListItemWriter()
        step1 = Step('s1', reader1, None, writer1, chunk_size=10)

        class FailingProcessor(ItemProcessor):
            def process(self, item):
                raise RuntimeError("fail")

        reader2 = ListItemReader([4, 5])
        step2 = Step('s2', reader2, FailingProcessor(), ListItemWriter(), chunk_size=10)

        reader3 = ListItemReader([6, 7])
        writer3 = ListItemWriter()
        step3 = Step('s3', reader3, None, writer3, chunk_size=10)

        job = Job('fail_job', [step1, step2, step3])
        launcher = JobLauncher()
        execution = launcher.run(job)

        assert execution.status == BatchStatus.FAILED
        assert len(execution.step_executions) == 2  # step3 未执行
        assert writer1.items == [1, 2, 3]
        assert writer3.items == []  # step3 未执行

    def test_job_empty_steps_raises(self):
        with pytest.raises(ValueError):
            Job('empty', [])

    def test_step_invalid_chunk_size(self):
        with pytest.raises(ValueError):
            Step('bad', ListItemReader([]), chunk_size=0)


class TestJobLauncher:
    """启动器测试"""

    def test_launcher_increments_id(self):
        reader = ListItemReader([1])
        writer = ListItemWriter()
        job = Job('j', [Step('s', reader, None, writer, chunk_size=1)])

        launcher = JobLauncher()
        e1 = launcher.run(job)
        e2 = launcher.run(job)

        assert e2.job_id == e1.job_id + 1
