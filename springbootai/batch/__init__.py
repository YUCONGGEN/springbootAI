"""
Spring Batch 批处理框架（对齐 Spring Batch）

提供大数据量批处理能力，支持分块处理、重试、跳过等企业级特性。

功能：
- Job/Step 模型：作业由多个步骤组成
- ItemReader/ItemProcessor/ItemWriter：读-处理-写三段式架构
- 分块处理（Chunk）：按 chunk_size 批量提交，避免内存溢出
- 重试策略：可配置最大重试次数和可重试异常
- 跳过策略：可配置最大跳过次数和可跳过异常
- 作业执行上下文：JobExecution/StepExecution 记录执行状态
- 内存安全的流式读取：Reader 返回生成器，支持大数据集

与 Java Spring Batch 的差异：
- Java 使用 ItemStreamReader 支持流式读取，Python 直接使用生成器
- Java 有完整的 JobRepository 持久化，Python 版本提供内存级执行记录
- Java 支持远程分块和分区，Python 版本仅支持单机分块

Usage::

    from springbootai.batch import (
        Job, Step, JobLauncher,
        ListItemReader, CsvItemReader,
        ItemProcessor, ItemWriter,
        JobExecution,
    )

    # 1. 定义 Reader
    reader = ListItemReader([1, 2, 3, 4, 5])

    # 2. 定义 Processor
    class DoubleProcessor(ItemProcessor):
        def process(self, item):
            return item * 2

    # 3. 定义 Writer
    class PrintWriter(ItemWriter):
        def write(self, items):
            for item in items:
                print(item)

    # 4. 定义 Step（chunk_size=2）
    step = Step('double_step', reader, DoubleProcessor(), PrintWriter(), chunk_size=2)

    # 5. 定义 Job
    job = Job('double_job', [step])

    # 6. 执行
    launcher = JobLauncher()
    execution = launcher.run(job)
    print(execution.status)  # COMPLETED
"""
import csv
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generator, List, Optional, Type

logger = logging.getLogger("Spring.Batch")


class BatchStatus(Enum):
    """批处理状态"""
    STARTING = 'STARTING'
    STARTED = 'STARTED'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    STOPPED = 'STOPPED'
    ABANDONED = 'ABANDONED'
    UNKNOWN = 'UNKNOWN'


class ExitStatus(Enum):
    """退出状态"""
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    STOPPED = 'STOPPED'
    CONTINUABLE = 'CONTINUABLE'


@dataclass
class StepExecution:
    """步骤执行上下文"""
    step_name: str
    status: BatchStatus = BatchStatus.STARTING
    exit_status: Optional[ExitStatus] = None
    read_count: int = 0
    write_count: int = 0
    commit_count: int = 0
    skip_count: int = 0
    retry_count: int = 0
    error_message: str = ''
    start_time: float = 0.0
    end_time: float = 0.0

    def start(self) -> None:
        self.status = BatchStatus.STARTED
        self.start_time = time.time()

    def finish(self, status: BatchStatus, exit_status: ExitStatus) -> None:
        self.status = status
        self.exit_status = exit_status
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


@dataclass
class JobExecution:
    """作业执行上下文"""
    job_name: str
    job_id: int
    status: BatchStatus = BatchStatus.STARTING
    exit_status: Optional[ExitStatus] = None
    step_executions: List[StepExecution] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    error_message: str = ''

    def start(self) -> None:
        self.status = BatchStatus.STARTED
        self.start_time = time.time()

    def finish(self, status: BatchStatus, exit_status: ExitStatus) -> None:
        self.status = status
        self.exit_status = exit_status
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


# ==================== Reader ====================

class ItemReader:
    """数据读取器基类

    子类需实现 ``read()`` 方法返回生成器或迭代器。
    """

    def read(self) -> Generator[Any, None, None]:
        """返回数据迭代器。

        Raises:
            NotImplementedError: 子类必须实现
        """
        raise NotImplementedError("ItemReader.read() must be implemented")


class ListItemReader(ItemReader):
    """列表读取器

    适用于数据量较小、已全部加载到内存的场景。
    """

    def __init__(self, items: List[Any]):
        self.items = list(items)

    def read(self) -> Generator[Any, None, None]:
        for item in self.items:
            yield item


class CsvItemReader(ItemReader):
    """CSV 文件读取器（流式读取，内存安全）

    使用 Python csv 模块逐行读取，支持大文件。

    Args:
        file_path: CSV 文件路径
        delimiter: 分隔符（默认逗号）
        header: 是否跳过首行表头
        encoding: 文件编码
    """

    def __init__(
        self,
        file_path: str,
        delimiter: str = ',',
        header: bool = True,
        encoding: str = 'utf-8',
    ):
        self.file_path = file_path
        self.delimiter = delimiter
        self.header = header
        self.encoding = encoding

    def read(self) -> Generator[Any, None, None]:
        with open(self.file_path, 'r', encoding=self.encoding, newline='') as f:
            reader = csv.reader(f, delimiter=self.delimiter)
            for i, row in enumerate(reader):
                if self.header and i == 0:
                    continue
                yield row


