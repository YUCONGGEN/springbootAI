"""
批处理注解

提供 Spring Batch 风格的注解驱动批处理作业定义。

使用示例::

    @BatchJob(name="importUsers")
    class ImportUserJob:
        @BatchStep(name="readCsv", chunk_size=100)
        def read_csv_step(self):
            reader = CsvItemReader("users.csv")
            processor = FunctionItemProcessor(lambda x: x)
            writer = CsvItemWriter("output.csv")
            return Step("readCsv", reader, processor, writer, chunk_size=100)

对齐 Java Spring Batch：
- Java 通过 @Job 和 @Step 注解定义批处理作业
- Python 版本提供 @BatchJob 和 @BatchStep 注解标记作业和步骤
"""
from typing import Optional

from .core import SpringAnnotation


class BatchJob(SpringAnnotation):
    """标记一个类为批处理作业

    标记了此注解的类会被 BatchJobRegistry 注册，
    可通过 JobLauncher 执行或通过 @EnableBatchProcessing(auto_run=True) 自动执行。

    Attributes:
        name: 作业名称（必须唯一）
        description: 作业描述（可选）
        restartable: 是否允许重启失败的作业（默认 True）

    使用示例::

        @BatchJob(name="importUsers", description="导入用户数据")
        class ImportUserJob:
            def execute(self, job_launcher):
                # 定义并执行步骤
                pass
    """

    _annotation_type = "batch_job"

    def __init__(
        self,
        name: str,
        description: str = '',
        restartable: bool = True,
    ):
        super().__init__(
            name=name,
            description=description,
            restartable=restartable,
        )


class BatchStep(SpringAnnotation):
    """标记一个方法为批处理步骤

    标记了此注解的方法应返回一个 Step 对象或 Step 配置。

    Attributes:
        name: 步骤名称
        chunk_size: 分块大小（默认 10）
        retry_limit: 最大重试次数（默认 0，不重试）
        skip_limit: 最大跳过次数（默认 0，不跳过）

    使用示例::

        @BatchJob(name="dataPipeline")
        class DataPipelineJob:
            @BatchStep(name="extract", chunk_size=500)
            def extract_step(self):
                reader = CsvItemReader("input.csv")
                writer = ListItemWriter()
                return Step("extract", reader, None, writer, chunk_size=500)

            @BatchStep(name="transform", chunk_size=100, retry_limit=3)
            def transform_step(self):
                ...
    """

    _annotation_type = "batch_step"

    def __init__(
        self,
        name: str,
        chunk_size: int = 10,
        retry_limit: int = 0,
        skip_limit: int = 0,
    ):
        super().__init__(
            name=name,
            chunk_size=chunk_size,
            retry_limit=retry_limit,
            skip_limit=skip_limit,
        )
