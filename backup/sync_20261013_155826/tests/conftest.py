"""pytest 全局配置：测试结束后自动清理测试数据。

本项目的测试直接连正式 PostgreSQL 库（不是内存库或临时库），测试过程会真实
创建商品/客户/供应商/仓库等档案。以前这些数据跑完就留在库里，累积几十次之后
商品总数突破了接口默认分页上限（500），既污染业务列表，也让依赖分页的断言
变得不稳定。

这里挂一个 session 级的自动清理：整套测试跑完（无论通过与否）自动删除测试档案。
清理规则见 scripts/clean_test_data.py —— 按测试脚本里写死的名称匹配，不会误伤
真实业务数据。
"""

import importlib.util
import os

import pytest


def _load_cleaner():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'scripts', 'clean_test_data.py')
    spec = importlib.util.spec_from_file_location('_clean_test_data', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='session', autouse=True)
def _cleanup_test_data_after_session():
    yield
    try:
        cleaner = _load_cleaner()
        removed = cleaner.run_cleanup(verbose=False)
        if removed:
            print(f'\n[conftest] 已自动清理 {removed} 行测试残留数据')
    except Exception as exc:  # 清理失败不能影响测试结论
        print(f'\n[conftest] 测试数据清理失败: {exc}')
