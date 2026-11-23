class DomainError(Exception):
    """An expected failure of a registry operation."""


class ProjectNotFoundError(DomainError):
    """The project does not exist in the registry."""


class DuplicateProjectError(DomainError):
    """The GitLab project ID is already registered."""


class ProjectChangedError(DomainError):
    """The project was updated concurrently with GitLab synchronization."""
