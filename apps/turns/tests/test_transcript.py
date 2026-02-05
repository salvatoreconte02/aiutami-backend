"""Tests for session transcript management."""
import json
import unittest
from unittest.mock import patch, MagicMock
from django.core.cache import cache
from django.test import TestCase


class TestSessionTranscript(TestCase):
    """Test transcript append functionality."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_append_human_entry(self):
        """Test appending human turn to transcript."""
        from apps.turns.ws_consumer import _append_to_session_transcript

        session_id = "test-session-123"
        entry = {
            "type": "human",
            "user_id": 456,
            "speaker_name": "Mario Rossi",
            "text": "Penso che dovremmo procedere",
            "timestamp": "2026-01-27T10:30:00Z"
        }

        _append_to_session_transcript(session_id, entry)

        key = f"session:{session_id}:transcript"
        items = cache.get(key)
        self.assertIsNotNone(items)
        self.assertEqual(len(items), 1)
        self.assertEqual(json.loads(items[0])["type"], "human")

    def test_append_ai_entry(self):
        """Test appending AI turn to transcript."""
        from apps.turns.ws_consumer import _append_to_session_transcript

        session_id = "test-session-123"
        entry = {
            "type": "ai",
            "text": "Grazie per il contributo",
            "trigger": "llm_decision",
            "timestamp": "2026-01-27T10:31:00Z"
        }

        _append_to_session_transcript(session_id, entry)

        key = f"session:{session_id}:transcript"
        items = cache.get(key)
        self.assertIsNotNone(items)
        parsed = json.loads(items[0])
        self.assertEqual(parsed["type"], "ai")
        self.assertEqual(parsed["trigger"], "llm_decision")

    def test_append_multiple_entries(self):
        """Test appending multiple entries maintains order."""
        from apps.turns.ws_consumer import _append_to_session_transcript

        session_id = "test-session-123"

        _append_to_session_transcript(session_id, {"type": "human", "text": "First"})
        _append_to_session_transcript(session_id, {"type": "ai", "text": "Second"})
        _append_to_session_transcript(session_id, {"type": "human", "text": "Third"})

        key = f"session:{session_id}:transcript"
        items = cache.get(key)

        self.assertEqual(len(items), 3)
        self.assertEqual(json.loads(items[0])["text"], "First")
        self.assertEqual(json.loads(items[1])["text"], "Second")
        self.assertEqual(json.loads(items[2])["text"], "Third")
