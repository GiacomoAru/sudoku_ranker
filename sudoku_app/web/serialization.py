from pathlib import Path

import numpy as np


def to_jsonable(value):
    """Converte i tipi interni del solver in una struttura JSON pura."""
    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (set, frozenset)):
        return sorted(to_jsonable(item) for item in value)

    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]

    if isinstance(value, list):
        return [to_jsonable(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): to_jsonable(item)
            for key, item in value.items()
        }

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise TypeError(
        f"Il tipo {type(value).__name__} non è serializzabile in JSON."
    )
