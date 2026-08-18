"""
Spring HATEOAS 超媒体链接（对齐 Spring HATEOAS）

为 RESTful API 提供超媒体链接（HATEOAS = Hypermedia As The Engine Of Application State），
让客户端可以通过响应中的链接动态发现可用操作，而无需硬编码 URL。

功能：
- Link：超媒体链接（href, rel, method）
- EntityModel：单个实体 + 链接
- CollectionModel：集合 + 链接
- PagedModel：分页集合 + 链接（含 first/last/next/prev）
- WebMvcLinkBuilder：链接构建辅助工具

与 Java Spring HATEOAS 的差异：
- Java 使用 RepresentationModel 泛型基类，Python 使用 dataclass
- Java 有 Affordances（描述链接支持的操作），Python 版本简化为 method 字段
- Java 支持 HAL/HAL-FORMS/Collection+JSON 等媒体类型，Python 版本使用标准 JSON
- Java 使用 ControllerLinkBuilder.methodOn() 生成链接，Python 版本使用显式路径

Usage::

    from springbootai.web.hateoas import Link, EntityModel, CollectionModel, PagedModel

    # 1. 单个实体的超媒体响应
    user = {'id': 1, 'name': 'Alice'}
    model = EntityModel.of(user)
    model.add(Link.of('/api/users/1', 'self'))
    model.add(Link.of('/api/users/1', 'update', method='PUT'))
    model.add(Link.of('/api/users/1', 'delete', method='DELETE'))
    # 返回 JSON: {"id": 1, "name": "Alice", "_links": {"self": {"href": "/api/users/1"}, ...}}

    # 2. 集合的超媒体响应
    users = [{'id': 1}, {'id': 2}]
    collection = CollectionModel.of(users)
    collection.add(Link.of('/api/users', 'self'))

    # 3. 分页的超媒体响应（自动添加 first/last/next/prev 链接）
    paged = PagedModel.of(users, page=0, size=20, total=100, base_path='/api/users')
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Link:
    """超媒体链接

    对齐 Spring HATEOAS 的 ``org.springframework.hateoas.Link``。

    Args:
        href: 链接 URL
        rel: 关系类型（self, update, delete, first, last, next, prev 等）
        method: HTTP 方法（GET/POST/PUT/DELETE/PATCH），可选
        title: 链接标题（用于文档），可选
        type: 媒体类型（如 application/json），可选
    """

    href: str
    rel: str = 'self'
    method: Optional[str] = None
    title: Optional[str] = None
    type: Optional[str] = None

    @staticmethod
    def of(href: str, rel: str = 'self', method: Optional[str] = None) -> 'Link':
        """创建链接的便捷方法。"""
        return Link(href=href, rel=rel, method=method)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。

        返回格式对齐 HAL 标准::

            {"href": "/api/users/1", "method": "PUT"}
        """
        result: Dict[str, Any] = {'href': self.href}
        if self.method:
            result['method'] = self.method
        if self.title:
            result['title'] = self.title
        if self.type:
            result['type'] = self.type
        return result


class RepresentationModel:
    """超媒体表示模型基类

    包含一组 ``Link``，可序列化为带 ``_links`` 字段的 JSON。
    """

    def __init__(self):
        self._links: List[Link] = []

    def add(self, link: Link) -> 'RepresentationModel':
        """添加链接（支持链式调用）。"""
        self._links.append(link)
        return self

    def add_all(self, links: List[Link]) -> 'RepresentationModel':
        """添加多个链接。"""
        self._links.extend(links)
        return self

    def get_links(self) -> Dict[str, Dict[str, Any]]:
        """获取所有链接，按 rel 分组。

        Returns:
            {rel: link_dict} 格式的字典
        """
        result: Dict[str, Dict[str, Any]] = {}
        for link in self._links:
            result[link.rel] = link.to_dict()
        return result

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（含 _links 字段）。"""
        links = self.get_links()
        if links:
            return {'_links': links}
        return {}


class EntityModel(RepresentationModel):
    """实体模型

    包装单个实体 + 链接。

    Args:
        entity: 实体对象（dict 或有 __dict__ 的对象）
    """

    def __init__(self, entity: Any):
        super().__init__()
        self.entity = entity

    @staticmethod
    def of(entity: Any) -> 'EntityModel':
        """创建 EntityModel。"""
        return EntityModel(entity)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。

        返回格式::

            {"id": 1, "name": "Alice", "_links": {...}}
        """
        from springbootai.data.rest import _to_dict
        result = _to_dict(self.entity) if not isinstance(self.entity, dict) else dict(self.entity)
        links = self.get_links()
        if links:
            result['_links'] = links
        return result


