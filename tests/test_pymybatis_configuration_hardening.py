"""Regression tests for malformed PyMyBatis configuration sections."""

import pytest

from spring.orm.pymybatis.configuration import Configuration


@pytest.mark.parametrize(
    "section",
    [
        "cache",
        "transaction",
        "pool",
        "security",
        "performance",
        "batch",
        "logging",
        "pagination",
        "metrics",
    ],
)
@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_malformed_optional_sections_fall_back_to_defaults(section, value):
    configuration = Configuration()

    # A malformed optional section must not turn startup into an AttributeError.
    configuration.load_config({section: value})

    assert configuration.pool_max_size == 20
    assert configuration.default_transaction_isolation == "READ_COMMITTED"


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_malformed_datasource_sections_are_ignored(value):
    configuration = Configuration()

    configuration.load_config({"datasource": value})

    assert configuration.datasources == {}
    assert configuration.default_datasource == "default"


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_malformed_multi_datasource_sections_are_ignored(value):
    configuration = Configuration()

    configuration.load_config({"datasources": value})

    assert configuration.datasources == {}


def test_malformed_nested_sections_and_lists_are_safe():
    configuration = Configuration()

    configuration.load_config(
        {
            "datasources": {
                "invalid": None,
                "default": {"driver": "sqlite", 1: "value"},
            },
            "cache": {"redis": []},
            "pool": {"circuit_breaker": "invalid"},
            "mappers": ["UserMapper", None, 7],
            "mapper_paths": ["mapper.xml", None, {"path": "other.xml"}],
            "default_datasource": [],
            "dialect": [],
        }
    )

    assert list(configuration.datasources) == ["default"]
    assert configuration.datasources["default"]["1"] == "value"
    assert configuration.redis_cache_config == {}
    assert configuration.mappers == ["UserMapper"]
    assert configuration.mapper_locations == ["mapper.xml"]
    assert configuration.default_datasource == "default"
    assert configuration.dialect == "mysql"
    # ``to_dict`` must remain safe after filtering malformed entries.
    assert configuration.to_dict()["datasources"] == {
        "default": {"driver": "sqlite", "1": "value"}
    }


def test_empty_and_valid_sqlite_configuration_still_work():
    configuration = Configuration()
    configuration.load_config({})
    assert configuration.datasources == {}

    configuration.load_config(
        {
            "datasource": {"driver": "sqlite", "database": ":memory:"},
            "pool": {"min_size": "1", "max_size": "1"},
        }
    )
    assert configuration.dialect == "sqlite"
    assert configuration.get_datasource()["database"] == ":memory:"
    assert configuration.pool_min_size == 1
    assert configuration.pool_max_size == 1


def test_sql_session_factory_is_closed_by_container_destroy(tmp_path):
    """Container shutdown must release the pool-owned database handle."""
    from spring.context.bean_factory import BeanFactory
    from spring.orm.mybatis_integration import MyBatisConfigurer
    from spring.orm.pymybatis import build_session_factory

    database_path = tmp_path / "shutdown.sqlite"
    session_factory = build_session_factory(
        {
            "datasource": {
                "driver": "sqlite",
                "database": str(database_path),
            },
            "pool": {"min_size": 1, "max_size": 1},
        }
    )

    configurer = MyBatisConfigurer.__new__(MyBatisConfigurer)
    configurer.sql_session_factory = session_factory
    configurer._mapper_registry = {}
    bean_factory = BeanFactory()
    try:
        configurer._register_beans(bean_factory)

        bean_factory.destroy_all()

        assert session_factory.connection_pool.get_pool_stats()["closed"] is True
    finally:
        # Keep the test robust if registration/assertion fails midway.
        session_factory.close()
