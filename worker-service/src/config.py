from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    aws_region: str = Field(default="us-east-1")
    aws_access_key_id: str = Field(default="test")
    aws_secret_access_key: str = Field(default="test")
    aws_endpoint_url: str = Field(default="http://localstack:4566")

    s3_bucket_raw: str = Field(default="raw-images-localdev")
    s3_bucket_processed: str = Field(default="processed-images-localdev")
    sqs_queue_url: str = Field(
        default=(
            "http://sqs.us-east-1.localhost.localstack.cloud:4566"
            "/000000000000/image-processing-queue-localdev"
        )
    )

    sqs_wait_time_seconds: int = Field(default=20)
    sqs_max_messages: int = Field(default=10)
    sqs_visibility_timeout: int = Field(default=60)

    max_retries: int = Field(default=3)
    retry_base_delay: float = Field(default=1.0)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
