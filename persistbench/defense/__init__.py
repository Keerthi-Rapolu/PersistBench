"""PersistBench defense plugin registry."""
from persistbench.defense.base import DefensePlugin, DefenseFlag, DefenseAction, MemoryUpdate
from persistbench.defense.no_defense import NoDefense
from persistbench.defense.pls import PromptLevelSanitization
from persistbench.defense.mw import MemoryWatermarking
from persistbench.defense.toh import ToolOutputHashing
from persistbench.defense.dev import DualExecutionVerification
from persistbench.defense.ps import ProvenanceScoring
from persistbench.defense.cd import CompositeDefense

REGISTRY: dict[str, type[DefensePlugin]] = {
    "NoDefense":                    NoDefense,
    "PromptLevelSanitization":      PromptLevelSanitization,
    "PLS":                          PromptLevelSanitization,
    "MemoryWatermarking":           MemoryWatermarking,
    "MW":                           MemoryWatermarking,
    "ToolOutputHashing":            ToolOutputHashing,
    "TOH":                          ToolOutputHashing,
    "DualExecutionVerification":    DualExecutionVerification,
    "DEV":                          DualExecutionVerification,
    "ProvenanceScoring":            ProvenanceScoring,
    "PS":                           ProvenanceScoring,
    "CompositeDefense":             CompositeDefense,
    "CD":                           CompositeDefense,
    "FragmentBlocker":              MemoryWatermarking,   # legacy alias
}


def load_defense(name: str, **kwargs) -> DefensePlugin:
    """Instantiate a defense by name. Raises ValueError for unknown names."""
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown defense: {name!r}. "
            f"Available: {sorted(REGISTRY)}"
        )
    return cls(**kwargs)


__all__ = [
    "DefensePlugin", "DefenseFlag", "DefenseAction", "MemoryUpdate",
    "NoDefense", "PromptLevelSanitization", "MemoryWatermarking",
    "ToolOutputHashing", "DualExecutionVerification",
    "ProvenanceScoring", "CompositeDefense",
    "REGISTRY", "load_defense",
]
