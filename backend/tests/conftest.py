"""测试公共设施。

- 每个测试从**独立临时库**开始（不污染 dev 库）。
- 默认给所有测试注入一个"已登录用户"（覆盖三个鉴权依赖），这样既有的功能测试
  不用逐个改写成"先登录再调用"；**鉴权本身的测试**（test_auth / test_authz /
  test_admin）不走这条路，它们用真实令牌验证 401/403/404。
- 测试里建任务请带 `user_id=TEST_USER_ID`，否则按归属过滤后查不到。
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

# 测试用独立临时库，避免依赖/污染 dev 库 backend/data（该目录在部分环境只读）。
# 每次测试会话用随机名，避免并行测试进程互踩。
_tmp = Path(tempfile.gettempdir()) / f"docwise_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"

from helpers import (  # noqa: E402  (必须在 DATABASE_URL 设好之后导入)
    TEST_ADMIN_ID,
    TEST_USER_ID,
    TEST_USERNAME,
)

from app import main as app_main  # noqa: E402
from app.db import (  # noqa: E402  (需在 DATABASE_URL 之后导入)
    Base,
    SessionLocal,
    engine,
)
from app.deps import (  # noqa: E402
    get_current_user,
    get_user_for_events,
    get_user_for_files,
)
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

AUTH_TEST_MODULES = ("test_auth", "test_authz", "test_admin")

# 上传目录改到临时目录：避免往仓库 data/ 里写（部分环境该目录只读），
# 也让测试之间不互相干扰。
_UPLOADS = Path(tempfile.gettempdir()) / f"docwise_uploads_{uuid.uuid4().hex}"
app_main.UPLOAD_DIR = _UPLOADS
_UPLOADS.mkdir(parents=True, exist_ok=True)


def _is_auth_module(request) -> bool:
    name = getattr(request.module, "__name__", "")
    return name.endswith(AUTH_TEST_MODULES)


@pytest.fixture(autouse=True)
def _reset_db(request):
    """每个测试从空库开始。

    非鉴权测试（功能测试）额外准备「普通用户 + 管理员」两个账号，并让它们"默认已登录"；
    鉴权测试（test_auth / test_authz / test_admin）保持空库，自己注册账号走真实令牌
    ——这样"首个注册账号成为管理员"之类的行为才能被测到。
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app.dependency_overrides.clear()
    if not _is_auth_module(request):
        with SessionLocal() as session:
            session.add(
                User(
                    id=TEST_USER_ID,
                    username=TEST_USERNAME,
                    display_name="测试用户",
                    password_hash="not-a-real-hash",
                    role="user",
                )
            )
            session.add(
                User(
                    id=TEST_ADMIN_ID,
                    username="admin",
                    display_name="管理员",
                    password_hash="not-a-real-hash",
                    role="admin",
                )
            )
            session.commit()

        fake_user = User(
            id=TEST_USER_ID,
            username=TEST_USERNAME,
            display_name="测试用户",
            password_hash="not-a-real-hash",
            role="user",
        )
        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_user_for_files] = lambda: fake_user
        app.dependency_overrides[get_user_for_events] = lambda: fake_user

    yield

    app.dependency_overrides.clear()
