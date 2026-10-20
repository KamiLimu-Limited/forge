"""Shared fixtures. Tests run against a real Postgres database (see compose.yaml)."""

import os

TEST_DATABASE_URL = os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://forge:forge@localhost:5433/forge_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["RESEND_API_KEY"] = ""

import uuid  # noqa: E402
from collections.abc import AsyncGenerator, Iterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import UTC, date, datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from forge.core.jwt import create_access_token  # noqa: E402
from forge.core.rate_limit import auth_rate_limiter  # noqa: E402
from forge.core.security import hash_password  # noqa: E402
from forge.db.session import get_db  # noqa: E402
from forge.main import app  # noqa: E402
from forge.models import (  # noqa: E402
    AccountState,
    Cohort,
    CohortEnrollment,
    CohortStatus,
    Invitation,
    ProgrammeSession,
    ProgrammeType,
    SessionCategory,
    SessionStatus,
    SessionType,
    User,
    UserRole,
    UserRoleAssignment,
)
from forge.services.windows import sync_window  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Apply migrations from scratch once per test session."""
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield TEST_DATABASE_URL


@pytest_asyncio.fixture(scope="session")
async def engine(migrated_database: str) -> AsyncGenerator[AsyncEngine]:
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """A session whose commits become savepoints inside a rolled-back transaction."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        # Each request starts with an empty identity map, like a real per-request session.
        db_session.expunge_all()
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    auth_rate_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def token_for(user: User) -> dict[str, str]:
    token, _, _ = create_access_token(user.id)
    return auth_header(token)


@dataclass
class Factory:
    """Builds persisted test data with sensible defaults."""

    db: AsyncSession

    async def user(
        self,
        email: str | None = None,
        *roles: UserRole,
        password: str | None = "Password123",
        state: AccountState = AccountState.ACTIVE,
        cohort_id: uuid.UUID | None = None,
        first_name: str = "Test",
        last_name: str = "User",
    ) -> User:
        user = User(
            email=email or f"user-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password(password) if password else None,
            first_name=first_name,
            last_name=last_name,
            account_state=state,
        )
        user.roles = [UserRoleAssignment(role=r, cohort_id=cohort_id) for r in roles]
        self.db.add(user)
        await self.db.commit()
        return user

    async def cohort(self, **overrides: object) -> Cohort:
        today = date.today()
        values: dict[str, object] = {
            "name": f"Cohort {uuid.uuid4().hex[:6]}",
            "programme_type": ProgrammeType.UNDERGRADUATE,
            "start_date": today - timedelta(days=60),
            "end_date": today + timedelta(days=240),
            "status": CohortStatus.ACTIVE,
            "ict_tracks_offered": ["web", "data"],
            "skill_names": ["communication", "leadership", "technical"],
            "leaderboard_anonymous": False,
        }
        cohort = Cohort(**(values | overrides))
        self.db.add(cohort)
        await self.db.commit()
        return cohort

    async def enroll(
        self,
        user: User,
        cohort: Cohort,
        role: UserRole = UserRole.MENTEE,
        *,
        peer_mentor: User | None = None,
        ict_track: str | None = None,
        enrolled_at: datetime | None = None,
    ) -> CohortEnrollment:
        enrollment = CohortEnrollment(
            user_id=user.id,
            cohort_id=cohort.id,
            role=role,
            peer_mentor_id=peer_mentor.id if peer_mentor else None,
            ict_track=ict_track,
            enrolled_at=enrolled_at or datetime.now(UTC) - timedelta(days=59),
        )
        self.db.add(enrollment)
        self.db.add(UserRoleAssignment(user_id=user.id, role=role, cohort_id=cohort.id))
        await self.db.commit()
        return enrollment

    async def session(
        self,
        cohort: Cohort,
        *,
        starts_at: datetime | None = None,
        status: SessionStatus = SessionStatus.PUBLISHED,
        category: SessionCategory = SessionCategory.THURSDAY,
        session_type: SessionType = SessionType.CORE,
        track: str | None = None,
        points: int = 10,
        kami_limu_month: int = 1,
        title: str = "Session",
    ) -> ProgrammeSession:
        session = ProgrammeSession(
            cohort_id=cohort.id,
            title=title,
            kami_limu_month=kami_limu_month,
            starts_at=starts_at or datetime.now(UTC) - timedelta(hours=3),
            duration_minutes=120,
            category=category,
            session_type=session_type,
            track=track,
            points=points,
            status=status,
            mentors=[],
            resources=[],
        )
        self.db.add(session)
        await self.db.flush()
        if status is SessionStatus.PUBLISHED:
            await sync_window(self.db, session, cohort)
        await self.db.commit()
        return session


