"""Runtime coverage for declarative AOP, @PostAuthorize and @Recover."""

import asyncio

import pytest

from springbootai.annotations import (
    After,
    AfterReturning,
    AfterThrowing,
    Around,
    Aspect,
    Before,
    Pointcut,
    PostAuthorize,
    Recover,
    Retryable,
)
from springbootai.aop import JoinPoint, ProceedingJoinPoint
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.bean_factory import BeanFactory
from springbootai.context.scanner import ComponentScanner
from springbootai.retry.retry_annotations import Retryable as StandaloneRetryable
from springbootai.retry.retry_decorator import retryable_decorator
from springbootai.security.security_aop import (
    AuthenticationError,
    AuthorizationError,
    post_authorize_decorator,
)
from springbootai.security.security_context import SecurityContextHolder


def _managed_beans(*bean_classes):
    factory = BeanFactory()
    for bean_class in bean_classes:
        name = bean_class.__name__[0].lower() + bean_class.__name__[1:]
        factory.register_bean_definition(
            name,
            BeanDefinition(bean_class=bean_class, bean_name=name),
        )
    return factory


class TestDeclarativeAop:
    def test_aspect_is_a_scannable_component(self):
        @Aspect
        class AuditAspect:
            pass

        scanner = ComponentScanner(application_context=None)
        assert scanner._is_component(AuditAspect)

    def test_all_advice_types_run_through_managed_bean_proxy(self):
        events = []

        @Aspect
        class RecordingAspect:
            @Pointcut("execution(* *.WorkService.*(..))")
            def service_methods(self):
                pass

            @Before("service_methods()")
            def before(self, join_point: JoinPoint):
                events.append(("before", join_point.method_name, join_point.args))

            @Around("service_methods()")
            def around(self, join_point: ProceedingJoinPoint):
                events.append(("around-before", join_point.signature))
                result = join_point.proceed()
                events.append(("around-after", result))
                return result

            @AfterReturning(pointcut="service_methods()", returning="value")
            def returned(self, value):
                events.append(("returning", value))

            @AfterThrowing(pointcut="service_methods()", throwing="error")
            def thrown(self, error):
                events.append(("throwing", type(error).__name__))

            @After("service_methods()")
            def after(self):
                events.append(("after",))

        class WorkService:
            def run(self, value):
                return value * 2

            def fail(self):
                raise LookupError("failed")

        factory = _managed_beans(WorkService, RecordingAspect)
        service = factory.get_bean("workService")

        assert service.run(3) == 6
        assert [event[0] for event in events] == [
            "before", "around-before", "around-after", "returning", "after"
        ]
        assert events[0][1:] == ("run", (3,))

        events.clear()
        with pytest.raises(LookupError, match="failed"):
            service.fail()
        assert [event[0] for event in events] == [
            "before", "around-before", "throwing", "after"
        ]

    def test_pointcut_composition_bean_and_annotation_matching(self):
        events = []

        @Aspect
        class AuditAspect:
            @Pointcut("bean(order*)")
            def order_beans(self):
                pass

            @Before("order_beans() && @annotation(Retryable)")
            def record(self, join_point):
                events.append(join_point.method_name)

        class OrderService:
            @Retryable(max_attempts=1, backoff=0)
            def submit(self):
                return "ok"

            def query(self):
                return "ok"

        factory = _managed_beans(AuditAspect, OrderService)
        service = factory.get_bean("orderService")

        assert service.submit() == "ok"
        assert service.query() == "ok"
        assert events == ["submit"]

    def test_within_or_and_not_pointcuts(self):
        events = []

        @Aspect
        class SelectionAspect:
            @Before(
                "within(*.SelectedService) or "
                "(bean(otherService) and not execution(* *.OtherService.skip(..)))"
            )
            def record(self, join_point):
                events.append((join_point.bean_name, join_point.method_name))

        class SelectedService:
            def run(self):
                return "selected"

        class OtherService:
            def run(self):
                return "other"

            def skip(self):
                return "skip"

        factory = _managed_beans(SelectionAspect, SelectedService, OtherService)
        assert factory.get_bean("selectedService").run() == "selected"
        other = factory.get_bean("otherService")
        assert other.run() == "other"
        assert other.skip() == "skip"
        assert events == [
            ("selectedService", "run"),
            ("otherService", "run"),
        ]

    def test_around_can_replace_arguments(self):
        @Aspect
        class NormalizeAspect:
            @Around("execution(* *.GreetingService.greet(..))")
            def normalize(self, join_point):
                return join_point.proceed(join_point.args[0].strip().title())

        class GreetingService:
            def greet(self, name):
                return f"Hello {name}"

        factory = _managed_beans(NormalizeAspect, GreetingService)
        assert factory.get_bean("greetingService").greet("  alice ") == "Hello Alice"

    def test_async_target_and_async_advice(self):
        events = []

        @Aspect
        class AsyncAspect:
            @Before("execution(* *.AsyncService.load(..))")
            async def before(self, join_point):
                await asyncio.sleep(0)
                events.append(join_point.method_name)

            @Around("execution(* *.AsyncService.load(..))")
            async def around(self, join_point):
                return (await join_point.proceed()) + 1

        class AsyncService:
            async def load(self):
                await asyncio.sleep(0)
                return 41

        factory = _managed_beans(AsyncAspect, AsyncService)
        service = factory.get_bean("asyncService")

        assert asyncio.run(service.load()) == 42
        assert events == ["load"]

    def test_unknown_pointcut_reference_fails_during_proxy_creation(self):
        @Aspect
        class BrokenAspect:
            @Before("missingPointcut()")
            def before(self):
                pass

        class TargetService:
            def run(self):
                return True

        factory = _managed_beans(BrokenAspect, TargetService)
        with pytest.raises(ValueError, match="Unknown pointcut reference"):
            factory.get_bean("targetService")

    def test_unsupported_pointcut_fails_during_proxy_creation(self):
        @Aspect
        class BrokenAspect:
            @Before("call(* *.TargetService.run(..))")
            def before(self):
                pass

        class TargetService:
            def run(self):
                return True

        factory = _managed_beans(BrokenAspect, TargetService)
        with pytest.raises(ValueError, match="Unsupported pointcut expression"):
            factory.get_bean("targetService")

    def test_boolean_pointcut_validates_all_branches(self):
        @Aspect
        class BrokenAspect:
            @Before("bean(noMatch) and call(* *.TargetService.run(..))")
            def before(self):
                pass

        class TargetService:
            def run(self):
                return True

        factory = _managed_beans(BrokenAspect, TargetService)
        with pytest.raises(ValueError, match="Unsupported pointcut expression"):
            factory.get_bean("targetService")

    def test_circular_pointcut_reference_is_rejected(self):
        @Aspect
        class BrokenAspect:
            @Pointcut("second()")
            def first(self):
                pass

            @Pointcut("first()")
            def second(self):
                pass

            @Before("first()")
            def before(self):
                pass

        class TargetService:
            def run(self):
                return True

        factory = _managed_beans(BrokenAspect, TargetService)
        with pytest.raises(ValueError, match="Circular pointcut reference"):
            factory.get_bean("targetService")

    def test_advice_can_collect_context_with_kwargs(self):
        captured = {}

        @Aspect
        class ContextAspect:
            @AfterReturning(
                "execution(* *.TargetService.run(..))", returning="response"
            )
            def returned(self, join_point, **context):
                captured.update(context)
                captured["method"] = join_point.method_name

        class TargetService:
            def run(self):
                return 42

        factory = _managed_beans(ContextAspect, TargetService)
        assert factory.get_bean("targetService").run() == 42
        assert captured["method"] == "run"
        assert captured["response"] == 42
        assert captured["result"] == 42


