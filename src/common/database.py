"""Database connection utilities.

AWS Credentials:
    Athena client uses boto3, which automatically discovers credentials in this order:
    1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    2. AWS_PROFILE environment variable (uses SSO cached credentials)
    3. SSO cached credentials in ~/.aws/credentials (after aws sso login)
    4. IAM instance role (if running on AWS compute)

    Recommended: Use AWS SSO with boto3 credential discovery

PostgreSQL Connections:
    Credentials are loaded from Config (environment variables or config.yaml)
    Always use parameterized queries to prevent SQL injection.
"""

from typing import Optional

import boto3
import psycopg2
from psycopg2.extensions import connection as PgConnection

from .config import config


class AthenaClient:
    """Client for AWS Athena queries.

    Credentials are auto-discovered by boto3:
    - Use AWS_PROFILE environment variable for SSO
    - Or rely on cached SSO credentials after aws sso login

    Example:
        export AWS_PROFILE=company-aws-profile
        client = AthenaClient()
    """

    def __init__(self, workgroup: str = None):
        """Initialize Athena client.

        Args:
            workgroup: Athena workgroup name. If None, uses lab workgroup from config.

        Raises:
            botocore.exceptions.ClientError: If AWS credentials not found or invalid.
        """
        self.workgroup = workgroup or config.athena_lab_workgroup
        # boto3 automatically detects credentials from SSO or environment
        self.client = boto3.client("athena", region_name=config.aws_region)
        self.s3_output = f"s3://{config.s3_bucket}/athena/results/"

    def execute_query(self, query: str, database: str = None) -> str:
        """Execute Athena query and return execution ID.

        Args:
            query: SQL query string (use parameterized queries where possible)
            database: Glue database name. If None, uses default from config.

        Returns:
            Query execution ID for tracking.

        Raises:
            botocore.exceptions.ClientError: If query fails to start.
        """
        database = database or config.glue_database

        response = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": database},
            ResultConfiguration={"OutputLocation": self.s3_output},
            WorkGroup=self.workgroup,
        )

        return response["QueryExecutionId"]

    def get_query_results(self, execution_id: str):
        """Get query results.

        Args:
            execution_id: The query execution ID returned by execute_query.

        Returns:
            ResultSet with query results.

        Raises:
            botocore.exceptions.WaiterError: If query fails or times out.
        """
        # Wait for query to complete
        waiter = self.client.get_waiter("query_succeeded")
        waiter.wait(QueryExecutionId=execution_id)

        # Get results
        response = self.client.get_query_results(QueryExecutionId=execution_id)
        return response["ResultSet"]


class PostgresClient:
    """Client for PostgreSQL with pgvector support.

    Manages connection pooling and provides context manager interface.
    Always uses parameterized queries to prevent SQL injection.

    Example:
        client = PostgresClient()
        with client as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM market_memory WHERE embedding <-> %s < 0.5",
                          (embedding_vector,))
    """

    def __init__(self):
        """Initialize PostgreSQL connection manager.

        Credentials loaded from Config (environment or config.yaml).
        Connection is lazy-initialized on first use.
        """
        self._conn: Optional[PgConnection] = None

    def connect(self) -> PgConnection:
        """Create or return existing database connection.

        Connection is automatically recreated if closed.

        Returns:
            psycopg2 connection object.

        Raises:
            psycopg2.OperationalError: If connection fails.
        """
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=config.postgres_host,
                port=config.postgres_port,
                database=config.postgres_db,
                user=config.postgres_user,
                password=config.postgres_password,
            )
        return self._conn

    def close(self):
        """Close database connection gracefully."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def __enter__(self):
        """Context manager entry - returns open connection."""
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - closes connection."""
        self.close()
