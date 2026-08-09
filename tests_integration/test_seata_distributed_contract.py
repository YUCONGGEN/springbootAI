import os

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.seata_integration]

if os.getenv("RUN_SEATA_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "set RUN_SEATA_INTEGRATION_TESTS=1 with a compatible Seata SDK and Server",
        allow_module_level=True,
    )


def test_real_seata_begin_commit_and_rollback_contract():
    from spring.cloud.seata import SeataTransactionManager

    manager = SeataTransactionManager()
    manager.configure(
        server_addr=os.getenv("SEATA_SERVER", "127.0.0.1:8091"),
        application_id=os.environ["SEATA_APP_ID"],
        transaction_group=os.getenv("SEATA_TX_GROUP", "my_tx_group"),
        mode="distributed",
    )

    committed_xid = manager.begin_transaction(name="springpy-contract-commit")
    assert committed_xid
    assert manager.get_current_tx_id() == committed_xid
    assert manager.commit_transaction(committed_xid) is True
    assert manager.is_in_transaction() is False

    rolled_back_xid = manager.begin_transaction(name="springpy-contract-rollback")
    assert rolled_back_xid
    assert manager.rollback_transaction(rolled_back_xid) is True
    assert manager.is_in_transaction() is False
