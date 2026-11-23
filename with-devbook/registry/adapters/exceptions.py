class HTTPAdapterError(Exception):
    """GitLab could not provide usable project metadata."""


class HTTPTimeoutError(HTTPAdapterError):
    """The GitLab request exceeded its time budget."""


class GitLabConfigurationError(HTTPAdapterError):
    """GitLab credentials are missing."""
