#!/usr/bin/env python3
"""Command-line interface for Forge administration tasks."""

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from forge.core.config import settings
from forge.core.security import hash_password, validate_password
from forge.models import AccountState, User, UserRole, UserRoleAssignment


async def create_admin_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
) -> None:
    """Create the initial admin user in the database."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as db:
        # Check if user already exists
        existing = await db.scalar(select(User).where(User.email == email.lower()))
        if existing:
            print(f"Error: A user with email '{email}' already exists.")
            sys.exit(1)

        # Check if any admin exists
        admin_role = await db.scalar(
            select(UserRoleAssignment).where(UserRoleAssignment.role == UserRole.ADMIN)
        )
        if admin_role:
            print("Warning: An admin user already exists in the system.")
            response = input("Do you want to create another admin? (yes/no): ")
            if response.lower() != "yes":
                print("Aborted.")
                sys.exit(0)

        # Validate password
        validation = validate_password(password)
        if not validation.is_valid:
            print("Error: Password does not meet requirements:")
            for error in validation.errors:
                print(f"  - {error}")
            sys.exit(1)

        # Create user
        user = User(
            id=uuid.uuid4(),
            email=email.lower(),
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            account_state=AccountState.ACTIVE,
        )
        db.add(user)
        await db.flush()

        # Assign admin role
        role = UserRoleAssignment(
            user_id=user.id,
            role=UserRole.ADMIN,
        )
        db.add(role)

        await db.commit()

        print("\nAdmin user created successfully!")
        print(f"  Email: {email}")
        print(f"  Name: {first_name} {last_name}")
        print(f"  ID: {user.id}")
        print("\nYou can now log in at /api/v1/auth/login")

    await engine.dispose()


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Forge CLI - Administration tools for the KamiLimu Learning System"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create-admin command
    admin_parser = subparsers.add_parser(
        "create-admin",
        help="Create the initial admin user",
        description="Create the first admin user who can then invite other users.",
    )
    admin_parser.add_argument(
        "--email",
        required=True,
        help="Admin user's email address",
    )
    admin_parser.add_argument(
        "--first-name",
        required=True,
        help="Admin user's first name",
    )
    admin_parser.add_argument(
        "--last-name",
        required=True,
        help="Admin user's last name",
    )
    admin_parser.add_argument(
        "--password",
        help="Admin user's password (will prompt if not provided)",
    )

    args = parser.parse_args()

    if args.command == "create-admin":
        password = args.password
        if not password:
            password = getpass.getpass("Enter password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Error: Passwords do not match.")
                sys.exit(1)

        asyncio.run(
            create_admin_user(
                email=args.email,
                password=password,
                first_name=args.first_name,
                last_name=args.last_name,
            )
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
