"""
根级 conftest：当 TEST_USE_SQLITE=1 时（本地 make test），
settings.py 自动切换到内存 SQLite，无需 MySQL 容器。
容器内（IS_DOCKER=1 或不设此 env）走原始 MySQL。
"""
# 此文件故意留空——env var 切换由 Makefile 注入，settings.py 读取。
# pytest 需要在 rootdir 存在 conftest.py 才能正确发现 tests/ 目录。
