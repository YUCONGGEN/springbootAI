"""
Spring Data REST（对齐 Spring Data REST）

自动将 Repository 转换为 REST API，无需手写 Controller。

功能：
- 自动生成 CRUD 端点（GET 列表/详情、POST 创建、PUT 更新、DELETE 删除）
- 支持分页（page、size 参数）和排序（sort 参数）
- 支持路径前缀自定义
- 与 FastAPI 路由集成
- 与现有 PagingAndSortingRepository 对齐（duck typing，不强制继承）

与 Java Spring Data REST 的差异：
- Java 通过 @RepositoryRestResource 注解自动暴露
- Python 版本通过 RepositoryRestController 显式注册
- Java 使用 HATEOAS 超媒体链接，Python 版本返回分页元数据
- Java 支持 HAL/HAL-FORMS 等媒体类型，Python 版本使用 JSON

Usage::

    from springbootai.data.rest import RepositoryRestController
    from springbootai.data.repository import PagingAndSortingRepository

    # 假设已有 user_repo: PagingAndSortingRepository[User]
    controller = RepositoryRestController(
        repository=user_repo,
        path='/api/users',
        entity_class=User,
    )

    # 注册到 FastAPI app
    controller.register(app)

    # 生成的端点：
    # GET    /api/users          列表（支持 ?page=0&size=20&sort=name,asc）
    # GET    /api/users/{id}     详情
    # POST   /api/users          创建
    # PUT    /api/users/{id}     更新
    # DELETE /api/users/{id}     删除
"""
import logging
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger("Spring.Data.Rest")


