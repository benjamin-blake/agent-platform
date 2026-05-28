"""Configuration management for the trading system.

Credential Resolution:
    AWS credentials are resolved automatically in the following order:
    1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    2. AWS_PROFILE environment variable (uses SSO cached credentials)
    3. SSO cached credentials in ~/.aws/credentials
    4. IAM instance role (if running on AWS compute)

    Recommended: Use AWS SSO (aws sso login --profile <profile-name>)

Example configuration:
    # For SSO with a specific profile
    export AWS_PROFILE=company-aws-profile

    # Then boto3 will automatically use SSO credentials
"""

import logging
import os
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


class Config:
    """Central configuration manager.

    Loads configuration from YAML file with environment variable overrides.
    Supports AWS SSO credential discovery via boto3.
    """

    def __init__(self, config_path: str = None, validate: bool = False):
        """Initialize configuration.

        Args:
            config_path: Path to config.yaml. If None, uses TRADING_CONFIG env var
                        or default path relative to project root.
            validate: If True, call validate() after loading config.
        """
        if config_path is None:
            # Resolve config path using the following priority:
            # 1. TRADING_CONFIG env var (explicit override)
            # 2. ENVIRONMENT env var: 'company' -> config.company.yaml,
            #                         'personal' -> config.personal.yaml
            # 3. Fall back to config.yaml (base / Lambda defaults)
            explicit = os.environ.get("TRADING_CONFIG")
            if explicit:
                config_path = explicit
            else:
                env = os.environ.get("ENVIRONMENT", "")
                base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
                env_map = {
                    "company": "config.company.yaml",
                    "personal": "config.personal.yaml",
                }
                filename = env_map.get(env, "config.yaml")
                config_path = os.path.join(base_dir, "config", filename)

        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._aws_profile = os.environ.get("AWS_PROFILE")
        self._load_config()
        if validate:
            self.validate()

    def _load_config(self):
        """Load configuration from YAML file.

        If config file doesn't exist, logs a warning and uses an empty dict.
        This allows tests and CI environments to proceed without a config file.
        Explicit validation errors (via validate()) will catch missing config.
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path} — using empty config")
            self._config = {}
            return

        with open(self.config_path, "r") as f:
            self._config = yaml.safe_load(f) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-separated key.

        Args:
            key: Dot-separated key (e.g., 'aws.region')
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    @property
    def aws_profile(self) -> str:
        """Get AWS SSO profile name.

        Used for boto3 credential resolution. Set via AWS_PROFILE env var.
        Example: 'company-aws-profile' for SSO profile
        """
        return self._aws_profile

    @property
    def aws_region(self) -> str:
        """Get AWS region for API calls.

        Resolved from config.yaml or AWS_REGION environment variable.
        """
        return self.get("aws.region", os.environ.get("AWS_REGION", "eu-west-2"))

    @property
    def s3_bucket(self) -> str:
        """Get S3 data lake bucket name.

        Resolved from config.yaml or S3_BUCKET environment variable.
        Required for data lake operations.
        """
        return self.get("aws.s3_bucket", os.environ.get("S3_BUCKET"))

    @property
    def glue_database(self) -> str:
        """Get Glue catalog database name."""
        return self.get("aws.glue_database", "trading_formulas_db")

    @property
    def athena_lab_workgroup(self) -> str:
        """Get Athena workgroup for lab (research) queries."""
        return self.get("aws.athena_lab_workgroup", "agent-platform-lab")

    @property
    def athena_prod_workgroup(self) -> str:
        """Get Athena workgroup for production queries."""
        return self.get("aws.athena_prod_workgroup", "agent-platform-production")

    @property
    def postgres_host(self) -> str:
        """Get PostgreSQL host address."""
        return self.get("postgres.host", os.environ.get("POSTGRES_HOST", "localhost"))

    @property
    def postgres_port(self) -> int:
        """Get PostgreSQL port number."""
        return self.get("postgres.port", int(os.environ.get("POSTGRES_PORT", "5432")))

    @property
    def postgres_db(self) -> str:
        """Get PostgreSQL database name."""
        return self.get("postgres.database", os.environ.get("POSTGRES_DB", "trading"))

    @property
    def postgres_user(self) -> str:
        """Get PostgreSQL user name."""
        return self.get("postgres.user", os.environ.get("POSTGRES_USER", "trading"))

    @property
    def postgres_password(self) -> str:
        """Get PostgreSQL password.

        Loaded from POSTGRES_PASSWORD environment variable.
        Should be set at runtime, never committed to repository.
        """
        return os.environ.get("POSTGRES_PASSWORD", self.get("postgres.password", ""))

    def validate(self) -> None:
        """Validate required configuration fields based on environment.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        env = os.environ.get("TRADING_ENVIRONMENT", "")

        # Common required fields
        required = ["aws.region"]

        # Environment-specific requirements
        if env == "company":
            required.extend(
                [
                    "aws.glue_database",
                    "aws.athena_lab_workgroup",
                    "aws.s3_data_lake_bucket",
                ]
            )
        elif env == "personal":
            required.extend(
                [
                    "postgres.host",
                    "postgres.database",
                ]
            )

        missing = []
        for key in required:
            if not self.get(key):
                missing.append(key)

        if missing:
            raise ValueError(
                f"Missing required configuration fields for environment '{env}': {', '.join(missing)}\n"
                f"Config file: {self.config_path}"
            )


# Global configuration instance
config = Config()
