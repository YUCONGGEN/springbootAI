import multiprocessing
import os

if os.path.exists('/etc/springpy/gunicorn.conf.py'):
    pass

workers = multiprocessing.cpu_count() * 2 + 1
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

preload_app = True
worker_connections = 1000
backlog = 2048