class GeneratorItemReader(ItemReader):
    """生成器读取器

    适用于自定义数据源（数据库查询、API调用等）。
    """

    def __init__(self, generator_factory: Callable[[], Generator[Any, None, None]]):
        self.generator_factory = generator_factory

    def read(self) -> Generator[Any, None, None]:
        yield from self.generator_factory()


# ==================== Processor ====================

class ItemProcessor:
    """数据处理器基类

    子类实现 ``process()`` 方法，对每条记录进行转换、过滤等操作。
    返回 None 表示过滤该记录。
    """

    def process(self, item: Any) -> Any:
        """处理单条记录。

        Args:
            item: 输入记录

        Returns:
            处理后的记录，或 None 表示过滤
        """
        return item


class FunctionItemProcessor(ItemProcessor):
    """函数式处理器

    将普通函数包装为 ItemProcessor。
    """

    def __init__(self, func: Callable[[Any], Any]):
        self.func = func

    def process(self, item: Any) -> Any:
        return self.func(item)


# ==================== Writer ====================

class ItemWriter:
    """数据写入器基类

    子类实现 ``write()`` 方法，接收一个 chunk 的记录列表。
    """

    def write(self, items: List[Any]) -> None:
        """写入一批记录。

        Args:
            items: 一个 chunk 的记录列表
        """
        raise NotImplementedError("ItemWriter.write() must be implemented")


class ListItemWriter(ItemWriter):
    """列表写入器

    将所有记录收集到内存列表，适用于测试。
    """

    def __init__(self):
        self.items: List[Any] = []

    def write(self, items: List[Any]) -> None:
        self.items.extend(items)


class FunctionItemWriter(ItemWriter):
    """函数式写入器"""

    def __init__(self, func: Callable[[List[Any]], None]):
        self.func = func

    def write(self, items: List[Any]) -> None:
        self.func(items)


class CsvItemWriter(ItemWriter):
    """CSV 文件写入器

    Args:
        file_path: 输出 CSV 文件路径
        delimiter: 分隔符
        header: 表头（None 表示不写表头）
        encoding: 文件编码
    """

    def __init__(
        self,
        file_path: str,
        delimiter: str = ',',
        header: Optional[List[str]] = None,
        encoding: str = 'utf-8',
    ):
        self.file_path = file_path
        self.delimiter = delimiter
        self.header = header
        self.encoding = encoding
        self._header_written = False

    def write(self, items: List[Any]) -> None:
        mode = 'a' if self._header_written else 'w'
        with open(self.file_path, mode, encoding=self.encoding, newline='') as f:
            writer = csv.writer(f, delimiter=self.delimiter)
            if self.header and not self._header_written:
                writer.writerow(self.header)
                self._header_written = True
            for item in items:
                if isinstance(item, (list, tuple)):
                    writer.writerow(item)
                else:
                    writer.writerow([item])


# ==================== Step ====================

