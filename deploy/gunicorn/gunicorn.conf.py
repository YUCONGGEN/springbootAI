import multiprocessing
import os

if os.path.exists('/etc/springpy/gunicorn.conf.py'):
    pass

workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
bind = "127.0.0.1:8080"
timeout = 30
keepalive = 5
max_requests = 10000
max_requests_jitter = 1000
graceful_timeout = 30

accesslog = "-"
errorlog = "-"
loglevel = "info"

access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s %(D)s'

# SpringPy initializes DB pools and optional clients while importing wsgi.py.
# Never fork workers from an already initialized application process.
preload_app = False
worker_connections = 1000
backlog = 2048


def child_exit(server, worker):
    """Remove dead worker gauge files from Prometheus multiprocess storage."""
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except ImportError:
        pass
