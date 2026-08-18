from typing import List, Type, Any
import importlib
import pkgutil
from springbootai.annotations.core import (
    Component,
    Service,
    Repository,
    Controller,
    RestController,
    Configuration,
    ControllerAdvice,
    ConfigurationProperties,
    get_spring_annotations,
)


class ComponentScanner:
    def __init__(self, application_context: Any):
        self.application_context = application_context
        self._scanned_classes: set = set()

    def scan(self, base_packages: List[str]) -> List[Type]:
        components: List[Type] = []
        for package_name in base_packages:
            components.extend(self._scan_package(package_name))
        return components

    def scan_classes(self, base_packages: List[str]) -> List[Type]:
        """Import packages and return all declared classes once.

        Cloud integrations such as Feign are interface-like declarations and
        deliberately are not IoC components themselves, so they need a
        separate class scan from the component scan.
        """
        classes: List[Type] = []
        for package_name in base_packages:
            classes.extend(self._scan_package_classes(package_name))
        return classes

    def _scan_package_classes(self, package_name: str) -> List[Type]:
        classes: List[Type] = []
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            return classes
        if hasattr(package, '__path__'):
            for _, module_name, is_pkg in pkgutil.walk_packages(package.__path__, package_name + '.'):
                if is_pkg:
                    classes.extend(self._scan_package_classes(module_name))
                else:
                    try:
                        module = importlib.import_module(module_name)
                    except ImportError:
                        continue
                    classes.extend(
                        obj for obj in vars(module).values()
                        if isinstance(obj, type) and obj.__module__ == module.__name__
                    )
        return classes

    def _scan_package(self, package_name: str) -> List[Type]:
        components: List[Type] = []
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            return components

        if hasattr(package, '__path__'):
            for _, module_name, is_pkg in pkgutil.walk_packages(package.__path__, package_name + '.'):
                if is_pkg:
                    components.extend(self._scan_package(module_name))
                else:
                    try:
                        module = importlib.import_module(module_name)
                        components.extend(self._find_components_in_module(module))
                    except ImportError:
                        continue
        return components

    def _find_components_in_module(self, module: Any) -> List[Type]:
        components: List[Type] = []
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and obj not in self._scanned_classes:
                if self._is_component(obj):
                    self._scanned_classes.add(obj)
                    components.append(obj)
        return components

    def _is_component(self, cls: Type) -> bool:
        annotations = get_spring_annotations(cls)
        component_annotations = (
            Component,
            Service,
            Repository,
            Controller,
            RestController,
            Configuration,
            ControllerAdvice,
            ConfigurationProperties,
        )
        for annotation in annotations:
            if isinstance(annotation, component_annotations):
                return True
        return False
