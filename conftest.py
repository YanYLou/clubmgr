# conftest.py
#
# 阶段 0.5 说明：仓库根的导入路径现在由 pytest.ini 的 pythonpath=. 提供，
# 本文件不再是 import domain / infrastructure 能成功的必要条件；
# 保留它是为了放共享 fixture（阶段 1 的服务层测试会用到内存库 fixture）。