class Step:
    """批处理步骤

    一个 Step 包含 Reader、Processor、Writer，按 chunk_size 分块处理。

    Args:
        name: 步骤名
        reader: 数据读取器
        processor: 数据处理器（可选，默认不处理）
        writer: 数据写入器
        chunk_size: 分块大小（每 chunk_size 条记录提交一次）
        retry_limit: 最大重试次数（0 表示不重试）
        retryable_exceptions: 可重试的异常类型列表
        skip_limit: 最大跳过次数（0 表示不跳过）
        skippable_exceptions: 可跳过的异常类型列表
    """

    def __init__(
        self,
        name: str,
        reader: ItemReader,
        processor: Optional[ItemProcessor] = None,
        writer: Optional[ItemWriter] = None,
        chunk_size: int = 10,
        retry_limit: int = 0,
        retryable_exceptions: Optional[List[Type[Exception]]] = None,
        skip_limit: int = 0,
        skippable_exceptions: Optional[List[Type[Exception]]] = None,
    ):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.name = name
        self.reader = reader
        self.processor = processor or ItemProcessor()
        self.writer = writer
        self.chunk_size = chunk_size
        self.retry_limit = retry_limit
        self.retryable_exceptions = tuple(retryable_exceptions or [])
        self.skip_limit = skip_limit
        self.skippable_exceptions = tuple(skippable_exceptions or [])

    def execute(self, job_execution: JobExecution) -> StepExecution:
        """执行步骤。

        Args:
            job_execution: 所属作业执行上下文

        Returns:
            步骤执行上下文
        """
        step_execution = StepExecution(step_name=self.name)
        step_execution.start()
        logger.info(f"Step '{self.name}' started (chunk_size={self.chunk_size})")

        chunk: List[Any] = []
        try:
            for item in self.reader.read():
                step_execution.read_count += 1

                # 处理单条记录（支持重试）
                processed = self._process_with_retry(item, step_execution)
                if processed is not None:
                    chunk.append(processed)

                # 达到 chunk_size 时提交
                if len(chunk) >= self.chunk_size:
                    self._write_chunk(chunk, step_execution)
                    step_execution.commit_count += 1
                    chunk = []

            # 提交剩余记录
            if chunk:
                self._write_chunk(chunk, step_execution)
                step_execution.commit_count += 1

            step_execution.finish(BatchStatus.COMPLETED, ExitStatus.COMPLETED)
            logger.info(
                f"Step '{self.name}' completed: "
                f"read={step_execution.read_count}, write={step_execution.write_count}, "
                f"commits={step_execution.commit_count}, skips={step_execution.skip_count}, "
                f"duration={step_execution.duration_ms:.0f}ms"
            )

        except Exception as e:
            step_execution.error_message = str(e)
            step_execution.finish(BatchStatus.FAILED, ExitStatus.FAILED)
            logger.error(f"Step '{self.name}' failed: {e}\n{traceback.format_exc()}")
            job_execution.step_executions.append(step_execution)
            raise

        job_execution.step_executions.append(step_execution)
        return step_execution

    def _process_with_retry(self, item: Any, step_execution: StepExecution) -> Any:
        """处理记录（支持重试）。"""
        last_error = None
        for attempt in range(self.retry_limit + 1):
            try:
                return self.processor.process(item)
            except self.retryable_exceptions as e:
                last_error = e
                step_execution.retry_count += 1
                if attempt < self.retry_limit:
                    logger.debug(
                        f"Step '{self.name}' retry {attempt + 1}/{self.retry_limit} "
                        f"for item: {e}"
                    )
                    continue
            except self.skippable_exceptions as e:
                if step_execution.skip_count < self.skip_limit:
                    step_execution.skip_count += 1
                    logger.debug(f"Step '{self.name}' skipped item: {e}")
                    return None
                raise

        # 重试耗尽
        if self.skippable_exceptions and last_error:
            if step_execution.skip_count < self.skip_limit:
                step_execution.skip_count += 1
                logger.debug(f"Step '{self.name}' skipped item after retries: {last_error}")
                return None
        raise last_error  # type: ignore[misc]

    def _write_chunk(self, chunk: List[Any], step_execution: StepExecution) -> None:
        """写入一个 chunk。"""
        if not self.writer:
            return
        self.writer.write(chunk)
        step_execution.write_count += len(chunk)


# ==================== Job ====================

class Job:
    """批处理作业

    一个 Job 包含多个顺序执行的 Step。

    Args:
        name: 作业名
        steps: 步骤列表
    """

    def __init__(self, name: str, steps: List[Step]):
        if not steps:
            raise ValueError("Job must have at least one step")
        self.name = name
        self.steps = steps

    def execute(self, job_execution: JobExecution) -> JobExecution:
        """执行作业。

        Args:
            job_execution: 作业执行上下文

        Returns:
            更新后的作业执行上下文
        """
        job_execution.start()
        logger.info(f"Job '{self.name}' started with {len(self.steps)} steps")

        try:
            for step in self.steps:
                step.execute(job_execution)
                # 检查上一步是否失败
                last_step = job_execution.step_executions[-1]
                if last_step.status == BatchStatus.FAILED:
                    job_execution.finish(BatchStatus.FAILED, ExitStatus.FAILED)
                    logger.error(f"Job '{self.name}' failed at step '{last_step.step_name}'")
                    return job_execution

            job_execution.finish(BatchStatus.COMPLETED, ExitStatus.COMPLETED)
            logger.info(
                f"Job '{self.name}' completed: "
                f"steps={len(job_execution.step_executions)}, "
                f"duration={job_execution.duration_ms:.0f}ms"
            )

        except Exception as e:
            job_execution.error_message = str(e)
            job_execution.finish(BatchStatus.FAILED, ExitStatus.FAILED)
            logger.error(f"Job '{self.name}' failed: {e}")

        return job_execution


# ==================== JobLauncher ====================

class JobLauncher:
    """作业启动器

    负责创建 JobExecution 并执行 Job。

    Usage::
        launcher = JobLauncher()
        execution = launcher.run(job)
    """

    def __init__(self):
        self._job_counter = 0

    def run(self, job: Job) -> JobExecution:
        """启动作业。

        Args:
            job: 要执行的作业

        Returns:
            作业执行上下文
        """
        self._job_counter += 1
        job_execution = JobExecution(job_name=job.name, job_id=self._job_counter)
        return job.execute(job_execution)
