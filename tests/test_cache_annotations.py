"""SpringPy 缓存增强注解测试 —— 覆盖 @CachePut / @CacheEvict / @CacheConfig / @Caching。

对齐 tests/test_validation_module.py 的 pytest 风格。通过 ``BeanFactory._apply_aop_proxy``
走真实 AOP 集成路径（与 IoC 容器受管 Bean 一致），验证：
- 注解元数据构造
- @Cacheable 命中/未命中（回归）
- @CachePut 总是执行 + 写缓存 + 跨方法更新 @Cacheable 条目
- @CacheEvict 按 key 失效 / all_entries 清空命名空间 / before_invocation 时序 / 异常不失效
- condition（参数名 / !参数名 / callable）
- @CacheConfig 类级默认命名空间回退
- @Caching 组合多操作

缓存存储复用 ``BeanFactory._cache``（与 @Cacheable 同一进程内存储，对齐 Spring Cache 抽象）。
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spring.annotations.core import Cacheable
from spring.annotations.cache import CachePut, CacheEvict, CacheConfig, Caching
from spring.context.bean_factory import BeanFactory
from spring.context.bean_definition import BeanDefinition


# ==================== 辅助：构建受管 Bean（应用 AOP） ====================

def _make_bean(bean_cls):
    """实例化 BeanFactory + Bean，并应用 _apply_aop_proxy（模拟 IoC 容器创建受管 Bean）。"""
    bf = BeanFactory()
    instance = bean_cls()
    definition = BeanDefinition(bean_class=bean_cls, bean_name="svc")
    bf._apply_aop_proxy(instance, definition)
    return instance, bf


# ==================== 注解元数据 ====================

class TestCacheAnnotationMetadata:
    def test_cache_put_defaults(self):
        ann = CachePut()
        assert ann.value == ""
        assert ann.key is None
        assert ann.condition is None
        assert ann._annotation_type == "aop"

    def test_cache_put_custom(self):
        ann = CachePut(value="users", key="{id}", condition="enabled")
        assert ann.value == "users"
        assert ann.key == "{id}"
        assert ann.condition == "enabled"

    def test_cache_evict_defaults(self):
        ann = CacheEvict()
        assert ann.all_entries is False
        assert ann.before_invocation is False

    def test_cache_evict_all_entries_and_before(self):
        ann = CacheEvict(value="users", all_entries=True, before_invocation=True)
        assert ann.all_entries is True
        assert ann.before_invocation is True

    def test_cache_config_defaults(self):
        ann = CacheConfig()
        assert ann.cache_names == []
        assert ann.key_generator is None

    def test_cache_config_custom(self):
        ann = CacheConfig(cache_names=["users", "orders"], key_generator="myGen")
        assert ann.cache_names == ["users", "orders"]
        assert ann.key_generator == "myGen"

    def test_caching_empty(self):
        ann = Caching()
        assert ann.cacheable == [] and ann.put == [] and ann.evict == []

    def test_caching_with_ops(self):
        put_op = CachePut(value="u", key="{id}")
        evict_op = CacheEvict(value="u", key="{id}")
        ann = Caching(put=[put_op], evict=[evict_op])
        assert ann.put == [put_op]
        assert ann.evict == [evict_op]


# ==================== @Cacheable 回归（基线） ====================

class TestCacheableBaseline:
    def test_cacheable_miss_then_hit(self):
        class Svc:
            def __init__(self):
                self.calls = 0

            @Cacheable(value="users", key="{id}")
            def get_user(self, id):
                self.calls += 1
                return {"id": id, "name": f"u{id}"}

        svc, _ = _make_bean(Svc)
        r1 = svc.get_user(1)
        r2 = svc.get_user(1)
        assert r1 == r2 == {"id": 1, "name": "u1"}
        assert svc.calls == 1  # 第二次命中缓存
        # 不同 id 不命中
        svc.get_user(2)
        assert svc.calls == 2

    def test_cacheable_condition_skip(self):
        class Svc:
            def __init__(self):
                self.calls = 0

            @Cacheable(value="v", key="{id}", condition="enabled")
            def get(self, id, enabled):
                self.calls += 1
                return id

        svc, _ = _make_bean(Svc)
        # enabled=False -> 不走缓存，每次执行
        svc.get(1, enabled=False)
        svc.get(1, enabled=False)
        assert svc.calls == 2
        # enabled=True -> 走缓存
        svc.get(1, enabled=True)
        svc.get(1, enabled=True)
        assert svc.calls == 3


# ==================== @CachePut ====================

class TestCachePut:
    def test_always_executes_and_stores(self):
        class Svc:
            def __init__(self):
                self.calls = 0

            @CachePut(value="v", key="{id}")
            def put(self, id):
                self.calls += 1
                return id * 10

        svc, bf = _make_bean(Svc)
        assert svc.put(1) == 10
        assert svc.put(1) == 10  # 总是执行
        assert svc.calls == 2
        # 缓存中存在条目
        assert len(bf._cache) == 1

    def test_cache_put_updates_cacheable_entry_cross_method(self):
        class Svc:
            def __init__(self):
                self.get_calls = 0

            @Cacheable(value="users", key="{id}")
            def get_user(self, id):
                self.get_calls += 1
                return {"id": id, "name": "old"}

            @CachePut(value="users", key="{id}")
            def update_user(self, id, name):
                return {"id": id, "name": name}

        svc, _ = _make_bean(Svc)
        # 首次 get：执行并缓存
        assert svc.get_user(1) == {"id": 1, "name": "old"}
        assert svc.get_calls == 1
        # update：写入新值到同一缓存 key
        svc.update_user(1, "new")
        # 再次 get：应命中被 @CachePut 更新的缓存，不执行
        assert svc.get_user(1) == {"id": 1, "name": "new"}
        assert svc.get_calls == 1

    def test_condition_param_name(self):
        class Svc:
            def __init__(self):
                self.calls = 0

            @CachePut(value="v", key="{id}", condition="enabled")
            def put(self, id, enabled):
                self.calls += 1
                return id

        svc, bf = _make_bean(Svc)
        svc.put(1, enabled=False)  # 不写缓存
        assert len(bf._cache) == 0
        svc.put(1, enabled=True)  # 写缓存
        assert len(bf._cache) == 1

    def test_condition_negation(self):
        class Svc:
            @CachePut(value="v", key="{id}", condition="!skip")
            def put(self, id, skip):
                return id

        svc, bf = _make_bean(Svc)
        svc.put(1, skip=True)  # skip=True -> !skip=False -> 不写
        assert len(bf._cache) == 0
        svc.put(1, skip=False)  # 写
        assert len(bf._cache) == 1

    def test_condition_callable(self):
        class Svc:
            @CachePut(value="v", key="{id}", condition=lambda id: id > 0)
            def put(self, id):
                return id

        svc, bf = _make_bean(Svc)
        svc.put(-1)  # 不写
        assert len(bf._cache) == 0
        svc.put(1)  # 写
        assert len(bf._cache) == 1


# ==================== @CacheEvict ====================

class TestCacheEvict:
    def test_evict_by_key_cross_method(self):
        class Svc:
            def __init__(self):
                self.get_calls = 0

            @Cacheable(value="users", key="{id}")
            def get_user(self, id):
                self.get_calls += 1
                return {"id": id}

            @CacheEvict(value="users", key="{id}")
            def delete_user(self, id):
                return None

        svc, _ = _make_bean(Svc)
        svc.get_user(1)
        assert svc.get_calls == 1
        svc.get_user(1)  # 命中缓存
        assert svc.get_calls == 1
        svc.delete_user(1)  # 失效该 key
        svc.get_user(1)  # 缓存已失效 -> 重新执行
        assert svc.get_calls == 2

    def test_evict_all_entries(self):
        class Svc:
            @Cacheable(value="users", key="{id}")
            def get_user(self, id):
                return {"id": id}

            @CacheEvict(value="users", all_entries=True)
            def clear(self):
                return None

        svc, bf = _make_bean(Svc)
        svc.get_user(1)
        svc.get_user(2)
        svc.get_user(3)
        assert len(bf._cache) == 3
        svc.clear()
        assert len(bf._cache) == 0

    def test_evict_after_invocation_only_on_success(self):
        # 默认 before_invocation=False：方法异常时不失效
        class Svc:
            @Cacheable(value="u", key="{id}")
            def get(self, id):
                return id

            @CacheEvict(value="u", key="{id}")
            def delete(self, id):
                raise RuntimeError("boom")

        svc, bf = _make_bean(Svc)
        svc.get(1)
        assert len(bf._cache) == 1
        with pytest.raises(RuntimeError):
            svc.delete(1)
        # 异常 -> 不失效
        assert len(bf._cache) == 1

    def test_evict_before_invocation_runs_regardless_of_exception(self):
        class Svc:
            @Cacheable(value="u", key="{id}")
            def get(self, id):
                return id

            @CacheEvict(value="u", key="{id}", before_invocation=True)
            def delete(self, id):
                raise RuntimeError("boom")

        svc, bf = _make_bean(Svc)
        svc.get(1)
        assert len(bf._cache) == 1
        with pytest.raises(RuntimeError):
            svc.delete(1)
        # before_invocation -> 调用前已失效
        assert len(bf._cache) == 0

    def test_evict_before_invocation_then_method_runs(self):
        class Svc:
            def __init__(self):
                self.calls = 0

            @Cacheable(value="u", key="{id}")
            def get(self, id):
                return id

            @CacheEvict(value="u", key="{id}", before_invocation=True)
            def refresh(self, id):
                self.calls += 1
                return "done"

        svc, _ = _make_bean(Svc)
        svc.get(1)
        svc.refresh(1)
        assert svc.calls == 1  # 方法仍执行


# ==================== @CacheConfig 类级默认 ====================

class TestCacheConfig:
    def test_default_namespace_fallback_for_cache_put(self):
        @CacheConfig(cache_names=["default_ns"])
        class Svc:
            def __init__(self):
                self.calls = 0

            @CachePut(key="{id}")  # value 为空 -> 回退到 @CacheConfig
            def put(self, id):
                self.calls += 1
                return id

        svc, bf = _make_bean(Svc)
        svc.put(1)
        assert len(bf._cache) == 1
        # 命名空间应登记为 default_ns
        meta = list(bf._cache_metadata.values())[0]
        assert meta["namespace"] == "default_ns"

    def test_default_namespace_fallback_for_cache_evict_all_entries(self):
        @CacheConfig(cache_names=["default_ns"])
        class Svc:
            @Cacheable(value="default_ns", key="{id}")
            def get(self, id):
                return id

            @CacheEvict(all_entries=True)  # value 为空 -> 回退到 @CacheConfig
            def clear(self):
                return None

        svc, bf = _make_bean(Svc)
        svc.get(1)
        svc.get(2)
        assert len(bf._cache) == 2
        svc.clear()
        assert len(bf._cache) == 0

    def test_explicit_value_overrides_config(self):
        @CacheConfig(cache_names=["default_ns"])
        class Svc:
            @CachePut(value="explicit_ns", key="{id}")
            def put(self, id):
                return id

        svc, bf = _make_bean(Svc)
        svc.put(1)
        meta = list(bf._cache_metadata.values())[0]
        assert meta["namespace"] == "explicit_ns"


# ==================== @Caching 组合 ====================

class TestCaching:
    def test_caching_put_and_evict_combined(self):
        class Svc:
            def __init__(self):
                self.calls = 0

            @Cacheable(value="users", key="{id}")
            def get_user(self, id):
                self.calls += 1
                return {"id": id, "name": "old"}

            @Caching(
                put=[CachePut(value="users", key="{id}")],
                evict=[CacheEvict(value="users", key="{id}", before_invocation=True)],
            )
            def refresh_user(self, id, name):
                return {"id": id, "name": name}

        svc, _ = _make_bean(Svc)
        svc.get_user(1)
        assert svc.calls == 1
        # refresh: evict(before) -> 执行 -> put(写新值)
        result = svc.refresh_user(1, "new")
        assert result == {"id": 1, "name": "new"}
        # 再次 get：应命中 put 写入的新值
        assert svc.get_user(1) == {"id": 1, "name": "new"}
        assert svc.calls == 1  # get 未重新执行

    def test_caching_order_cacheable_put_evict(self):
        # 验证 @Caching 按 cacheable -> put -> evict 顺序叠加包装（不报错）
        class Svc:
            @Caching(
                cacheable=[Cacheable(value="v", key="{id}")],
                put=[CachePut(value="v", key="{id}")],
                evict=[CacheEvict(value="v", key="{id}")],
            )
            def op(self, id):
                return id

        svc, _ = _make_bean(Svc)
        # 能正常调用即说明三层包装叠加成功
        assert svc.op(1) == 1
