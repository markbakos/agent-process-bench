class Store:
    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        self._values[key] = value

    def get(self, key: str) -> object | None:
        return self._values.get(key)
