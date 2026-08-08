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
    author='YuConggen',
    author_email='1516933915@qq.com',
    url='https://github.com/YUCONGGEN/springboot_cloud_python.git',
    license='MIT',
    license_files=['LICENSE'],
    packages=find_packages(exclude=['tests', 'examples', 'example*']),
    include_package_data=True,
    package_data={
        'spring': ['*.py', '**/*.py', '**/*.xml', '**/*.yml', '**/*.yaml'],
    },
    install_requires=[
        # Web框架
        'fastapi==0.128.8',
        'uvicorn==0.39.0',
        # 配置文件
        'pyyaml==6.0.3',
        'python-dotenv==1.2.1',
        # 数据库驱动
        'DBUtils==3.1.2',
        'cryptography==48.0.1',
        'bcrypt==5.0.0',
        # 认证授权
        'pyjwt==2.13.0',
        # 参数校验
        'pydantic==2.13.4',
    ],
    extras_require={
        # 数据库驱动
        'mysql': ['PyMySQL==1.2.0'],
        'postgresql': ['psycopg2-binary==2.9.11'],
        'oracle': ['cx-Oracle>=8.0.0'],
        'sqlite': [],
        'sqlalchemy': ['sqlalchemy==2.0.40'],
        # Redis
        'redis': ['redis==7.0.1'],
        # SQL注入检测
        'ast': ['sqlglot==27.28.1'],
        # 消息队列
        'rabbitmq': ['pika==1.4.4'],
        # 服务发现
        'nacos': ['nacos-sdk-python==2.0.11'],
        # 监控
        'prometheus': ['prometheus-client==0.26.0'],
        'logging': ['loguru==0.7.3'],
        # 分布式事务
        'seata': ['seata>=1.7.0'],
        # 分布式追踪
        'skywalking': ['skywalking>=0.12.0'],
        # 开发依赖
        'dev': [
            'pytest==8.4.2',
            'pytest-cov==7.1.0',
            'flake8==7.3.0',
            'black==25.1.0',
            'redis==7.0.1',
            'sqlglot==27.28.1',
        ],
        # 完整依赖
        'full': [
            'PyMySQL==1.2.0',
            'psycopg2-binary==2.9.11',
            'sqlalchemy==2.0.40',
            'redis==7.0.1',
            'sqlglot==27.28.1',
            'pika==1.4.4',
            'nacos-sdk-python==2.0.11',
            'prometheus-client==0.26.0',
            'loguru==0.7.3',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Database',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
    ],
    keywords=['spring', 'springboot', 'mybatis', 'orm', 'web', 'framework', 'python'],
    python_requires='>=3.9',
    entry_points={
        'console_scripts': [
            'springpy=spring.main:run_cli',
        ],
    },
)
