"""Tests for common utilities."""

import os
import tempfile

import pytest

from src.common.config import Config

pytestmark = pytest.mark.unit


def test_config_initialization():
    """Test configuration initialization."""
    config = Config()
    assert config is not None


def test_config_defaults():
    """Test default configuration values."""
    config = Config()

    # Test default values
    assert config.get("nonexistent.key", "default") == "default"
    assert isinstance(config.aws_region, str)


def test_config_from_file():
    """Test loading configuration from file."""
    # Create temporary config file
    config_data = """
    aws:
      region: eu-west-2
      s3_bucket: test-bucket

    postgres:
      host: testhost
      port: 5433
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_data)
        config_path = f.name

    try:
        config = Config(config_path=config_path)
        assert config.get("aws.region") == "eu-west-2"
        assert config.get("aws.s3_bucket") == "test-bucket"
        assert config.get("postgres.host") == "testhost"
        assert config.get("postgres.port") == 5433
    finally:
        os.unlink(config_path)


def test_config_nested_access():
    """Test nested configuration access."""
    config_data = """
    level1:
      level2:
        level3: value
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_data)
        config_path = f.name

    try:
        config = Config(config_path=config_path)
        assert config.get("level1.level2.level3") == "value"
        assert config.get("level1.level2.nonexistent", "default") == "default"
    finally:
        os.unlink(config_path)


def test_config_data_pipeline_section():
    """Test data pipeline configuration section."""
    config_data = """
    data:
      provider: yfinance
      universe: ftse_100
      schedule_cron: "0 18 * * 1-5"
      features:
        technicals: true
        sentiment: true
        fundamentals: true
      retry_attempts: 3
      retry_delay_seconds: 60
      overwrite_existing: true
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_data)
        config_path = f.name

    try:
        config = Config(config_path=config_path)
        assert config.get("data.provider") == "yfinance"
        assert config.get("data.universe") == "ftse_100"
        assert config.get("data.features.technicals") is True
        assert config.get("data.features.sentiment") is True
        assert config.get("data.features.fundamentals") is True
        assert config.get("data.retry_attempts") == 3
        assert config.get("data.retry_delay_seconds") == 60
        assert config.get("data.overwrite_existing") is True
        assert config.get("data.schedule_cron") == "0 18 * * 1-5"
    finally:
        os.unlink(config_path)


def test_config_validate_rejects_empty_string():
    """Test that validate() rejects empty strings for required fields.

    Ensures that both None and empty string values are caught
    by the validation logic.
    """
    config_data = """
    aws:
      region: ""
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_data)
        config_path = f.name

    try:
        # Create config without validation first
        config = Config(config_path=config_path, validate=False)

        # Now call validate and expect it to raise ValueError
        with pytest.raises(ValueError, match="Missing required configuration fields"):
            config.validate()
    finally:
        os.unlink(config_path)
