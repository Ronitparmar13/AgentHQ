"""Provider-neutral contract for synchronous language-model completion."""

from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """A provider that returns raw text for a prompt and model identifier."""

    @abstractmethod
    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        """Return a raw completion or raise ``LLMProviderError`` on failure."""
        raise NotImplementedError
