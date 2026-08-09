"""
WSGI/ASGI 入口点 (生产部署用)

用于 Gunicorn + UvicornWorker 部署:
    gunicorn wsgi:app -c deploy/gunicorn/gunicorn.conf.py
"""
from spring.main import create_app

# 默认示例应用入口
# 用户需要修改为自己的 Application 类
try:
    from example_all.Application import Application
    app = create_app(Application)
except ImportError:
    # 如果example_all不可用，提供一个最小ASGI应用占位
    from fastapi import FastAPI
    from spring import __version__
    app = FastAPI(title="SpringPy", version=__version__)

    @app.get("/")
    async def root():
        return {"message": "SpringPy application not configured", "status": "setup"}
