"""pytest 全局配置：**测试只连测试库**（A5，2026-10-27）+ 跑完清理测试数据。

一、为什么强制 TEST_DATABASE_URL
--------------------------------
2026-10-27 之前：601 个测试直接拿 `.env` 的 `DATABASE_URL` 连**正式库** `erp`。
测试会真实建商品/客户/供应商/仓库，会走审核与状态机；收尾靠事后按名字擦数据
（`scripts/clean_test_data.py`）。擦不干净就污染业务列表 —— 商品总数突破接口默认
分页上限 500、导致分页断言不稳那次就是这么来的；更糟的是，任何一行写错的
DELETE/UPDATE 都会直接改到生产数据上。

现在：连接串**只认** `TEST_DATABASE_URL`，并在 pytest 收集测试**之前**把它写进
`os.environ['DATABASE_URL']`。`app.core.config.settings` 里环境变量优先于 .env，
所以应用代码一行都不用改，整场测试就落到测试库上。

  · 没配 TEST_DATABASE_URL            → 整场测试中止（exit code 2），一个都不跑；
  · 配成和生产库同一个 host/端口/库名 → 同样中止；
  · 配成远端主机                      → 放行，但大声告警（团队共享测试库的场景）。

起测试库（独立实例，不碰 5432，不需要超级用户密码）：

    python scripts\\test_db.py init      # 首次
    python scripts\\test_db.py start     # 每次开机后
    python -m pytest

二、跑完清理测试数据
--------------------
清理规则见 `scripts/clean_test_data.py`：按测试脚本里写死的名称匹配，不误伤真实数据。
现在它清的是**测试库**里的残留，生产库在这条链路里根本连不上。

三、鉴权收口后的测试适配（P0-1「方案 B」，2026-10-26）
-----------------------------------------------------
`/api/v1` 现在**默认拒绝匿名请求**（白名单只有 health / login / register / 商品图）。
存量 61 个测试文件、几百条用例都是在 `TestClient(app)` 上直接打业务接口的，
没有一条带过登录语义。

这里不去改那几百条用例（改不完，而且会把"接口行为断言"和"登录样板"搅在一起），
而是**在 conftest 里给每个 TestClient 统一注入一张管理员 token**：

  · 被测代码跑的是**生产口径**（auth_mode 默认 enforce，不为测试开后门）；
  · 用例里显式传 `headers={'Authorization': ...}` 时以用例为准（逐请求头会覆盖默认值），
    需要验证"匿名应被拒"的用例就靠这个把默认 token 抵掉；
  · token 用 `admin`（`ensure_default_admin_user` 保证存在，签名密钥就是本进程的真实密钥），
    所以网关里"回库确认账号存在且未停用"那一段也是真跑的。
"""

import importlib.util
import os
import tempfile
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / '.env'
PROD_KEY = 'DATABASE_URL'
TEST_KEY = 'TEST_DATABASE_URL'

# 密钥落盘位置：测试不去写用户目录（`~/.erp_core/secret_key`），扔进系统临时目录。
# 必须在 import app.* 之前设置 —— 见 pytest_sessionstart 的注释。
os.environ.setdefault('ERP_SECRET_FILE', str(Path(tempfile.gettempdir()) / 'erp_core_test_secret_key'))


def _env_file_value(key):
    """直接读 .env 的一行。

    不 import dotenv：测试还没开始就依赖第三方包，反而多一处失败点。
    """
    if not ENV_FILE.exists():
        return None
    for raw in ENV_FILE.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'") or None
    return None


def _setting(key):
    """环境变量优先，其次项目根 .env —— 与 pydantic-settings 的优先级一致。"""
    return (os.environ.get(key) or '').strip() or _env_file_value(key)


def _parts(url):
    parsed = urllib.parse.urlsplit(url.replace('postgresql+psycopg://', 'postgresql://', 1))
    return {
        'host': (parsed.hostname or '').lower(),
        'port': parsed.port or 5432,
        'db': (parsed.path or '').lstrip('/'),
        'user': parsed.username or '',
    }


def _masked(url):
    p = _parts(url)
    return '%s@%s:%s/%s' % (p['user'] or '?', p['host'] or '?', p['port'], p['db'] or '?')


_HOWTO = (
    '起测试库：\n'
    '    python scripts\\test_db.py init      # 首次，会顺手把 TEST_DATABASE_URL 写进 .env\n'
    '    python scripts\\test_db.py start     # 每次开机后\n'
    '也可以手工指定任意一个**不是生产库**的 PostgreSQL：\n'
    '    set TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:55432/erp_test'
)

_admin_token_cache = None


