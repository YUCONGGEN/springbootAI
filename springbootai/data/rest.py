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
import re
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger("Spring.Data.Rest")
_SENSITIVE_FIELD = re.compile(
    r"(?:password|passwd|secret|token|credential|private[_-]?key|api[_-]?key)",
    re.IGNORECASE,
)
_PRIVILEGED_WRITE_FIELDS = {
    'role', 'roles', 'permission', 'permissions', 'authorities',
    'is_admin', 'is_superuser', 'admin',
}


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
        secured: bool = False,
        required_scopes: Optional[List[str]] = None,
        read_fields: Optional[List[str]] = None,
        write_fields: Optional[List[str]] = None,
    ):
        if not path.startswith('/'):
            path = '/' + path
        self.repository = repository
        self.path = path.rstrip('/')
        self.entity_class = entity_class
        self.id_type = id_type
        self.secured = bool(secured)
        self.required_scopes = list(required_scopes or [])
        self.read_fields = set(read_fields) if read_fields else None
        self.write_fields = set(write_fields) if write_fields else None

    def register(self, app: Any) -> None:
        """将 CRUD 端点注册到 FastAPI app。

        Args:
            app: FastAPI 应用实例
        """
        from fastapi import Depends, HTTPException, Query, Request

        repo = self.repository
        path = self.path
        id_type = self.id_type
        entity_class = self.entity_class
        read_fields = self.read_fields
        write_fields = self.write_fields

        def authenticate(request: Request) -> Dict[str, Any]:
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.lower().startswith('bearer '):
                raise HTTPException(
                    status_code=401,
                    detail="Bearer token required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = auth_header[7:].strip()
            try:
                from springbootai.security.oauth2 import oauth2_resource_server
                if oauth2_resource_server.is_configured:
                    payload = oauth2_resource_server.validate_token(token)
                else:
                    from springbootai.security.jwt_utils import jwt_utils
                    payload = jwt_utils.decode_token(token)
            except Exception as exc:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid bearer token",
                    headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
                ) from exc
            if self.required_scopes:
                scope_claim = payload.get('scope', payload.get('scp', []))
                token_scopes = set(scope_claim.split()) if isinstance(scope_claim, str) else set(scope_claim)
                if not set(self.required_scopes).issubset(token_scopes):
                    raise HTTPException(status_code=403, detail="Insufficient scope")
            return payload

        route_dependencies = [Depends(authenticate)] if self.secured else []

        # ==================== GET 列表（分页+排序） ====================
        @app.get(
            path,
            summary=f"List {entity_class.__name__}",
            dependencies=route_dependencies,
        )
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
                    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', field):
                        raise HTTPException(status_code=400, detail="Invalid sort field")
                    if read_fields is not None and field not in read_fields:
                        raise HTTPException(status_code=400, detail="Sort field is not exposed")
                    direction = Direction.DESC if len(parts) > 1 and parts[1].strip().lower() == 'desc' else Direction.ASC
                    sort_obj = Sort(Order(property=field, direction=direction))

                pageable = Pageable.of(page_number=page, page_size=size, sort=sort_obj)
                result = repo.find_all(pageable)

                # 返回分页响应
                if hasattr(result, 'content') and hasattr(result, 'total'):
                    return {
                        'content': [_to_dict(item, read_fields) for item in result.content],
                        'page': result.number,
                        'size': result.size,
                        'total_elements': result.total,
                        'total_pages': result.total_pages,
                    }
                # 非 Page 对象（普通列表）
                return {
                    'content': [_to_dict(item, read_fields) for item in result],
                    'page': page,
                    'size': size,
                }
            except HTTPException:
                raise
            except Exception:
                logger.exception("List %s failed", entity_class.__name__)
                raise HTTPException(status_code=500, detail="Unable to list resources")

        # ==================== GET 详情 ====================
        @app.get(
            f"{path}/{{item_id}}",
            summary=f"Get {entity_class.__name__} by ID",
            dependencies=route_dependencies,
        )
        def get_entity(item_id: id_type):
            """根据 ID 获取实体"""
            entity = repo.find_by_id(item_id)
            if entity is None:
                raise HTTPException(status_code=404, detail=f"{entity_class.__name__} with id={item_id} not found")
            return _to_dict(entity, read_fields)

        # ==================== POST 创建 ====================
        @app.post(
            path,
            summary=f"Create {entity_class.__name__}",
            status_code=201,
            dependencies=route_dependencies,
        )
        def create_entity(data: dict):
            """创建实体"""
            try:
                entity = _from_dict(
                    entity_class, data, write_fields, reject_sensitive=True
                )
                saved = repo.save(entity)
                return _to_dict(saved, read_fields)
            except Exception:
                logger.exception("Create %s failed", entity_class.__name__)
                raise HTTPException(status_code=400, detail="Invalid resource payload")

        # ==================== PUT 更新 ====================
        @app.put(
            f"{path}/{{item_id}}",
            summary=f"Update {entity_class.__name__}",
            dependencies=route_dependencies,
        )
        def update_entity(item_id: id_type, data: dict):
            """更新实体"""
            try:
                existing = repo.find_by_id(item_id)
                if existing is None:
                    raise HTTPException(status_code=404, detail=f"{entity_class.__name__} with id={item_id} not found")

                entity = _from_dict(
                    entity_class, data, write_fields, reject_sensitive=True
                )
                # 保留原 ID
                if hasattr(entity, 'id'):
                    entity.id = item_id
                saved = repo.save(entity)
                return _to_dict(saved, read_fields)
            except HTTPException:
                raise
            except Exception:
                logger.exception("Update %s failed", entity_class.__name__)
                raise HTTPException(status_code=400, detail="Invalid resource payload")

        # ==================== DELETE 删除 ====================
        @app.delete(
            f"{path}/{{item_id}}",
            summary=f"Delete {entity_class.__name__}",
            dependencies=route_dependencies,
        )
        def delete_entity(item_id: id_type):
            """删除实体"""
            existing = repo.find_by_id(item_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"{entity_class.__name__} with id={item_id} not found")
            try:
                repo.delete_by_id(item_id)
                return {'message': f'{entity_class.__name__} with id={item_id} deleted'}
            except Exception:
                logger.exception("Delete %s failed", entity_class.__name__)
                raise HTTPException(status_code=500, detail="Unable to delete resource")

        logger.info(
            f"Registered REST endpoints for {entity_class.__name__} at {path} "
            f"(GET/POST/PUT/DELETE)"
        )