class RepositoryRestController:
    """Repository REST 控制器

    自动为 Repository 生成 CRUD REST 端点。

    Args:
        repository: Repository 实例，需支持以下方法（duck typing）：
            - find_all(pageable) -> Page
            - find_by_id(id) -> Optional[entity]
            - save(entity) -> entity
            - delete_by_id(id) -> None
        path: REST 路径前缀（如 '/api/users'）
        entity_class: 实体类（用于创建实例）
        id_type: ID 字段的类型（默认 int）
    """

    def __init__(
        self,
        repository: Any,
        path: str,
        entity_class: Type,
        id_type: type = int,
    ):
        if not path.startswith('/'):
            path = '/' + path
        self.repository = repository
        self.path = path.rstrip('/')
        self.entity_class = entity_class
        self.id_type = id_type

    def register(self, app: Any) -> None:
        """将 CRUD 端点注册到 FastAPI app。

        Args:
            app: FastAPI 应用实例
        """
        from fastapi import HTTPException, Query

        repo = self.repository
        path = self.path
        id_type = self.id_type
        entity_class = self.entity_class

        # ==================== GET 列表（分页+排序） ====================
        @app.get(path, summary=f"List {entity_class.__name__}")
        def list_entities(
            page: int = Query(0, ge=0, description="页码（从0开始）"),
            size: int = Query(20, ge=1, le=1000, description="每页数量"),
            sort: Optional[str] = Query(None, description="排序，格式: field,asc 或 field,desc"),
        ):
            """获取实体列表（分页+排序）"""
            try:
                from springbootai.data.page import Pageable, Sort, Order, Direction
                sort_obj = Sort.unsorted()
                if sort:
                    parts = sort.split(',')
                    field = parts[0].strip()
                    direction = Direction.DESC if len(parts) > 1 and parts[1].strip().lower() == 'desc' else Direction.ASC
                    sort_obj = Sort(Order(property=field, direction=direction))

                pageable = Pageable.of(page_number=page, page_size=size, sort=sort_obj)
                result = repo.find_all(pageable)

                # 返回分页响应
                if hasattr(result, 'content') and hasattr(result, 'total'):
                    return {
                        'content': [_to_dict(item) for item in result.content],
                        'page': result.number,
                        'size': result.size,
                        'total_elements': result.total,
                        'total_pages': result.total_pages,
                    }
                # 非 Page 对象（普通列表）
                return {
                    'content': [_to_dict(item) for item in result],
                    'page': page,
                    'size': size,
                }
            except Exception as e:
                logger.error(f"List {entity_class.__name__} failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # ==================== GET 详情 ====================
        @app.get(f"{path}/{{item_id}}", summary=f"Get {entity_class.__name__} by ID")
        def get_entity(item_id: id_type):
            """根据 ID 获取实体"""
            entity = repo.find_by_id(item_id)
            if entity is None:
                raise HTTPException(status_code=404, detail=f"{entity_class.__name__} with id={item_id} not found")
            return _to_dict(entity)

        # ==================== POST 创建 ====================
        @app.post(path, summary=f"Create {entity_class.__name__}", status_code=201)
        def create_entity(data: dict):
            """创建实体"""
            try:
                entity = _from_dict(entity_class, data)
                saved = repo.save(entity)
                return _to_dict(saved)
            except Exception as e:
                logger.error(f"Create {entity_class.__name__} failed: {e}")
                raise HTTPException(status_code=400, detail=str(e))

        # ==================== PUT 更新 ====================
        @app.put(f"{path}/{{item_id}}", summary=f"Update {entity_class.__name__}")
        def update_entity(item_id: id_type, data: dict):
            """更新实体"""
            try:
                existing = repo.find_by_id(item_id)
                if existing is None:
                    raise HTTPException(status_code=404, detail=f"{entity_class.__name__} with id={item_id} not found")

                entity = _from_dict(entity_class, data)
                # 保留原 ID
                if hasattr(entity, 'id'):
                    entity.id = item_id
                saved = repo.save(entity)
                return _to_dict(saved)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Update {entity_class.__name__} failed: {e}")
                raise HTTPException(status_code=400, detail=str(e))

        # ==================== DELETE 删除 ====================
        @app.delete(f"{path}/{{item_id}}", summary=f"Delete {entity_class.__name__}")
        def delete_entity(item_id: id_type):
            """删除实体"""
            existing = repo.find_by_id(item_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"{entity_class.__name__} with id={item_id} not found")
            try:
                repo.delete_by_id(item_id)
                return {'message': f'{entity_class.__name__} with id={item_id} deleted'}
            except Exception as e:
                logger.error(f"Delete {entity_class.__name__} failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        logger.info(
            f"Registered REST endpoints for {entity_class.__name__} at {path} "
            f"(GET/POST/PUT/DELETE)"
        )


def _to_dict(entity: Any) -> Any:
    """将实体转换为字典。

    支持以下情况：
    - 实体有 to_dict() 方法
    - 实体有 __dict__ 属性
    - 实体本身就是 dict
    - 实体是基础类型（int/str 等）
    """
    if entity is None:
        return None
    if isinstance(entity, dict):
        return entity
    if hasattr(entity, 'to_dict') and callable(entity.to_dict):
        return entity.to_dict()
    if hasattr(entity, '__dict__'):
        result = {}
        for k, v in entity.__dict__.items():
            if not k.startswith('_'):
                result[k] = v
        return result
    return entity


def _from_dict(entity_class: Type, data: dict) -> Any:
    """从字典创建实体实例。

    支持以下情况：
    - 实体类有 from_dict() 类方法
    - 实体类有 __init__ 接受关键字参数
    """
    if hasattr(entity_class, 'from_dict') and callable(entity_class.from_dict):
        return entity_class.from_dict(data)
    # 过滤掉非实体字段的键
    import inspect
    sig = inspect.signature(entity_class.__init__)
    valid_params = {
        k: v for k, v in data.items()
        if k in sig.parameters and k != 'self'
    }
    return entity_class(**valid_params)


class DataRestConfig:
    """Spring Data REST 配置

    对齐 Spring Boot 的 springbootai.data.rest 配置项。

    Args:
        base_path: 所有 Repository 的基础路径（如 '/api'）
        default_page_size: 默认分页大小
        max_page_size: 最大分页大小
        return_body_on_create: 创建后是否返回 body
        return_body_on_update: 更新后是否返回 body
    """

    def __init__(
        self,
        base_path: str = '',
        default_page_size: int = 20,
        max_page_size: int = 1000,
        return_body_on_create: bool = True,
        return_body_on_update: bool = True,
    ):
        self.base_path = base_path
        self.default_page_size = default_page_size
        self.max_page_size = max_page_size
        self.return_body_on_create = return_body_on_create
        self.return_body_on_update = return_body_on_update
