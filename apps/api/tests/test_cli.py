import argparse
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentdesk_api import cli


def command_args() -> argparse.Namespace:
    return argparse.Namespace(
        command="bootstrap-admin",
        email="admin@example.com",
        name="System Admin",
    )


def test_command_disposes_engine_on_same_async_run(monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap_admin = AsyncMock()
    dispose = AsyncMock()
    monkeypatch.setattr(cli, "bootstrap_admin", bootstrap_admin)
    monkeypatch.setattr(cli, "engine", SimpleNamespace(dispose=dispose))

    asyncio.run(cli.run_command(command_args()))

    bootstrap_admin.assert_awaited_once_with("admin@example.com", "System Admin")
    dispose.assert_awaited_once_with()


def test_command_disposes_engine_when_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap_admin = AsyncMock(side_effect=ValueError("already exists"))
    dispose = AsyncMock()
    monkeypatch.setattr(cli, "bootstrap_admin", bootstrap_admin)
    monkeypatch.setattr(cli, "engine", SimpleNamespace(dispose=dispose))

    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(cli.run_command(command_args()))

    dispose.assert_awaited_once_with()
