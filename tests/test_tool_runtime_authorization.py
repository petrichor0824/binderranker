import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from protein_design_agent.agent import tool_api
from protein_design_agent.agent.tool_api_contract import (
    ExecuteRankerToolRequest,
    RequestApprovalToolRequest,
)
from protein_design_agent.agent.tool_runtime_authorization import (
    RuntimeAuthorizationError,
    RuntimeAuthorizationGrant,
    TrustedAuthorizationBroker,
    TrustedToolRuntime,
)


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(
            2026,
            8,
            26,
            9,
            0,
            tzinfo=timezone.utc,
        )

    def __call__(self) -> datetime:
        return self.current


@pytest.fixture
def prepared_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "agent_prepare_manifest.json").write_text(
        '{"status":"READY_FOR_REVIEW"}',
        encoding="utf-8",
    )
    (bundle / "approval.json").write_text(
        '{"status":"APPROVED"}',
        encoding="utf-8",
    )
    return bundle


def issue_plan_grant(
    broker: TrustedAuthorizationBroker,
    bundle: Path,
):
    return broker.issue_plan_approval(
        bundle_dir=bundle,
        authorized_by="local-user",
        user_confirmed=True,
        approval_note="reviewed in host UI",
        acknowledge_smoke_test=True,
    )


def issue_execution_grant(
    broker: TrustedAuthorizationBroker,
    bundle: Path,
):
    return broker.issue_execution(
        bundle_dir=bundle,
        authorized_by="local-user",
        user_confirmed=True,
    )


def test_broker_rejects_missing_real_user_confirmation(
    prepared_bundle: Path,
) -> None:
    broker = TrustedAuthorizationBroker()

    with pytest.raises(
        RuntimeAuthorizationError,
        match="尚未获得真实用户确认",
    ):
        broker.issue_plan_approval(
            bundle_dir=prepared_bundle,
            authorized_by="local-user",
            user_confirmed=False,
        )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="尚未获得真实用户确认",
    ):
        broker.issue_execution(
            bundle_dir=prepared_bundle,
            authorized_by="local-user",
        )


def test_grant_is_opaque_and_not_json_serializable(
    prepared_bundle: Path,
) -> None:
    broker = TrustedAuthorizationBroker()
    grant = issue_plan_grant(broker, prepared_bundle)

    assert repr(grant) == "RuntimeAuthorizationGrant(<opaque>)"
    with pytest.raises(TypeError):
        json.dumps(grant)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(grant)


def test_plan_grant_injects_host_facts_into_existing_tool_api(
    prepared_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    expected = object()

    def fake_request_approval(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        tool_api,
        "request_approval",
        fake_request_approval,
    )

    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_plan_grant(broker, prepared_bundle)
    request = RequestApprovalToolRequest(
        bundle_dir=prepared_bundle,
    )

    assert runtime.request_approval(
        request=request,
        authorization=grant,
    ) is expected
    assert captured == {
        "bundle_dir": prepared_bundle,
        "approved_by": "local-user",
        "approval_confirmed": True,
        "approval_note": "reviewed in host UI",
        "acknowledge_smoke_test": True,
    }


def test_execution_grant_injects_confirmation_into_existing_tool_api(
    prepared_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    expected = object()

    def fake_execute_ranker(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        tool_api,
        "execute_ranker",
        fake_execute_ranker,
    )

    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_execution_grant(broker, prepared_bundle)

    result = runtime.execute_ranker(
        request=ExecuteRankerToolRequest(
            bundle_dir=prepared_bundle,
        ),
        authorization=grant,
    )

    assert result is expected
    assert captured == {
        "bundle_dir": prepared_bundle,
        "execution_confirmed": True,
    }


def test_grant_is_single_use_even_when_first_tool_call_succeeds(
    prepared_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tool_api,
        "request_approval",
        lambda **_kwargs: object(),
    )
    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_plan_grant(broker, prepared_bundle)
    request = RequestApprovalToolRequest(
        bundle_dir=prepared_bundle,
    )

    runtime.request_approval(
        request=request,
        authorization=grant,
    )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="已使用",
    ):
        runtime.request_approval(
            request=request,
            authorization=grant,
        )


def test_wrong_action_attempt_consumes_grant(
    prepared_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tool_api,
        "request_approval",
        lambda **_kwargs: object(),
    )
    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_plan_grant(broker, prepared_bundle)

    with pytest.raises(
        RuntimeAuthorizationError,
        match="动作范围",
    ):
        runtime.execute_ranker(
            request=ExecuteRankerToolRequest(
                bundle_dir=prepared_bundle,
            ),
            authorization=grant,
        )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="已使用",
    ):
        runtime.request_approval(
            request=RequestApprovalToolRequest(
                bundle_dir=prepared_bundle,
            ),
            authorization=grant,
        )


def test_wrong_bundle_attempt_consumes_grant(
    prepared_bundle: Path,
    tmp_path: Path,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "agent_prepare_manifest.json").write_text(
        "{}",
        encoding="utf-8",
    )

    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_plan_grant(broker, prepared_bundle)

    with pytest.raises(
        RuntimeAuthorizationError,
        match="其他任务目录",
    ):
        runtime.request_approval(
            request=RequestApprovalToolRequest(
                bundle_dir=other,
            ),
            authorization=grant,
        )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="已使用",
    ):
        runtime.request_approval(
            request=RequestApprovalToolRequest(
                bundle_dir=prepared_bundle,
            ),
            authorization=grant,
        )


