from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import Conversation, ConversationKind
from echo_server.domain.messages import (
    ConversationSyncQuery,
    SubmitMessageCommand,
    SyncMessagesQuery,
)
from echo_server.runtime.application_runtime import (
    ApplicationRuntime,
    InvalidCursorError,
)
from echo_server.store.database import Database

BASE_TIME = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def sync_runtime(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
    )
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=lambda: BASE_TIME,
    )
    await runtime.start()
    await create_conversation(runtime, "second-conversation", "acheng")
    yield runtime
    if runtime.database.is_open:
        await runtime.stop()


async def create_conversation(
    runtime: ApplicationRuntime,
    conversation_id: str,
    character_id: str,
) -> None:
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.runtime_conversations.create(
            Conversation(
                account_id=runtime.settings.account_id,
                conversation_id=conversation_id,
                kind=ConversationKind.DIRECT,
                created_at_utc=BASE_TIME,
                updated_at_utc=BASE_TIME,
            ),
            connection=connection,
        )


async def submit(
    runtime: ApplicationRuntime,
    conversation_id: str,
    text: str,
) -> None:
    await runtime.submit_message(
        SubmitMessageCommand(
            account_id=runtime.settings.account_id,
            conversation_id=conversation_id,
            player_text=text,
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=BASE_TIME,
        )
    )


@pytest.mark.asyncio
async def test_runtime_sync_isolates_conversations_and_binds_cursor(sync_runtime):
    runtime = sync_runtime
    account_id = runtime.settings.account_id
    await submit(runtime, "xiaojin", "A first")
    await submit(runtime, "second-conversation", "B first")

    first_a = await runtime.sync_conversation_messages(
        ConversationSyncQuery(account_id=account_id, conversation_id="xiaojin")
    )
    assert [message.text for message in first_a.messages] == ["A first"]
    assert first_a.next_cursor != ""

    first_b = await runtime.sync_conversation_messages(
        ConversationSyncQuery(account_id=account_id, conversation_id="second-conversation")
    )
    assert [message.text for message in first_b.messages] == ["B first"]

    with pytest.raises(InvalidCursorError):
        await runtime.sync_conversation_messages(
            ConversationSyncQuery(
                account_id=account_id,
                conversation_id="second-conversation",
                since=first_a.next_cursor,
            )
        )

    await submit(runtime, "xiaojin", "A second")
    second_a = await runtime.sync_conversation_messages(
        ConversationSyncQuery(
            account_id=account_id,
            conversation_id="xiaojin",
            since=first_a.next_cursor,
        )
    )
    assert [message.text for message in second_a.messages] == ["A second"]
    assert all(message.conversation_id == "xiaojin" for message in second_a.messages)

    empty_a = await runtime.sync_conversation_messages(
        ConversationSyncQuery(
            account_id=account_id,
            conversation_id="xiaojin",
            since=second_a.next_cursor,
        )
    )
    assert empty_a.messages == ()
    assert empty_a.next_cursor == second_a.next_cursor

    account_stream = await runtime.sync_messages(SyncMessagesQuery(account_id=account_id))
    assert [message.text for message in account_stream.messages] == [
        "A first",
        "B first",
        "A second",
    ]


@pytest.mark.asyncio
async def test_account_sync_empty_page_does_not_skip_concurrent_message(sync_runtime, monkeypatch):
    runtime = sync_runtime
    account_id = runtime.settings.account_id
    await submit(runtime, "xiaojin", "before account cursor")
    initial = await runtime.sync_messages(SyncMessagesQuery(account_id=account_id))
    injected = False
    original_list_account = runtime.runtime_messages.list_account

    async def list_account_with_concurrent_write(
        account: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        connection=None,
    ):
        nonlocal injected
        messages = await original_list_account(
            account,
            after_sequence=after_sequence,
            limit=limit,
            connection=connection,
        )
        if not injected:
            injected = True
            await submit(runtime, "xiaojin", "during account sync")
        return messages

    monkeypatch.setattr(
        runtime.runtime_messages,
        "list_account",
        list_account_with_concurrent_write,
    )
    empty = await runtime.sync_messages(
        SyncMessagesQuery(account_id=account_id, since=initial.next_cursor)
    )

    assert empty.messages == ()
    assert empty.next_cursor == initial.next_cursor
    following = await runtime.sync_messages(
        SyncMessagesQuery(account_id=account_id, since=empty.next_cursor)
    )
    assert [message.text for message in following.messages] == ["during account sync"]


@pytest.mark.asyncio
async def test_conversation_sync_empty_page_does_not_skip_concurrent_message(
    sync_runtime, monkeypatch
):
    runtime = sync_runtime
    account_id = runtime.settings.account_id
    conversation_id = "xiaojin"
    await submit(runtime, conversation_id, "before conversation cursor")
    initial = await runtime.sync_conversation_messages(
        ConversationSyncQuery(account_id=account_id, conversation_id=conversation_id)
    )
    injected = False
    original_list_conversation = runtime.runtime_messages.list_conversation

    async def list_conversation_with_concurrent_write(
        account: str,
        conversation: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        connection=None,
    ):
        nonlocal injected
        messages = await original_list_conversation(
            account,
            conversation,
            after_sequence=after_sequence,
            limit=limit,
            connection=connection,
        )
        if not injected:
            injected = True
            await submit(runtime, conversation_id, "during conversation sync")
        return messages

    monkeypatch.setattr(
        runtime.runtime_messages,
        "list_conversation",
        list_conversation_with_concurrent_write,
    )
    empty = await runtime.sync_conversation_messages(
        ConversationSyncQuery(
            account_id=account_id,
            conversation_id=conversation_id,
            since=initial.next_cursor,
        )
    )

    assert empty.messages == ()
    assert empty.next_cursor == initial.next_cursor
    following = await runtime.sync_conversation_messages(
        ConversationSyncQuery(
            account_id=account_id,
            conversation_id=conversation_id,
            since=empty.next_cursor,
        )
    )
    assert [message.text for message in following.messages] == ["during conversation sync"]


@pytest.mark.asyncio
async def test_http_session_sync_preserves_compatibility_and_rejects_scoped_cursor(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
    )
    app = __import__("echo_server.main", fromlist=["create_app"]).create_app(
        settings,
        StubCharacterAgent(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        runtime = app.state.runtime
        await create_conversation(runtime, "second-conversation", "acheng")
        await submit(runtime, "xiaojin", "A message")
        await submit(runtime, "second-conversation", "B message")

        response = await client.get("/conversations/xiaojin/messages")
        assert response.status_code == 200
        assert [message["text"] for message in response.json()["messages"]] == ["A message"]
        cursor = response.json()["nextCursor"]

        response = await client.get(
            "/conversations/second-conversation/messages",
            params={"since": cursor},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"

        response = await client.get("/conversations/unknown/messages")
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"

        response = await client.get("/message/sync")
        assert response.status_code == 200
        assert [message["text"] for message in response.json()["messages"]] == [
            "A message",
            "B message",
        ]
