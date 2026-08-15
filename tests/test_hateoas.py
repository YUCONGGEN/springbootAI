"""Spring HATEOAS 超媒体链接测试"""
import pytest

from spring.web.hateoas import (
    CollectionModel,
    EntityModel,
    Link,
    PagedModel,
    RepresentationModel,
    WebMvcLinkBuilder,
)


class TestLink:
    """Link 测试"""

    def test_create_link(self):
        link = Link.of('/api/users/1', 'self')
        assert link.href == '/api/users/1'
        assert link.rel == 'self'

    def test_link_with_method(self):
        link = Link.of('/api/users/1', 'update', method='PUT')
        d = link.to_dict()
        assert d['href'] == '/api/users/1'
        assert d['method'] == 'PUT'

    def test_link_with_title_and_type(self):
        link = Link(href='/api/docs', rel='help', title='Documentation', type='text/html')
        d = link.to_dict()
        assert d['title'] == 'Documentation'
        assert d['type'] == 'text/html'

    def test_link_minimal_dict(self):
        link = Link.of('/api/users', 'self')
        d = link.to_dict()
        assert d == {'href': '/api/users'}


class TestRepresentationModel:
    """RepresentationModel 测试"""

    def test_add_link(self):
        model = RepresentationModel()
        model.add(Link.of('/api/users', 'self'))
        links = model.get_links()
        assert 'self' in links
        assert links['self']['href'] == '/api/users'

    def test_add_multiple_links(self):
        model = RepresentationModel()
        model.add(Link.of('/api/users', 'self'))
        model.add(Link.of('/api/users', 'create', method='POST'))
        links = model.get_links()
        assert len(links) == 2
        assert 'self' in links
        assert 'create' in links

    def test_add_all(self):
        model = RepresentationModel()
        model.add_all([
            Link.of('/api/users', 'self'),
            Link.of('/api/users', 'create', method='POST'),
        ])
        links = model.get_links()
        assert len(links) == 2

    def test_chaining(self):
        model = RepresentationModel()
        result = model.add(Link.of('/a', 'self')).add(Link.of('/b', 'next'))
        assert result is model
        assert len(model.get_links()) == 2

    def test_empty_links(self):
        model = RepresentationModel()
        d = model.to_dict()
        assert d == {}  # 无链接时返回空字典

    def test_to_dict_with_links(self):
        model = RepresentationModel()
        model.add(Link.of('/api/users', 'self'))
        d = model.to_dict()
        assert '_links' in d
        assert d['_links']['self']['href'] == '/api/users'


class TestEntityModel:
    """EntityModel 测试"""

    def test_entity_model_basic(self):
        model = EntityModel.of({'id': 1, 'name': 'Alice'})
        model.add(Link.of('/api/users/1', 'self'))
        d = model.to_dict()
        assert d['id'] == 1
        assert d['name'] == 'Alice'
        assert '_links' in d
        assert d['_links']['self']['href'] == '/api/users/1'

    def test_entity_model_with_object(self):
        class User:
            def __init__(self):
                self.id = 1
                self.name = 'Bob'

        model = EntityModel.of(User())
        model.add(Link.of('/api/users/1', 'self'))
        d = model.to_dict()
        assert d['id'] == 1
        assert d['name'] == 'Bob'

    def test_entity_model_no_links(self):
        model = EntityModel.of({'id': 1})
        d = model.to_dict()
        assert d['id'] == 1
        assert '_links' not in d

    def test_entity_model_multiple_links(self):
        model = EntityModel.of({'id': 1, 'name': 'Alice'})
        model.add_all([
            Link.of('/api/users/1', 'self'),
            Link.of('/api/users/1', 'update', method='PUT'),
            Link.of('/api/users/1', 'delete', method='DELETE'),
        ])
        d = model.to_dict()
        assert len(d['_links']) == 3
        assert d['_links']['update']['method'] == 'PUT'


