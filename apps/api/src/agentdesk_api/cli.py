from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from agentdesk_api.db.models import User, UserIdentity
from agentdesk_api.db.session import async_session_factory, engine
from agentdesk_api.security import hash_password, normalized_email


async def bootstrap_admin(email: str, display_name: str) -> None:
    normalized = normalized_email(email)
    password = getpass.getpass("New Super Admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")

    async with async_session_factory() as session:
        existing = await session.scalar(select(User.id).where(User.email == normalized))
        if existing:
            raise ValueError("A user with this email already exists")
        user = User(
            email=normalized,
            display_name=display_name.strip(),
            system_role="super_admin",
            status="active",
        )
        identity = UserIdentity(
            user=user,
            provider_type="local",
            provider_subject=normalized,
            email_at_link_time=normalized,
            password_hash=hash_password(password),
            mfa_required=True,
            status="active",
        )
        session.add_all([user, identity])
        await session.commit()
        print(f"Created Super Admin: {normalized}")


async def reset_password(email: str) -> None:
    normalized = normalized_email(email)
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")

    async with async_session_factory() as session:
        identity = await session.scalar(
            select(UserIdentity).where(
                UserIdentity.provider_type == "local",
                UserIdentity.provider_subject == normalized,
            )
        )
        if identity is None:
            raise ValueError(f"Local account not found: {normalized}")
        identity.password_hash = hash_password(password)
        identity.password_changed_at = datetime.now(UTC)
        identity.status = "active"
        await session.commit()
        print(f"Password reset: {normalized}")


async def run_command(args: argparse.Namespace) -> None:
    try:
        if args.command == "bootstrap-admin":
            await bootstrap_admin(args.email, args.name)
        elif args.command == "reset-password":
            await reset_password(args.email)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentDesk administration commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser("bootstrap-admin")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--name", required=True)
    reset = subparsers.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    args = parser.parse_args()

    try:
        asyncio.run(run_command(args))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