class TestPostAuthorize:
    def setup_method(self):
        SecurityContextHolder.clear_context()

    def teardown_method(self):
        SecurityContextHolder.clear_context()

    def test_return_object_owner_and_permission_expression(self):
        SecurityContextHolder.set_authentication({
            "principal": "alice",
            "permissions": ["document:read"],
        })

        @post_authorize_decorator(
            PostAuthorize(
                "returnObject.owner == authentication.name "
                "and hasPermission('document:read')"
            )
        )
        def load(owner):
            return {"owner": owner, "secret": "value"}

        assert load("alice")["secret"] == "value"
        with pytest.raises(AuthorizationError, match="Access denied"):
            load("bob")

    def test_managed_bean_path_and_return_object_alias(self):
        class DocumentService:
            @PostAuthorize("#returnObject.owner == authentication.name")
            def load(self, owner):
                return {"owner": owner}

        factory = _managed_beans(DocumentService)
        service = factory.get_bean("documentService")

        with pytest.raises(AuthenticationError, match="Authentication required"):
            service.load("alice")

        SecurityContextHolder.set_authentication({"principal": "alice"})
        assert service.load("alice") == {"owner": "alice"}
        with pytest.raises(AuthorizationError, match="Access denied"):
            service.load("bob")

    def test_post_authorize_runs_after_business_method(self):
        SecurityContextHolder.set_authentication({"principal": "alice"})
        calls = []

        @post_authorize_decorator(PostAuthorize("returnObject.owner == principal"))
        def load():
            calls.append("called")
            return {"owner": "bob"}

        with pytest.raises(AuthorizationError):
            load()
        assert calls == ["called"]

    def test_async_post_authorize(self):
        SecurityContextHolder.set_authentication({
            "principal": "admin",
            "roles": ["ROLE_ADMIN"],
        })

        @post_authorize_decorator(
            PostAuthorize("hasRole('ROLE_ADMIN') and returnObject == 42")
        )
        async def load():
            return 42

        assert asyncio.run(load()) == 42

    def test_object_return_value_and_subscript_expression(self):
        class Document:
            def __init__(self, owner):
                self.owner = owner

        SecurityContextHolder.set_authentication({"principal": "alice"})

        @post_authorize_decorator(
            PostAuthorize("returnObject[0].owner == principal")
        )
        def load():
            return [Document("alice")]

        assert load()[0].owner == "alice"

    def test_expression_rejects_executable_python(self):
        SecurityContextHolder.set_authentication({"principal": "alice"})

        @post_authorize_decorator(
            PostAuthorize("__import__('os').system('echo unsafe') == 0")
        )
        def load():
            return {"owner": "alice"}

        with pytest.raises(AuthorizationError):
            load()