class TestCollectionModel:
    """CollectionModel 测试"""

    def test_collection_model_basic(self):
        users = [{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}]
        model = CollectionModel.of(users)
        model.add(Link.of('/api/users', 'self'))
        d = model.to_dict()
        assert '_embedded' in d
        assert len(d['_embedded']['items']) == 2
        assert d['_links']['self']['href'] == '/api/users'

    def test_collection_model_empty(self):
        model = CollectionModel.of([])
        d = model.to_dict()
        assert d['_embedded']['items'] == []

    def test_collection_model_with_links(self):
        model = CollectionModel.of([{'id': 1}])
        model.add_all([
            Link.of('/api/users', 'self'),
            Link.of('/api/users', 'create', method='POST'),
        ])
        d = model.to_dict()
        assert len(d['_links']) == 2


class TestPagedModel:
    """PagedModel 测试"""

    def test_paged_model_basic(self):
        items = [{'id': 1}, {'id': 2}]
        model = PagedModel.of(items, page=0, size=20, total=100, base_path='/api/users')
        d = model.to_dict()

        assert '_embedded' in d
        assert len(d['_embedded']['items']) == 2
        assert d['page']['size'] == 20
        assert d['page']['total_elements'] == 100
        assert d['page']['total_pages'] == 5
        assert d['page']['number'] == 0

    def test_paged_model_links(self):
        """分页模型自动生成分页链接"""
        model = PagedModel.of([], page=1, size=20, total=100, base_path='/api/users')
        d = model.to_dict()
        links = d['_links']

        # 应包含 self, first, last, next, prev
        assert 'self' in links
        assert 'first' in links
        assert 'last' in links
        assert 'next' in links  # page=1, total_pages=5, 有 next
        assert 'prev' in links  # page=1 > 0, 有 prev

    def test_paged_model_first_page(self):
        """第一页没有 prev"""
        model = PagedModel.of([], page=0, size=20, total=100, base_path='/api/users')
        d = model.to_dict()
        links = d['_links']
        assert 'prev' not in links
        assert 'next' in links

    def test_paged_model_last_page(self):
        """最后一页没有 next"""
        model = PagedModel.of([], page=4, size=20, total=100, base_path='/api/users')
        d = model.to_dict()
        links = d['_links']
        assert 'next' not in links
        assert 'prev' in links

    def test_paged_model_single_page(self):
        """只有一页时没有 next/prev"""
        model = PagedModel.of([], page=0, size=100, total=5, base_path='/api/users')
        d = model.to_dict()
        links = d['_links']
        assert 'next' not in links
        assert 'prev' not in links
        assert 'first' in links
        assert 'last' in links

    def test_paged_model_no_base_path(self):
        """无 base_path 时不生成链接"""
        model = PagedModel.of([{'id': 1}], page=0, size=20, total=1)
        d = model.to_dict()
        assert '_links' not in d

    def test_paged_model_total_pages_calculation(self):
        assert PagedModel.of([], page=0, size=20, total=100).total_pages == 5
        assert PagedModel.of([], page=0, size=20, total=101).total_pages == 6
        assert PagedModel.of([], page=0, size=20, total=1).total_pages == 1
        assert PagedModel.of([], page=0, size=20, total=0).total_pages == 0


class TestWebMvcLinkBuilder:
    """链接构建器测试"""

    def test_link_to(self):
        link = WebMvcLinkBuilder.link_to('/api/users', 'self')
        assert link.href == '/api/users'
        assert link.rel == 'self'

    def test_self_link(self):
        link = WebMvcLinkBuilder.self_link('/api/users/1')
        assert link.rel == 'self'
        assert link.href == '/api/users/1'

    def test_crud_links(self):
        links = WebMvcLinkBuilder.crud_links('/api/users', 1)
        assert len(links) == 3

        rels = [l.rel for l in links]
        assert 'self' in rels
        assert 'update' in rels
        assert 'delete' in rels

        # update 和 delete 应有 method
        update_link = next(l for l in links if l.rel == 'update')
        assert update_link.method == 'PUT'
        delete_link = next(l for l in links if l.rel == 'delete')
        assert delete_link.method == 'DELETE'

    def test_collection_links(self):
        links = WebMvcLinkBuilder.collection_links('/api/users')
        assert len(links) == 2

        rels = [l.rel for l in links]
        assert 'self' in rels
        assert 'create' in rels

        create_link = next(l for l in links if l.rel == 'create')
        assert create_link.method == 'POST'
