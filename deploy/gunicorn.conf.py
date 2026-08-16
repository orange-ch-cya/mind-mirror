# 心镜平台 Gunicorn 配置（文档 9.1）
# 单机部署：worker 数 = CPU 核数 + 1（建议 2-4）
bind = "127.0.0.1:8000"
workers = 3
worker_class = "sync"
timeout = 60
graceful_timeout = 30
accesslog = "/var/log/mind-mirror/access.log"
errorlog = "/var/log/mind-mirror/error.log"
loglevel = "info"
