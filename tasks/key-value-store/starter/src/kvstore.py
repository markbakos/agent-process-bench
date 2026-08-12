class Store:
    def __init__(self, *, case_sensitive: bool = True) -> None:
        self.case_sensitive = case_sensitive
        self._values: dict[str, object] = {}

    def _key(self, key: str) -> str:
        return key if self.case_sensitive else key.casefold()

    def set(self, key: str, value: object) -> None:
        self._values[self._key(key)] = value

    def get(self, key: str) -> object | None:
        return self._values.get(self._key(key))

    def delete(self, key: str) -> bool:
        return self._values.pop(self._key(key), None) is not None

