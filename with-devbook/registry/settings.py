from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    # region Database
    database_path: Path = Path("projects.sqlite3")
    # endregion

    # region GitLab
    gitlab_url: HttpUrl = HttpUrl("https://gitlab.com")
    gitlab_token: SecretStr | None = None
    gitlab_timeout_seconds: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    # endregion

    @field_validator("gitlab_url")
    @classmethod
    def validate_gitlab_base_url(cls, url: HttpUrl) -> HttpUrl:
        if (
            url.username
            or url.password
            or url.query is not None
            or url.fragment is not None
        ):
            raise ValueError(
                "GitLab base URL cannot contain credentials, query or fragment"
            )
        return url

    @property
    def database_url(self) -> URL:
        return URL.create("sqlite+aiosqlite", database=str(self.database_path))