class CollectionModel(RepresentationModel):
    """集合模型

    包装实体集合 + 链接。

    Args:
        items: 实体列表
    """

    def __init__(self, items: List[Any]):
        super().__init__()
        self.items = items

    @staticmethod
    def of(items: List[Any]) -> 'CollectionModel':
        """创建 CollectionModel。"""
        return CollectionModel(items)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。

        返回格式::

            {"_embedded": {...}, "_links": {...}}
        """
        from springbootai.data.rest import _to_dict
        content = [
            _to_dict(item) if not isinstance(item, dict) else dict(item)
            for item in self.items
        ]
        result: Dict[str, Any] = {'_embedded': {'items': content}}
        links = self.get_links()
        if links:
            result['_links'] = links
        return result


class PagedModel(RepresentationModel):
    """分页模型

    包装分页集合 + 链接（自动添加 first/last/next/prev）。

    Args:
        items: 当前页的实体列表
        page: 当前页码（从0开始）
        size: 每页数量
        total: 总记录数
        base_path: 基础路径（用于生成分页链接）
    """

    def __init__(
        self,
        items: List[Any],
        page: int = 0,
        size: int = 20,
        total: int = 0,
        base_path: str = '',
    ):
        super().__init__()
        self.items = items
        self.page = page
        self.size = size
        self.total = total
        self.base_path = base_path.rstrip('/')

        # 自动生成分页链接
        self._add_pagination_links()

    @staticmethod
    def of(
        items: List[Any],
        page: int = 0,
        size: int = 20,
        total: int = 0,
        base_path: str = '',
    ) -> 'PagedModel':
        """创建 PagedModel。"""
        return PagedModel(items, page, size, total, base_path)

    @property
    def total_pages(self) -> int:
        if self.size == 0:
            return 0
        return (self.total + self.size - 1) // self.size

    def _add_pagination_links(self) -> None:
        """自动添加分页链接（first/last/next/prev/self）。"""
        if not self.base_path:
            return

        total_pages = self.total_pages

        # self 链接
        self.add(Link.of(
            f'{self.base_path}?page={self.page}&size={self.size}',
            'self',
        ))

        # first 链接
        self.add(Link.of(
            f'{self.base_path}?page=0&size={self.size}',
            'first',
        ))

        # last 链接
        if total_pages > 0:
            self.add(Link.of(
                f'{self.base_path}?page={total_pages - 1}&size={self.size}',
                'last',
            ))

        # next 链接
        if self.page + 1 < total_pages:
            self.add(Link.of(
                f'{self.base_path}?page={self.page + 1}&size={self.size}',
                'next',
            ))

        # prev 链接
        if self.page > 0:
            self.add(Link.of(
                f'{self.base_path}?page={self.page - 1}&size={self.size}',
                'prev',
            ))

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。

        返回格式::

            {
                "_embedded": {"items": [...]},
                "_links": {"self": {...}, "first": {...}, "last": {...}, "next": {...}, "prev": {...}},
                "page": {
                    "size": 20,
                    "total_elements": 100,
                    "total_pages": 5,
                    "number": 0
                }
            }
        """
        from springbootai.data.rest import _to_dict
        content = [
            _to_dict(item) if not isinstance(item, dict) else dict(item)
            for item in self.items
        ]
        result: Dict[str, Any] = {
            '_embedded': {'items': content},
            'page': {
                'size': self.size,
                'total_elements': self.total,
                'total_pages': self.total_pages,
                'number': self.page,
            },
        }
        links = self.get_links()
        if links:
            result['_links'] = links
        return result


class WebMvcLinkBuilder:
    """链接构建辅助工具

    对齐 Spring HATEOAS 的 ``WebMvcLinkBuilder``。

    提供便捷方法构建常见链接模式。
    """

    @staticmethod
    def link_to(path: str, rel: str = 'self') -> Link:
        """构建链接。"""
        return Link.of(path, rel)

    @staticmethod
    def self_link(path: str) -> Link:
        """构建 self 链接。"""
        return Link.of(path, 'self')

    @staticmethod
    def crud_links(base_path: str, item_id: Any) -> List[Link]:
        """构建 CRUD 链接集合。

        Args:
            base_path: 基础路径（如 '/api/users'）
            item_id: 实体 ID

        Returns:
            [self, update, delete] 链接列表
        """
        item_path = f'{base_path}/{item_id}'
        return [
            Link.of(item_path, 'self'),
            Link.of(item_path, 'update', method='PUT'),
            Link.of(item_path, 'delete', method='DELETE'),
        ]

    @staticmethod
    def collection_links(base_path: str) -> List[Link]:
        """构建集合链接。

        Args:
            base_path: 基础路径

        Returns:
            [self, create] 链接列表
        """
        return [
            Link.of(base_path, 'self'),
            Link.of(base_path, 'create', method='POST'),
        ]
