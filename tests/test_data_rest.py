"""Spring Data REST 测试"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spring.data.rest import RepositoryRestController, DataRestConfig, _to_dict, _from_dict


# ==================== 测试用 Mock Repository ====================

@dataclass
class User:
    id: int = 0
    name: str = ''
    email: str = ''


class MockUserRepository:
    """内存级 Mock Repository，模拟 PagingAndSortingRepository 接口"""

    def __init__(self):
        self._store: Dict[int, User] = {}
        self._next_id = 1

    def find_all(self, pageable=None) -> any:
        from spring.data.page import Page
        items = list(self._store.values())
        # 排序
        if pageable and pageable.sort:
            for order in pageable.sort.orders:
                reverse = order.direction.value == 'DESC'
                items.sort(key=lambda x: getattr(x, order.property, ''), reverse=reverse)
        # 分页
        page_num = pageable.page_number if pageable else 0
        size = pageable.page_size if pageable else len(items)
        total = len(items)
        start = page_num * size
        end = start + size
        content = items[start:end]
        return Page(content=content, pageable=pageable, total=total)

    def find_by_id(self, id: int) -> Optional[User]:
        return self._store.get(id)

    def save(self, entity: User) -> User:
        if entity.id == 0:
            entity.id = self._next_id
            self._next_id += 1
        self._store[entity.id] = entity
        return entity

    def delete_by_id(self, id: int) -> None:
        self._store.pop(id, None)


@pytest.fixture
def app_and_repo():
    app = FastAPI()
    repo = MockUserRepository()
    controller = RepositoryRestController(
        repository=repo,
        path='/api/users',
        entity_class=User,
        id_type=int,
    )
    controller.register(app)
    return app, repo


class TestRepositoryRestController:
    """REST 控制器测试"""

    def test_create_entity(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)

        response = client.post('/api/users', json={'name': 'Alice', 'email': 'alice@test.com'})
        assert response.status_code == 201
        data = response.json()
        assert data['name'] == 'Alice'
        assert data['email'] == 'alice@test.com'
        assert data['id'] > 0

    def test_get_entity(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)

        # 先创建
        repo.save(User(id=1, name='Bob', email='bob@test.com'))
        response = client.get('/api/users/1')
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'Bob'

    def test_get_entity_not_found(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)
        response = client.get('/api/users/999')
        assert response.status_code == 404

    def test_list_entities(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)

        repo.save(User(id=1, name='A', email='a@test.com'))
        repo.save(User(id=2, name='B', email='b@test.com'))
        repo.save(User(id=3, name='C', email='c@test.com'))

        response = client.get('/api/users?page=0&size=2')
        assert response.status_code == 200
        data = response.json()
        assert len(data['content']) == 2
        assert data['total_elements'] == 3
        assert data['total_pages'] == 2

    def test_list_with_pagination(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)

        for i in range(5):
            repo.save(User(id=i + 1, name=f'User{i + 1}', email=f'u{i}@test.com'))

        response = client.get('/api/users?page=1&size=2')
        assert response.status_code == 200
        data = response.json()
        assert data['page'] == 1
        assert data['size'] == 2
        assert len(data['content']) == 2

    def test_update_entity(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)

        repo.save(User(id=1, name='Old', email='old@test.com'))
        response = client.put('/api/users/1', json={'name': 'New', 'email': 'new@test.com'})
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'New'
        assert data['email'] == 'new@test.com'
        # ID 应保留
        assert data['id'] == 1

    def test_update_not_found(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)
        response = client.put('/api/users/999', json={'name': 'X'})
        assert response.status_code == 404

    def test_delete_entity(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)

        repo.save(User(id=1, name='ToDelete', email='del@test.com'))
        response = client.delete('/api/users/1')
        assert response.status_code == 200
        assert repo.find_by_id(1) is None

    def test_delete_not_found(self, app_and_repo):
        app, repo = app_and_repo
        client = TestClient(app)
        response = client.delete('/api/users/999')
        assert response.status_code == 404


class TestHelperFunctions:
    """辅助函数测试"""

    def test_to_dict_with_dict(self):
        assert _to_dict({'a': 1}) == {'a': 1}

    def test_to_dict_with_none(self):
        assert _to_dict(None) is None

    def test_to_dict_with_object(self):
        obj = User(id=1, name='Test', email='test@test.com')
        result = _to_dict(obj)
        assert result['id'] == 1
        assert result['name'] == 'Test'

    def test_to_dict_with_to_dict_method(self):
        class ObjWithDict:
            def to_dict(self):
                return {'custom': True}
        assert _to_dict(ObjWithDict()) == {'custom': True}

    def test_from_dict(self):
        data = {'id': 1, 'name': 'Test', 'email': 'test@test.com'}
        user = _from_dict(User, data)
        assert user.id == 1
        assert user.name == 'Test'
        assert user.email == 'test@test.com'

    def test_from_dict_filters_extra_keys(self):
        """非实体字段被过滤"""
        data = {'id': 1, 'name': 'Test', 'email': 'test@test.com', 'extra': 'ignored'}
        user = _from_dict(User, data)
        assert user.id == 1
        assert not hasattr(user, 'extra')


class TestDataRestConfig:
    """配置测试"""

    def test_default_config(self):
        config = DataRestConfig()
        assert config.base_path == ''
        assert config.default_page_size == 20
        assert config.max_page_size == 1000

    def test_custom_config(self):
        config = DataRestConfig(
            base_path='/api/v2',
            default_page_size=50,
            max_page_size=500,
        )
        assert config.base_path == '/api/v2'
        assert config.default_page_size == 50
        assert config.max_page_size == 500
