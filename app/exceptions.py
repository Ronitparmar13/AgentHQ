"""Domain-level errors shared across application layers."""


class ConfigurationError(RuntimeError):
    def __init__(self, variable_name: str) -> None:
        self.variable_name = variable_name
        super().__init__(f"Missing or invalid configuration: {variable_name}")


class LLMProviderError(RuntimeError):
    def __init__(self, provider: str, category: str, message: str) -> None:
        self.provider = provider
        self.category = category
        super().__init__(message)


class InvalidTransitionError(ValueError):
    def __init__(self, resource_id: str, current: str, target: str) -> None:
        self.resource_id = resource_id
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot transition {resource_id} from '{current}' to '{target}'."
        )


class WorkspaceBoundaryError(PermissionError):
    pass


class NotFoundError(LookupError):
    pass
