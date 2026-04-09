from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """
    Base interface for all model/system adapters.
    """

    @abstractmethod
    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Return model output for a given prompt."""
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        """Return adapter name."""
        raise NotImplementedError