def _admin_token():
    """一张管理员 token（懒创建）。

    必须懒：`settings.secret_key` 要等 `app.core.config` 被 import 才有，
    而 import 它的那一刻 `settings` 就定型了 —— 必须晚于 sessionstart 里换库那一步。
    能用 `admin` 是因为 `create_app()` 里 `ensure_default_admin_user` 保证它存在。
    """
    global _admin_token_cache
    if _admin_token_cache is None:
        from app.core.security import create_access_token

        _admin_token_cache = create_access_token(
            subject='admin', role='admin', expires_delta=60 * 24 * 7
        )
    return _admin_token_cache


def _install_authed_test_client():
    """给所有 `TestClient` 默认带上管理员凭证（P0-1 收口后 /api/v1 默认拒绝匿名）。

    为什么替换类而不是给每个用例加 headers：存量 61 个文件、几百条用例，一个个改
    既改不完也容易漏；替换类只需要在 conftest 里写一次，用例主体一行都不用动，
    而且**被测代码仍然是生产口径**（不靠 env 关鉴权）。

    逐请求传的 `headers={'Authorization': ...}` 优先级更高，所以需要验证"匿名被拒"
    的用例直接传一个假 token 就能把默认值抵掉，见 `tests/test_auth_gate.py`。
    """
    import fastapi.testclient as testclient

    if getattr(testclient.TestClient, '_erp_authed', False):
        return  # 重复调用不叠加

    base = testclient.TestClient

    class AuthedTestClient(base):
        _erp_authed = True

        def __init__(self, *args, **kwargs):
            headers = dict(kwargs.pop('headers', None) or {})
            headers.setdefault('Authorization', 'Bearer %s' % _admin_token())
            super().__init__(*args, headers=headers, **kwargs)

    AuthedTestClient.__name__ = 'TestClient'
    AuthedTestClient.__qualname__ = 'TestClient'
    testclient.TestClient = AuthedTestClient


_test_url = _setting(TEST_KEY)
_prod_url = _setting(PROD_KEY)

_test = _parts(_test_url) if _test_url else {}
_prod = _parts(_prod_url) if _prod_url else {}


def pytest_sessionstart(session):
    """在收集任何测试（因而在 import app.*）之前，把连接串钉死到测试库。

    为什么在这里而不是 conftest 模块顶层：模块顶层抛 `pytest.exit` 会被 pytest
    包装成 "ImportError while loading conftest"，红字一大片、看不出人话。
    sessionstart 阶段抛则是一条干净的退出信息，且**仍然早于**测试模块 import，
    `app.core.config.settings` 读到的已经是测试库。
    """
    if not _test_url:
        pytest.exit(
            '[conftest] 拒绝运行：没有配置 TEST_DATABASE_URL。\n'
            '测试绝不允许连生产库（当前 DATABASE_URL = %s）。\n%s'
            % (_masked(_prod_url) if _prod_url else '未配置', _HOWTO),
            returncode=2,
        )

    if not _test.get('db'):
        pytest.exit(
            '[conftest] 拒绝运行：TEST_DATABASE_URL 里没有库名（%s）。\n%s'
            % (_masked(_test_url), _HOWTO),
            returncode=2,
        )

    if _prod and (_test['host'], _test['port'], _test['db']) == (_prod['host'], _prod['port'], _prod['db']):
        pytest.exit(
            '[conftest] 拒绝运行：TEST_DATABASE_URL 和 DATABASE_URL 指向同一个库（%s）。\n'
            '这正是要拆的那颗雷 —— 测试会直接改生产数据。\n%s'
            % (_masked(_test_url), _HOWTO),
            returncode=2,
        )

    # 关键一步：把连接串换成测试库。
    os.environ[PROD_KEY] = _test_url
    os.environ['ERP_TEST_DATABASE'] = _test_url

    # 也在这一步之后才碰 app.*：conftest 顶层若先 import 了 app.core.config，
    # settings 就会在 DATABASE_URL 被换成测试库**之前**实例化，整场测试会打到生产库。
    _install_authed_test_client()

    print('[conftest] 测试库：%s' % _masked(_test_url))
    if _prod:
        print('[conftest] 生产库：%s —— 本场测试不会连接它' % _masked(_prod_url))
    if _test['host'] not in ('127.0.0.1', 'localhost', '::1'):
        print('[conftest] 警告：测试库在远端主机 %s，确认那是测试库而不是生产库' % _test['host'])


def _load_cleaner():
    path = os.path.join(str(ROOT), 'scripts', 'clean_test_data.py')
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
            print('\n[conftest] 已自动清理 %s 行测试残留数据（测试库）' % removed)
    except Exception as exc:  # 清理失败不能影响测试结论
        print('\n[conftest] 测试数据清理失败: %s' % exc)