@pytest.fixture
def factory(db_session: AsyncSession) -> Factory:
    return Factory(db_session)


@pytest_asyncio.fixture
async def admin_user(factory: Factory) -> User:
    return await factory.user(
        "admin@test.com", UserRole.ADMIN, password="AdminPass123", first_name="Admin"
    )


@pytest_asyncio.fixture
async def regular_user(factory: Factory) -> User:
    return await factory.user(
        "user@test.com", UserRole.MENTEE, password="UserPass123", first_name="Regular"
    )


@pytest_asyncio.fixture
async def pending_user(factory: Factory) -> User:
    return await factory.user(
        "pending@test.com",
        password=None,
        state=AccountState.PENDING,
        first_name="Pending",
    )


@pytest_asyncio.fixture
async def suspended_user(factory: Factory) -> User:
    return await factory.user(
        "suspended@test.com",
        password="SuspendedPass123",
        state=AccountState.SUSPENDED,
        first_name="Suspended",
    )


@pytest_asyncio.fixture
async def valid_invitation(db_session: AsyncSession, admin_user: User) -> Invitation:
    invitation = Invitation(
        email="newuser@test.com",
        token="valid-invitation-token",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        invited_by=admin_user.id,
        first_name="New",
        last_name="User",
        intended_roles=[UserRole.MENTEE.value],
    )
    db_session.add(invitation)
    await db_session.commit()
    return invitation


@pytest_asyncio.fixture
async def expired_invitation(db_session: AsyncSession, admin_user: User) -> Invitation:
    invitation = Invitation(
        email="expired@test.com",
        token="expired-invitation-token",
        expires_at=datetime.now(UTC) - timedelta(days=1),
        invited_by=admin_user.id,
    )
    db_session.add(invitation)
    await db_session.commit()
    return invitation


@pytest.fixture
def admin_token(admin_user: User) -> str:
    return create_access_token(admin_user.id)[0]


@pytest.fixture
def user_token(regular_user: User) -> str:
    return create_access_token(regular_user.id)[0]


@dataclass
class Programme:
    """A populated cohort: admin, committee, peer mentors and three mentees."""

    cohort: Cohort
    admin: User
    committee: User
    peer_mentor: User
    ict_mentor: User
    prof_mentor: User
    mentees: list[User]
    outsider: User


@pytest_asyncio.fixture
async def programme(factory: Factory, admin_user: User) -> Programme:
    cohort = await factory.cohort()
    committee = await factory.user("committee@test.com", first_name="Comm")
    await factory.enroll(committee, cohort, UserRole.COMMITTEE)
    peer_mentor = await factory.user("peer@test.com", first_name="Peer")
    await factory.enroll(peer_mentor, cohort, UserRole.PEER_MENTOR_1_1)
    ict_mentor = await factory.user("ict@test.com", first_name="Ict")
    await factory.enroll(ict_mentor, cohort, UserRole.PEER_MENTOR_ICT, ict_track="web")
    prof_mentor = await factory.user(
        "prof@test.com", UserRole.PROFESSIONAL_MENTOR, first_name="Prof"
    )
    mentees = []
    for i in range(3):
        mentee = await factory.user(f"mentee{i}@test.com", first_name=f"Mentee{i}")
        await factory.enroll(
            mentee,
            cohort,
            peer_mentor=peer_mentor if i < 2 else None,
            ict_track="web" if i == 0 else "data",
        )
        mentees.append(mentee)
    outsider = await factory.user(
        "outsider@test.com", UserRole.MENTEE, first_name="Out"
    )
    return Programme(
        cohort,
        admin_user,
        committee,
        peer_mentor,
        ict_mentor,
        prof_mentor,
        mentees,
        outsider,
    )
