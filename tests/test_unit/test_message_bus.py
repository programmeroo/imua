"""
Unit tests for the Message Bus service layer.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from app.services.message_bus import send_message, get_messages, _resolve_recipients


class TestResolveRecipients:
    """Test addressing mode resolution."""

    def test_single_recipient(self, mock_conn):
        result = _resolve_recipients(mock_conn, "svy")
        assert result == ["svy"]

    def test_broadcast_all(self, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(_asdict=lambda: {"name": "svy"}),
            MagicMock(_asdict=lambda: {"name": "akm"}),
            MagicMock(_asdict=lambda: {"name": "slk"}),
        ]
        result = _resolve_recipients(mock_conn, "all")
        assert result == ["svy", "akm", "slk"]

    def test_comma_separated(self, mock_conn):
        result = _resolve_recipients(mock_conn, "svy, slk")
        assert result == ["svy", "slk"]

    def test_role_based(self, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("svy",),
            ("akm",),
        ]
        result = _resolve_recipients(mock_conn, "role:developer")
        assert result == ["svy", "akm"]


class TestSendMessage:
    """Test sending messages through the bus."""

    def test_send_direct_message(self, mock_conn):
        mock_conn.execute.return_value.one.return_value = MagicMock(
            _asdict=lambda: {"id": 1, "sender": "akm", "recipient": "svy",
                             "msg_type": "direct", "body": "Hey!", "status": "pending",
                             "created_at": datetime.utcnow()}
        )
        mock_conn.execute.return_value.inserted_primary_key = [1]

        with patch("app.services.message_bus._push_via_ws"):
            result = send_message(mock_conn, sender="akm", to="svy",
                                  body="Hey!")

        assert result["sender"] == "akm"
        assert result["recipient"] == "svy"
        assert result["body"] == "Hey!"

    def test_broadcast_message(self, mock_conn):
        mock_conn.execute.return_value.one.return_value = MagicMock(
            _asdict=lambda: {"id": 2, "sender": "akm", "recipient": "all",
                             "msg_type": "broadcast", "body": "Attention!",
                             "status": "pending", "created_at": datetime.utcnow()}
        )
        mock_conn.execute.return_value.inserted_primary_key = [2]

        with patch("app.services.message_bus._resolve_recipients") as mock_resolve:
            mock_resolve.return_value = ["svy"]
            with patch("app.services.message_bus._push_via_ws"):
                result = send_message(mock_conn, sender="akm", to="all",
                                      body="Attention!")

        assert result["recipient"] == "all" or result["msg_type"] == "broadcast"


class TestGetMessages:
    """Test retrieving messages."""

    def test_get_messages_for_agent(self, mock_conn):
        now = datetime.utcnow()
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(_asdict=lambda: {"id": 1, "sender": "akm",
                                       "recipient": "svy", "body": "Hi",
                                       "status": "pending",
                                       "created_at": now - timedelta(minutes=5)}),
        ]

        msgs = get_messages(mock_conn, "svy")

        assert len(msgs) == 1
        assert msgs[0]["sender"] == "akm"

    def test_get_messages_with_since_filter(self, mock_conn):
        now = datetime.utcnow()
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(_asdict=lambda: {"id": 1, "sender": "akm",
                                       "recipient": "svy", "body": "Old",
                                       "status": "pending",
                                       "created_at": now - timedelta(hours=2)}),
            MagicMock(_asdict=lambda: {"id": 2, "sender": "slk",
                                       "recipient": "svy", "body": "New",
                                       "status": "pending",
                                       "created_at": now}),
        ]

        since = (now - timedelta(hours=1)).isoformat()
        msgs = get_messages(mock_conn, "svy", since=since)

        assert len(msgs) == 1
        assert msgs[0]["body"] == "New"
