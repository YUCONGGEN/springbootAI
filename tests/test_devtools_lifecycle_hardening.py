"""Regression tests for DevTools and application shutdown lifecycle hardening."""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import Mock, patch

import pytest

from springbootai.annotations.enterprise import EnableDevTools
from springbootai.cloud import discovery
from springbootai.devtools import FileWatcher, RestartTrigger, create_devtools_watcher
from springbootai.main import SpringApplication


def test_devtools_rejects_non_finite_intervals_and_false_string(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        FileWatcher([str(tmp_path)], poll_interval=float("nan"))
    with pytest.raises(ValueError, match="negative"):
        RestartTrigger(quiet_period=float("inf"))
    assert create_devtools_watcher({
        "spring": {"devtools": {"restart": {"enabled": "false"}}},
    }) is None


def test_devtools_factory_accepts_snake_case_config_and_zero_arg_callback(tmp_path):
    callback_called = threading.Event()
    config = {
        "spring": {
            "devtools": {
                "restart": {
                    "enabled": True,
                    "watch_dirs": [str(tmp_path)],
                    "exclude_dirs": ["generated"],
                    "poll_interval": 0.02,
                    "quiet_period": 0.01,
                }
            }
        }
    }

    watcher = create_devtools_watcher(
        config, restart_callback=callback_called.set)
    try:
        assert watcher is not None
        assert watcher.watch_dirs == [tmp_path]
        assert watcher.exclude_dirs == {"generated"}
        assert watcher.poll_interval == 0.02

        (tmp_path / "created.py").write_text("value = 1\n", encoding="utf-8")
        assert callback_called.wait(2), "zero-argument debounce callback was not invoked"
    finally:
        if watcher is not None:
            watcher.stop()


def test_file_watcher_detects_non_increasing_mtime(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("value = 1\n", encoding="utf-8")
    original_mtime = source.stat().st_mtime
    changed = threading.Event()

    watcher = FileWatcher([str(tmp_path)], poll_interval=0.02)
    watcher.start(lambda _files: changed.set())
    try:
        source.write_text("value = 2\n", encoding="utf-8")
        os.utime(source, (original_mtime - 10, original_mtime - 10))
        assert changed.wait(2), "content replacement with an older mtime was missed"
    finally:
        watcher.stop()


def test_file_watcher_stop_interrupts_long_poll_and_cancels_pending_callback(tmp_path):
    callback_called = threading.Event()
    trigger = RestartTrigger(
        quiet_period=0.2, restart_callback=callback_called.set)
    watcher = FileWatcher([str(tmp_path)], poll_interval=30)
    watcher._restart_trigger = trigger
    watcher.start(trigger.on_file_changed)
    trigger.on_file_changed([str(tmp_path / "changed.py")])

    started = time.perf_counter()
    watcher.stop()
    elapsed = time.perf_counter() - started

    assert elapsed < 1
    assert watcher._thread is not None and not watcher._thread.is_alive()
    assert not callback_called.wait(0.3)


def test_enable_devtools_annotation_overrides_without_mutating_live_config():
    @EnableDevTools(
        watch_dirs=["src", "config"],
        poll_interval=0.25,
        exclude_dirs=["generated"],
    )
    class DemoApplication:
        pass

    application = SpringApplication(DemoApplication)
    application.logger = Mock()
    watcher = Mock()
    config = {
        "spring": {
            "devtools": {
                "restart": {
                    "enabled": False,
                    "watch-dirs": ["from-yaml"],
                    "poll-interval": 1.0,
                }
            }
        }
    }

    with patch(
        "springbootai.devtools.create_devtools_watcher",
        return_value=watcher,
    ) as create_watcher:
        application._init_devtools(config, config["spring"], fail_fast=False)

    passed_config = create_watcher.call_args.args[0]
    restart = passed_config["spring"]["devtools"]["restart"]
    assert restart["enabled"] is True
    assert restart["watch-dirs"] == ["src", "config"]
    assert restart["poll-interval"] == 0.25
    assert restart["exclude"] == ["generated"]
    assert config["spring"]["devtools"]["restart"] == {
        "enabled": False,
        "watch-dirs": ["from-yaml"],
        "poll-interval": 1.0,
    }

    # RestartTrigger invokes this callback without arguments.  It must report
    # the external-reloader boundary without raising or claiming a restart.
    callback = create_watcher.call_args.kwargs["restart_callback"]
    callback()
    messages = [call.args[0] for call in application.logger.info.call_args_list]
    assert any("external reloader" in message for message in messages)
    assert application._devtools_watcher is watcher

    application._stop_devtools_watcher()
    application._stop_devtools_watcher()
    watcher.stop.assert_called_once_with()


def test_start_failure_cleanup_stops_application_owned_watcher():
    application = SpringApplication(type("DemoApplication", (), {}))
    application.logger = Mock()
    watcher = Mock()
    application._devtools_watcher = watcher
    application.application_context = None

    application._cleanup_after_start_failure()

    watcher.stop.assert_called_once_with()
    assert application._devtools_watcher is None


def test_discovery_and_admin_shutdown_use_independent_lifecycles():
    class Context:
        @staticmethod
        def get_config():
            return {
                "spring": {"application": {"name": "orders-service"}},
            }

    application = SpringApplication(type("DemoApplication", (), {}))
    application.logger = Mock()
    application.application_context = Context()
    application._discovery_registered = True
    application._discovery_registration = None
    admin_client = Mock()
    application._admin_client = admin_client

    nacos_client = Mock()
    nacos_client._ip = "127.0.0.7"
    nacos_client._port = 8123
    with patch.object(discovery, "nacos_client", nacos_client):
        application._deregister_discovery_service()

    nacos_client.deregister_service.assert_called_once_with(
        "orders-service", "127.0.0.7", 8123)
    assert application._discovery_registered is False
    assert application._discovery_registration is None
    # Discovery shutdown must not consume a separately owned Admin client.
    assert application._admin_client is admin_client

    application._deregister_admin_client()
    admin_client.deregister.assert_called_once_with()
    admin_client.close.assert_called_once_with()
    assert application._admin_client is None