def _to_dict(entity: Any, allowed_fields: Optional[set] = None) -> Any:
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
        raw = dict(entity)
    if hasattr(entity, 'to_dict') and callable(entity.to_dict):
        raw = entity.to_dict()
    elif hasattr(entity, '__dict__'):
        raw = {k: v for k, v in entity.__dict__.items() if not k.startswith('_')}
    elif not isinstance(entity, dict):
        return entity
    if not isinstance(raw, dict):
        return raw
    return {
        key: value for key, value in raw.items()
        if not _SENSITIVE_FIELD.search(str(key))
        and (allowed_fields is None or key in allowed_fields)
    }


def _from_dict(
    entity_class: Type,
    data: dict,
    allowed_fields: Optional[set] = None,
    reject_sensitive: bool = False,
) -> Any:
    """从字典创建实体实例。

    支持以下情况：
    - 实体类有 from_dict() 类方法
    - 实体类有 __init__ 接受关键字参数
    """
    if not isinstance(data, dict):
        raise ValueError("Resource payload must be an object")
    forbidden = {
        key for key in data
        if _SENSITIVE_FIELD.search(str(key))
        or str(key).lower() in _PRIVILEGED_WRITE_FIELDS
        or (allowed_fields is not None and key not in allowed_fields)
    }
    if forbidden and reject_sensitive:
        raise ValueError("Payload contains fields that are not writable")
    filtered_data = {key: value for key, value in data.items() if key not in forbidden}
    if hasattr(entity_class, 'from_dict') and callable(entity_class.from_dict):
        return entity_class.from_dict(filtered_data)
    # 过滤掉非实体字段的键
    import inspect
    sig = inspect.signature(entity_class.__init__)
    valid_params = {
        k: v for k, v in filtered_data.items()
        if k in sig.parameters and k != 'self'
    }
    return entity_class(**valid_params)


class DataRestConfig:
    """Spring Data REST 配置

    对齐 Spring Boot 的 spring.data.rest 配置项。

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