def test_grant_from_another_broker_is_rejected_without_consuming_it(
    prepared_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = object()
    monkeypatch.setattr(
        tool_api,
        "request_approval",
        lambda **_kwargs: expected,
    )

    issuing_broker = TrustedAuthorizationBroker()
    other_runtime = TrustedToolRuntime(
        TrustedAuthorizationBroker()
    )
    grant = issue_plan_grant(
        issuing_broker,
        prepared_bundle,
    )
    request = RequestApprovalToolRequest(
        bundle_dir=prepared_bundle,
    )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="不属于当前",
    ):
        other_runtime.request_approval(
            request=request,
            authorization=grant,
        )

    assert TrustedToolRuntime(
        issuing_broker
    ).request_approval(
        request=request,
        authorization=grant,
    ) is expected


def test_constructed_grant_cannot_bypass_broker_registry(
    prepared_bundle: Path,
) -> None:
    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    real_grant = issue_plan_grant(broker, prepared_bundle)
    forged = RuntimeAuthorizationGrant(
        _broker_id=real_grant._broker_id,
        _authorization_id="rta_forged",
    )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="无效",
    ):
        runtime.request_approval(
            request=RequestApprovalToolRequest(
                bundle_dir=prepared_bundle,
            ),
            authorization=forged,
        )


def test_expired_grant_is_rejected_and_consumed(
    prepared_bundle: Path,
) -> None:
    clock = MutableClock()
    broker = TrustedAuthorizationBroker(
        authorization_ttl=timedelta(seconds=30),
        clock=clock,
    )
    runtime = TrustedToolRuntime(broker)
    grant = issue_execution_grant(broker, prepared_bundle)
    clock.current += timedelta(seconds=30)
    request = ExecuteRankerToolRequest(
        bundle_dir=prepared_bundle,
    )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="已经过期",
    ):
        runtime.execute_ranker(
            request=request,
            authorization=grant,
        )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="已使用",
    ):
        runtime.execute_ranker(
            request=request,
            authorization=grant,
        )


@pytest.mark.parametrize(
    ("action", "resource_name"),
    (
        ("plan", "agent_prepare_manifest.json"),
        ("execute", "approval.json"),
    ),
)
def test_review_resource_change_invalidates_grant(
    prepared_bundle: Path,
    action: str,
    resource_name: str,
) -> None:
    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)

    if action == "plan":
        grant = issue_plan_grant(broker, prepared_bundle)
        request = RequestApprovalToolRequest(
            bundle_dir=prepared_bundle,
        )
        invoke = lambda: runtime.request_approval(
            request=request,
            authorization=grant,
        )
    else:
        grant = issue_execution_grant(broker, prepared_bundle)
        request = ExecuteRankerToolRequest(
            bundle_dir=prepared_bundle,
        )
        invoke = lambda: runtime.execute_ranker(
            request=request,
            authorization=grant,
        )

    (prepared_bundle / resource_name).write_text(
        '{"changed":true}',
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeAuthorizationError,
        match="审核文件发生变化",
    ):
        invoke()


def test_concurrent_consumers_allow_exactly_one_tool_call(
    prepared_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_request_approval(**_kwargs):
        calls.append(1)
        return "approved"

    monkeypatch.setattr(
        tool_api,
        "request_approval",
        fake_request_approval,
    )

    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_plan_grant(broker, prepared_bundle)
    request = RequestApprovalToolRequest(
        bundle_dir=prepared_bundle,
    )

    def invoke():
        try:
            return runtime.request_approval(
                request=request,
                authorization=grant,
            )
        except RuntimeAuthorizationError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: invoke(), range(2)))

    assert calls == [1]
    assert outcomes.count("approved") == 1
    assert sum(
        isinstance(value, RuntimeAuthorizationError)
        for value in outcomes
    ) == 1


def test_runtime_rejects_unvalidated_request_objects(
    prepared_bundle: Path,
) -> None:
    broker = TrustedAuthorizationBroker()
    runtime = TrustedToolRuntime(broker)
    grant = issue_plan_grant(broker, prepared_bundle)

    with pytest.raises(
        RuntimeAuthorizationError,
        match="未通过公开 schema",
    ):
        runtime.request_approval(
            request={  # type: ignore[arg-type]
                "bundle_dir": str(prepared_bundle)
            },
            authorization=grant,
        )


def test_broker_requires_aware_clock_and_positive_ttl(
    prepared_bundle: Path,
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        TrustedAuthorizationBroker(
            authorization_ttl=timedelta(0)
        )

    broker = TrustedAuthorizationBroker(
        clock=lambda: datetime(2026, 8, 26, 9, 0)
    )
    with pytest.raises(
        RuntimeAuthorizationError,
        match="带时区",
    ):
        issue_plan_grant(broker, prepared_bundle)


def test_broker_rejects_empty_authorized_by(
    prepared_bundle: Path,
) -> None:
    broker = TrustedAuthorizationBroker()

    with pytest.raises(
        RuntimeAuthorizationError,
        match="非空",
    ):
        broker.issue_plan_approval(
            bundle_dir=prepared_bundle,
            authorized_by="   ",
            user_confirmed=True,
        )


def test_authorization_documentation_preserves_host_boundary() -> None:
    document = Path("docs/TOOL_API_CONTRACT.md").read_text(encoding="utf-8")

    for required in (
        "TrustedAuthorizationBroker",
        "TrustedToolRuntime",
        "must never be registered as model-callable tools",
        "atomically consumable once",
        "five minutes",
        "SHA256",
        "do not survive process restart",
        "does not claim",
    ):
        assert required in document
