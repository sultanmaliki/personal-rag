import types

import pytest

from app.store import conversations as conv
from app.store import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own throwaway SQLite file -- never touches the
    real data/conversations.db."""
    fake_config = types.SimpleNamespace(conversations_db=tmp_path / "test.db")
    monkeypatch.setattr(db, "config", fake_config)
    db.init_db()


def test_create_and_list_conversation():
    conv_id = conv.create_conversation("What language is QueryCraft-AI built with?")
    summaries = conv.list_conversations()
    assert len(summaries) == 1
    assert summaries[0].id == conv_id
    assert summaries[0].title == "What language is QueryCraft-AI built with?"


def test_auto_title_truncates_long_first_message():
    long_q = "x" * 200
    conv_id = conv.create_conversation(long_q)
    summary = conv.list_conversations()[0]
    assert summary.id == conv_id
    assert len(summary.title) <= conv.MAX_AUTO_TITLE_LENGTH
    assert summary.title.endswith("…")


def test_new_chat_with_no_first_message_gets_generic_title():
    conv.create_conversation()
    assert conv.list_conversations()[0].title == "New chat"


def test_add_message_and_get_messages_round_trip():
    conv_id = conv.create_conversation("hello")
    conv.add_message(conv_id, "user", "hello")
    conv.add_message(
        conv_id, "assistant", "hi there",
        thinking="considering how to greet", sources=[{"label": "a", "ref": "b"}],
    )
    messages = conv.get_messages(conv_id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].thinking == "considering how to greet"
    assert messages[1].sources == [{"label": "a", "ref": "b"}]
    assert messages[0].thinking is None
    assert messages[0].sources is None


def test_add_message_bumps_conversation_updated_at():
    conv_id = conv.create_conversation("hello")
    before = conv.list_conversations()[0].updated_at
    conv.add_message(conv_id, "user", "another message")
    after = conv.list_conversations()[0].updated_at
    assert after >= before


def test_delete_conversation_cascades_messages():
    conv_id = conv.create_conversation("hello")
    conv.add_message(conv_id, "user", "hello")
    conv.delete_conversation(conv_id)
    assert conv.list_conversations() == []
    assert conv.get_messages(conv_id) == []
    assert conv.conversation_exists(conv_id) is False


def test_rename_conversation():
    conv_id = conv.create_conversation("hello")
    conv.rename_conversation(conv_id, "  My renamed chat  ")
    assert conv.list_conversations()[0].title == "My renamed chat"


def test_maybe_set_title_from_first_message_only_applies_once():
    conv_id = conv.create_conversation()  # generic "New chat" title
    conv.add_message(conv_id, "user", "what is querycraft-ai?")
    conv.maybe_set_title_from_first_message(conv_id, "what is querycraft-ai?")
    assert conv.list_conversations()[0].title == "what is querycraft-ai?"

    conv.add_message(conv_id, "user", "and what about setbeat?")
    conv.maybe_set_title_from_first_message(conv_id, "and what about setbeat?")
    # second message must NOT overwrite the title set from the first
    assert conv.list_conversations()[0].title == "what is querycraft-ai?"


def test_list_conversations_orders_most_recently_updated_first():
    first = conv.create_conversation("first")
    second = conv.create_conversation("second")
    conv.add_message(first, "user", "bump the first conversation")
    ids_in_order = [c.id for c in conv.list_conversations()]
    assert ids_in_order[0] == first
    assert ids_in_order[1] == second
