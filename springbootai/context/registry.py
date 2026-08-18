from typing import Dict, Type, Any, Optional


class BeanRegistry:
    _instance: Optional['BeanRegistry'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._beans: Dict[str, Any] = {}
        self._types: Dict[Type, str] = {}
        self._initialized = True

    def register(self, name: str, bean: Any) -> None:
        self._beans[name] = bean
        self._types[type(bean)] = name

    def get(self, name: str) -> Any:
        return self._beans.get(name)

    def get_by_type(self, bean_type: Type) -> Any:
        if bean_type in self._types:
            return self._beans[self._types[bean_type]]
        for bean in self._beans.values():
            if isinstance(bean, bean_type):
                return bean
        return None

    def contains(self, name: str) -> bool:
        return name in self._beans

    def contains_type(self, bean_type: Type) -> bool:
        return bean_type in self._types

    def unregister(self, name: str) -> None:
        if name in self._beans:
            bean = self._beans[name]
            del self._types[type(bean)]
            del self._beans[name]

    def clear(self) -> None:
        self._beans.clear()
        self._types.clear()

    def get_all(self) -> Dict[str, Any]:
        return dict(self._beans)

    def get_names(self) -> list:
        return list(self._beans.keys())

    def get_count(self) -> int:
        return len(self._beans)