class TestRecover:
    def test_selects_most_specific_recover_method_and_passes_exception(self):
        class RemoteService:
            def __init__(self):
                self.calls = 0

            @Retryable(value=(OSError,), max_attempts=2, backoff=0)
            def fetch(self, key):
                self.calls += 1
                raise ConnectionError("offline")

            @Recover(ConnectionError)
            def recover_connection(self, error, key):
                return f"connection:{key}:{error}"

            @Recover(OSError)
            def recover_io(self, error, key):
                return f"io:{key}:{error}"

        factory = _managed_beans(RemoteService)
        service = factory.get_bean("remoteService")

        assert service.fetch("orders") == "connection:orders:offline"
        assert service.calls == 2

    def test_infers_exception_type_from_recover_signature(self):
        class RemoteService:
            @Retryable(value=(ValueError,), max_attempts=1, backoff=0)
            def parse(self, value):
                raise ValueError("bad")

            @Recover
            def recover(self, error: ValueError, value):
                return f"fallback:{value}:{error}"

        factory = _managed_beans(RemoteService)
        assert factory.get_bean("remoteService").parse("x") == "fallback:x:bad"

    def test_recover_accepts_exception_tuple(self):
        class RemoteService:
            @Retryable(value=(LookupError,), max_attempts=1, backoff=0)
            def fetch(self):
                raise KeyError("missing")

            @Recover((KeyError, IndexError))
            def recover(self, error):
                return type(error).__name__

        factory = _managed_beans(RemoteService)
        assert factory.get_bean("remoteService").fetch() == "KeyError"

    def test_explicit_legacy_recover_name_remains_supported(self):
        class RemoteService:
            @Retryable(max_attempts=1, backoff=0, recover="fallback")
            def fetch(self, key):
                raise RuntimeError("offline")

            def fallback(self, key):
                return f"legacy:{key}"

        factory = _managed_beans(RemoteService)
        assert factory.get_bean("remoteService").fetch("x") == "legacy:x"

    def test_standalone_retry_decorator_discovers_recover(self):
        class RemoteService:
            @retryable_decorator(
                StandaloneRetryable(
                    value=(ConnectionError,), max_attempts=1, backoff=0
                )
            )
            def fetch(self, key):
                raise ConnectionError("offline")

            @Recover(ConnectionError)
            def recover(self, error, key):
                return f"standalone:{key}:{error}"

        assert RemoteService().fetch("x") == "standalone:x:offline"

    def test_unmatched_recover_re_raises_original_exception(self):
        class RemoteService:
            @Retryable(value=(RuntimeError,), max_attempts=1, backoff=0)
            def fetch(self):
                raise RuntimeError("offline")

            @Recover(ValueError)
            def fallback(self, error):
                return "not used"

        factory = _managed_beans(RemoteService)
        with pytest.raises(RuntimeError, match="offline"):
            factory.get_bean("remoteService").fetch()

    def test_ambiguous_recover_methods_are_rejected(self):
        class RemoteService:
            @Retryable(value=(RuntimeError,), max_attempts=1, backoff=0)
            def fetch(self, key):
                raise RuntimeError("offline")

            @Recover(RuntimeError)
            def first(self, error, key):
                return "first"

            @Recover(RuntimeError)
            def second(self, error, key):
                return "second"

        factory = _managed_beans(RemoteService)
        with pytest.raises(ValueError, match="Ambiguous @Recover methods"):
            factory.get_bean("remoteService").fetch("x")

    def test_recover_failure_is_not_silently_swallowed(self):
        class RemoteService:
            @Retryable(max_attempts=1, backoff=0)
            def fetch(self):
                raise RuntimeError("original")

            @Recover(RuntimeError)
            def fallback(self, error):
                raise LookupError("fallback failed")

        factory = _managed_beans(RemoteService)
        with pytest.raises(LookupError, match="fallback failed"):
            factory.get_bean("remoteService").fetch()

    def test_async_retry_uses_async_recover(self):
        class RemoteService:
            @Retryable(value=(TimeoutError,), max_attempts=2, backoff=0)
            async def fetch(self, key):
                raise TimeoutError("slow")

            @Recover(TimeoutError)
            async def recover(self, error, key):
                await asyncio.sleep(0)
                return f"async:{key}:{error}"

        factory = _managed_beans(RemoteService)
        service = factory.get_bean("remoteService")
        assert asyncio.run(service.fetch("x")) == "async:x:slow"
