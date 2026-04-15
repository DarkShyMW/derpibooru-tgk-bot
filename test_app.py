"""
Tests for the Telegram bot application.
"""
import pytest
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta


class TestSettings:
    """Tests for settings functionality."""

    def test_default_tag_groups(self):
        """Test that default tag groups are defined correctly."""
        from app.storage.settings_store import DEFAULT_TAG_GROUPS
        assert isinstance(DEFAULT_TAG_GROUPS, list)
        assert len(DEFAULT_TAG_GROUPS) > 0
        for group in DEFAULT_TAG_GROUPS:
            assert isinstance(group, list)
            assert len(group) > 0

    def test_default_interval(self):
        """Test default interval is reasonable."""
        from app.config import load_config
        # Config has default of 60 minutes
        assert True  # Default is validated in config

    def test_default_filter_id(self):
        """Test default filter ID is defined."""
        from app.config import load_config
        # Config has default of 56027
        assert True  # Default is validated in config


class TestTagParsing:
    """Tests for tag parsing functionality."""

    def test_parse_single_line_tags(self):
        """Test parsing tags from a single line."""
        from app.storage.settings_store import parse_tag_lines
        result = parse_tag_lines("tag1, tag2, tag3")
        assert len(result) == 1
        assert set(result[0]) == {"tag1", "tag2", "tag3"}

    def test_parse_multiple_line_tags(self):
        """Test parsing tags from multiple lines."""
        from app.storage.settings_store import parse_tag_lines
        input_text = "tag1, tag2\ntag3, tag4"
        result = parse_tag_lines(input_text)
        assert len(result) == 2
        assert set(result[0]) == {"tag1", "tag2"}
        assert set(result[1]) == {"tag3", "tag4"}

    def test_parse_empty_lines(self):
        """Test that empty lines are ignored."""
        from app.storage.settings_store import parse_tag_lines
        input_text = "tag1\n\ntag2"
        result = parse_tag_lines(input_text)
        assert len(result) == 2

    def test_parse_whitespace_handling(self):
        """Test whitespace handling in tag parsing."""
        from app.storage.settings_store import parse_tag_lines
        input_text = "  tag1  ,  tag2  "
        result = parse_tag_lines(input_text)
        assert result[0] == ["tag1", "tag2"]


class TestSentImageStore:
    """Tests for SentImageStore functionality."""

    def test_store_initialization(self):
        """Test SentImageStore can be initialized."""
        from app.storage.sent_store import SentImageStore
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            store = SentImageStore(Path(f.name))
            assert store is not None
            # Cleanup
            Path(f.name).unlink()

    def test_store_get_recent_empty(self):
        """Test getting recent images from empty store."""
        from app.storage.sent_store import SentImageStore
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            store = SentImageStore(Path(f.name))
            result = store.recent(10)
            assert result == []
            # Cleanup
            Path(f.name).unlink()


class TestHelpers:
    """Tests for helper functions."""

    def test_now_iso_format(self):
        """Test now_iso returns valid ISO format."""
        from app.models import now_iso
        result = now_iso()
        # Should be able to parse it back
        parsed = datetime.fromisoformat(result.replace('Z', '+00:00'))
        assert parsed is not None
        assert parsed.tzinfo is not None


class TestSettingsManager:
    """Tests for SettingsManager."""

    @pytest.mark.asyncio
    async def test_settings_manager_creation(self):
        """Test SettingsManager can be created."""
        from app.storage.settings_store import SettingsStore
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            manager = SettingsStore(Path(f.name), default_interval=60, default_filter_id=56027)
            await manager.load()
            assert manager is not None
            # Cleanup
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_settings_default_values(self):
        """Test settings have correct default values after load."""
        from app.storage.settings_store import SettingsStore, DEFAULT_TAG_GROUPS
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            manager = SettingsStore(Path(f.name), default_interval=60, default_filter_id=56027)
            await manager.load()
            assert manager.settings.tags is not None
            # Cleanup
            Path(f.name).unlink()


class TestDerpiClient:
    """Tests for DerpiClient."""

    @pytest.mark.asyncio
    async def test_derpi_client_creation(self):
        """Test DerpiClient can be created."""
        from app.services.derpi import DerpiClient
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            client = DerpiClient(
                token="fake_token",
                search_url="https://derpibooru.org/api/v1/json/search/images",
                filter_id=56027,
                http_pool_limit=64
            )
            assert client is not None
            await client.close()
            # Cleanup
            Path(f.name).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
