from typing import Optional, Type, Callable, Dict, Any, List
from springbootai.annotations.core import SpringAnnotation


class BeanDefinition:
    def __init__(
        self,
        bean_class: Type,
        bean_name: str,
        scope: str = "singleton",
        init_method: Optional[str] = None,
        destroy_method: Optional[str] = None,
        factory_method: Optional[Callable] = None,
        factory_class: Optional[Type] = None,
    ):
        self.bean_class = bean_class
        self.bean_name = bean_name
        self.scope = scope
        self.init_method = init_method
        self.destroy_method = destroy_method
        self.factory_method = factory_method
        self.factory_class = factory_class
        self.annotations: Dict[str, List[SpringAnnotation]] = {}
        self.dependencies: Dict[str, Type] = {}
        self.qualifiers: Dict[str, str] = {}
        self.dependency_required: Dict[str, bool] = {}
        self._instance: Optional[Any] = None
        self._initialized: bool = False
        self._destroyed: bool = False

    @property
    def is_singleton(self) -> bool:
        return self.scope == "singleton"

    @property
    def is_prototype(self) -> bool:
        return self.scope == "prototype"

    def get_instance(self) -> Optional[Any]:
        if self.is_singleton:
            return self._instance
        return None

    def set_instance(self, instance: Any) -> None:
        if self.is_singleton:
            self._instance = instance

    def mark_initialized(self) -> None:
        self._initialized = True

    def mark_destroyed(self) -> None:
        self._destroyed = True

    def add_annotation(self, annotation: SpringAnnotation) -> None:
        annotation_type = annotation._annotation_type
        if annotation_type not in self.annotations:
            self.annotations[annotation_type] = []
        self.annotations[annotation_type].append(annotation)

    def add_dependency(
        self,
        field_name: str,
        field_type: Type,
        qualifier: Optional[str] = None,
        required: bool = True,
    ) -> None:
        self.dependencies[field_name] = field_type
        self.dependency_required[field_name] = required
        if qualifier:
            self.qualifiers[field_name] = qualifier
