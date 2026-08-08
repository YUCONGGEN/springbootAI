"""
SpringPy - Python版Spring Boot框架
集成PyMyBatis作为ORM层，提供企业级Web开发能力

核心特性：
- 依赖注入（IoC容器）
- Web MVC框架
- PyMyBatis ORM（SQL与代码分离）
- 事务管理
- 安全模块（JWT、RBAC、SQL注入防御）
- 连接池管理
- 多级缓存
- 服务发现（Nacos）
- 分布式事务（Seata）
- 消息队列（RabbitMQ）
- Prometheus监控
- SkyWalking分布式追踪
"""

from setuptools import setup, find_packages
import os

def read_readme():
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ''

def read_version():
    """从 spring/__init__.py 读取版本号（单一版本源）"""
    version_path = os.path.join(os.path.dirname(__file__), 'spring', '__init__.py')
    with open(version_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip("'\"")
    return '1.3.0'

setup(
    name='springpy',
    version=read_version(),
    description='Python版Spring Boot框架，集成PyMyBatis ORM',
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    author='YuConggen Team',
    author_email='dev@springpy.org',
    url='https://github.com/springpy/springpy',
    license='MIT',
    license_files=['LICENSE'],
    packages=find_packages(exclude=['tests', 'examples', 'example*']),
    include_package_data=True,
    package_data={
        'spring': ['*.py', '**/*.py', '**/*.xml', '**/*.yml', '**/*.yaml'],
    },
    install_requires=[
        # Web框架
        'fastapi>=0.110.0,<1.0.0',
        'uvicorn>=0.29.0',
        # 配置文件
        'pyyaml>=6.0.1',
        'python-dotenv>=1.0.0',
        # 数据库驱动
        'dbutils>=3.0.0',
        'cryptography>=38.0.0',
        'bcrypt>=4.0.0',
        # 认证授权
        'pyjwt>=2.8.0',
        # 参数校验
        'pydantic>=2.0.0',
    ],
    extras_require={
        # 数据库驱动
        'mysql': ['PyMySQL>=1.1.0'],
        'postgresql': ['psycopg2-binary>=2.9.0'],
        'oracle': ['cx-Oracle>=8.0.0'],
        'sqlite': [],
        'sqlalchemy': ['sqlalchemy>=2.0.0'],
        # Redis
        'redis': ['redis>=5.0.0'],
        # SQL注入检测
        'ast': ['sqlglot>=18.0.0'],
        # 消息队列
        'rabbitmq': ['pika>=1.3.0'],
        # 服务发现
        'nacos': ['nacos-sdk-python>=1.3.0'],
        # 监控
        'prometheus': ['prometheus-client>=0.20.0'],
        'logging': ['loguru>=0.7.0'],
        # 分布式事务
        'seata': ['seata>=1.7.0'],
        # 分布式追踪
        'skywalking': ['skywalking>=0.12.0'],
        # 开发依赖
        'dev': [
            'pytest>=7.0.0',
            'pytest-cov>=4.0.0',
            'flake8>=6.0.0',
            'black>=23.0.0',
            'redis>=5.0.0',
            'sqlglot>=18.0.0',
        ],
        # 完整依赖
        'full': [
            'PyMySQL>=1.1.0',
            'psycopg2-binary>=2.9.0',
            'sqlalchemy>=2.0.0',
            'redis>=5.0.0',
            'sqlglot>=18.0.0',
            'pika>=1.3.0',
            'nacos-sdk-python>=1.3.0',
            'prometheus-client>=0.20.0',
            'loguru>=0.7.0',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Database',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
    ],
    keywords=['spring', 'springboot', 'mybatis', 'orm', 'web', 'framework', 'python'],
    python_requires='>=3.8',
    entry_points={
        'console_scripts': [
            'springpy=spring.main:run_cli',
        ],
    },
)
