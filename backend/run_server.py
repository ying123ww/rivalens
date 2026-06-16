#!/usr/bin/env python3
"""Rivalens 后端服务启动脚本。"""

import os
import signal
import sys
import logging
import time

import uvicorn
from dotenv import load_dotenv

# 将项目根目录和后端目录加入导入路径，确保直接运行本文件时也能加载模块。
backend_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(backend_dir, ".."))
os.environ.pop("OPENAI_API_KEY", None)
load_dotenv(os.path.join(repo_root, ".env"))
sys.path.insert(0, repo_root)
sys.path.insert(0, backend_dir)


class RivalensServer(uvicorn.Server):
    """记录导致 Uvicorn 退出的系统信号，方便排查意外关停。"""

    def __init__(self, config):
        super().__init__(config)
        self._started_at = time.monotonic()
        self._ignored_startup_sigint = False

    def handle_exit(self, sig, frame):
        try:
            signal_name = signal.Signals(sig).name
        except ValueError:
            signal_name = str(sig)
        if (
            sig == signal.SIGINT
            and not self._ignored_startup_sigint
            and time.monotonic() - self._started_at
            < float(os.getenv("RIVALENS_IGNORE_STARTUP_SIGINT_SECONDS", "5"))
        ):
            self._ignored_startup_sigint = True
            logging.getLogger("uvicorn.error").warning(
                "Ignored startup shutdown signal: %s. Press Ctrl+C again after startup to stop.",
                signal_name,
            )
            return
        logging.getLogger("uvicorn.error").warning(
            "Rivalens server received shutdown signal: %s",
            signal_name,
        )
        super().handle_exit(sig, frame)


if __name__ == "__main__":
    # 保持历史行为：输出、静态目录等相对路径以 backend 目录为基准。
    os.chdir(backend_dir)

    host = os.getenv("RIVALENS_HOST", "127.0.0.1")
    port = int(os.getenv("RIVALENS_PORT", "8000"))
    reload_enabled = os.getenv("RIVALENS_RELOAD", "").lower() in {"1", "true", "yes", "on"}

    if reload_enabled:
        uvicorn.run(
            "server.app:app",
            host=host,
            port=port,
            reload=True,
            log_level="info",
        )
    else:
        config = uvicorn.Config(
            "server.app:app",
            host=host,
            port=port,
            log_level="info",
        )
        try:
            RivalensServer(config).run()
        except KeyboardInterrupt:
            pass



