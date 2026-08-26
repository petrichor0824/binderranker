#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Trusted in-process authorization for protected BinderRanker Tools.

External model arguments are JSON values.  This module requires an opaque,
single-use Python capability that can only be issued by a host-owned broker
after an independent user-confirmation event.  The capability is never part of
the public Tool request schema.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, NoReturn

from protein_design_agent.agent import tool_api
from protein_design_agent.agent.approval import ApprovalRecord
from protein_design_agent.agent.local_executor import CompletedLocalExecution
from protein_design_agent.agent.tool_api_contract import (
    ExecuteRankerToolRequest,
    RequestApprovalToolRequest,
)


RuntimeAuthorizationAction = Literal[
    "REQUEST_APPROVAL",
    "EXECUTE_RANKER",
]

DEFAULT_AUTHORIZATION_TTL = timedelta(minutes=5)

_RESOURCE_FILE_BY_ACTION: dict[RuntimeAuthorizationAction, str] = {
    "REQUEST_APPROVAL": "agent_prepare_manifest.json",
    "EXECUTE_RANKER": "approval.json",
}


class RuntimeAuthorizationError(RuntimeError):
    """A trusted runtime authorization could not be issued or consumed."""


@dataclass(frozen=True, slots=True)
class RuntimeAuthorizationGrant:
    """Opaque bearer capability passed only inside a trusted host runtime."""

    _broker_id: str = field(repr=False)
    _authorization_id: str = field(repr=False)

    def __repr__(self) -> str:
        return "RuntimeAuthorizationGrant(<opaque>)"

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "RuntimeAuthorizationGrant cannot be serialized"
        )


@dataclass(frozen=True, slots=True)
class _PendingAuthorization:
    action: RuntimeAuthorizationAction
    bundle_key: str
    resource_path: Path
    resource_sha256: str

    authorized_by: str
    approval_note: str
    acknowledge_smoke_test: bool

    issued_at_utc: datetime
    expires_at_utc: datetime


@dataclass(frozen=True, slots=True)
class _ConsumedAuthorization:
    authorized_by: str
    approval_note: str
    acknowledge_smoke_test: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bundle_key(path: Path) -> tuple[Path, str]:
    resolved = Path(path).resolve()
    return resolved, os.path.normcase(str(resolved))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    try:
        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeAuthorizationError(
            "授权所绑定的审核文件无法读取。"
        ) from exc

    return digest.hexdigest()


class TrustedAuthorizationBroker:
    """Host-owned issuer and atomic consumer of runtime capabilities."""

    def __init__(
        self,
        *,
        authorization_ttl: timedelta = DEFAULT_AUTHORIZATION_TTL,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if authorization_ttl.total_seconds() <= 0:
            raise ValueError("authorization_ttl must be positive")

        self._authorization_ttl = authorization_ttl
        self._clock = clock
        self._broker_id = secrets.token_urlsafe(24)
        self._pending: dict[str, _PendingAuthorization] = {}
        self._lock = threading.Lock()

    def _current_time(self) -> datetime:
        current = self._clock()

        if current.tzinfo is None or current.utcoffset() is None:
            raise RuntimeAuthorizationError(
                "可信授权时钟必须返回带时区的时间。"
            )

        return current.astimezone(timezone.utc)

    def _issue(
        self,
        *,
        action: RuntimeAuthorizationAction,
        bundle_dir: Path,
        authorized_by: str,
        user_confirmed: bool,
        approval_note: str = "",
        acknowledge_smoke_test: bool = False,
    ) -> RuntimeAuthorizationGrant:
        if user_confirmed is not True:
            raise RuntimeAuthorizationError(
                "宿主尚未获得真实用户确认，不能签发可信授权。"
            )

        if not isinstance(authorized_by, str):
            raise RuntimeAuthorizationError(
                "可信授权必须包含字符串形式的用户审计标识。"
            )

        clean_authorized_by = authorized_by.strip()
        if not clean_authorized_by:
            raise RuntimeAuthorizationError(
                "可信授权必须包含非空的用户审计标识。"
            )

        bundle, bundle_key = _bundle_key(bundle_dir)
        if not bundle.is_dir():
            raise RuntimeAuthorizationError(
                "可信授权所绑定的任务目录不存在。"
            )

        resource_path = (
            bundle / _RESOURCE_FILE_BY_ACTION[action]
        ).resolve()
        if not resource_path.is_file():
            raise RuntimeAuthorizationError(
                "可信授权所需的审核文件不存在。"
            )

        resource_sha256 = _sha256_file(resource_path)
        issued_at = self._current_time()
        pending = _PendingAuthorization(
            action=action,
            bundle_key=bundle_key,
            resource_path=resource_path,
            resource_sha256=resource_sha256,
            authorized_by=clean_authorized_by,
            approval_note=approval_note,
            acknowledge_smoke_test=acknowledge_smoke_test,
            issued_at_utc=issued_at,
            expires_at_utc=(
                issued_at + self._authorization_ttl
            ),
        )

        with self._lock:
            expired_ids = [
                key
                for key, value in self._pending.items()
                if issued_at >= value.expires_at_utc
            ]
            for expired_id in expired_ids:
                self._pending.pop(expired_id, None)

            authorization_id = "rta_" + secrets.token_hex(24)
            while authorization_id in self._pending:
                authorization_id = "rta_" + secrets.token_hex(24)
            self._pending[authorization_id] = pending

        return RuntimeAuthorizationGrant(
            _broker_id=self._broker_id,
            _authorization_id=authorization_id,
        )

    def issue_plan_approval(
        self,
        *,
        bundle_dir: Path,
        authorized_by: str,
        user_confirmed: bool = False,
        approval_note: str = "",
        acknowledge_smoke_test: bool = False,
    ) -> RuntimeAuthorizationGrant:
        """Issue one capability after host-confirmed plan approval."""

        return self._issue(
            action="REQUEST_APPROVAL",
            bundle_dir=bundle_dir,
            authorized_by=authorized_by,
            user_confirmed=user_confirmed,
            approval_note=approval_note,
            acknowledge_smoke_test=acknowledge_smoke_test,
        )

    def issue_execution(
        self,
        *,
        bundle_dir: Path,
        authorized_by: str,
        user_confirmed: bool = False,
    ) -> RuntimeAuthorizationGrant:
        """Issue one capability after a separate execution confirmation."""

        return self._issue(
            action="EXECUTE_RANKER",
            bundle_dir=bundle_dir,
            authorized_by=authorized_by,
            user_confirmed=user_confirmed,
        )

    def _consume(
        self,
        *,
        grant: RuntimeAuthorizationGrant,
        expected_action: RuntimeAuthorizationAction,
        bundle_dir: Path,
    ) -> _ConsumedAuthorization:
        if not isinstance(grant, RuntimeAuthorizationGrant):
            raise RuntimeAuthorizationError(
                "受保护 Tool 需要宿主签发的不透明授权对象。"
            )

        if not hmac.compare_digest(
            grant._broker_id,
            self._broker_id,
        ):
            raise RuntimeAuthorizationError(
                "授权对象不属于当前可信 runtime。"
            )

        _bundle, expected_bundle_key = _bundle_key(bundle_dir)

        # Pop first so every attempted use is one-shot.  The lock makes two
        # concurrent consumers race for exactly one successful ownership claim.
        with self._lock:
            pending = self._pending.pop(
                grant._authorization_id,
                None,
            )

        if pending is None:
            raise RuntimeAuthorizationError(
                "授权对象无效、已使用或已撤销。"
            )

        if pending.action != expected_action:
            raise RuntimeAuthorizationError(
                "授权对象的动作范围与当前 Tool 不匹配。"
            )

        if not hmac.compare_digest(
            pending.bundle_key,
            expected_bundle_key,
        ):
            raise RuntimeAuthorizationError(
                "授权对象绑定了其他任务目录。"
            )

        if self._current_time() >= pending.expires_at_utc:
            raise RuntimeAuthorizationError(
                "可信授权已经过期，请重新获得用户确认。"
            )

        actual_sha256 = _sha256_file(pending.resource_path)
        if not hmac.compare_digest(
            pending.resource_sha256,
            actual_sha256,
        ):
            raise RuntimeAuthorizationError(
                "用户确认后审核文件发生变化，授权已失效。"
            )

        return _ConsumedAuthorization(
            authorized_by=pending.authorized_by,
            approval_note=pending.approval_note,
            acknowledge_smoke_test=(
                pending.acknowledge_smoke_test
            ),
        )


class TrustedToolRuntime:
    """Safe protected-Tool entry points owned by an external host adapter."""

    def __init__(self, broker: TrustedAuthorizationBroker) -> None:
        if not isinstance(broker, TrustedAuthorizationBroker):
            raise TypeError("broker must be a TrustedAuthorizationBroker")

        self._broker = broker

    def request_approval(
        self,
        *,
        request: RequestApprovalToolRequest,
        authorization: RuntimeAuthorizationGrant,
    ) -> ApprovalRecord:
        """Consume a plan-approval capability and call the stable Tool API."""

        if not isinstance(request, RequestApprovalToolRequest):
            raise RuntimeAuthorizationError(
                "request_approval 请求未通过公开 schema 验证。"
            )

        consumed = self._broker._consume(
            grant=authorization,
            expected_action="REQUEST_APPROVAL",
            bundle_dir=request.bundle_dir,
        )

        return tool_api.request_approval(
            bundle_dir=request.bundle_dir,
            approved_by=consumed.authorized_by,
            approval_confirmed=True,
            approval_note=consumed.approval_note,
            acknowledge_smoke_test=(
                consumed.acknowledge_smoke_test
            ),
        )

    def execute_ranker(
        self,
        *,
        request: ExecuteRankerToolRequest,
        authorization: RuntimeAuthorizationGrant,
    ) -> CompletedLocalExecution:
        """Consume an execution capability and call the stable Tool API."""

        if not isinstance(request, ExecuteRankerToolRequest):
            raise RuntimeAuthorizationError(
                "execute_ranker 请求未通过公开 schema 验证。"
            )

        self._broker._consume(
            grant=authorization,
            expected_action="EXECUTE_RANKER",
            bundle_dir=request.bundle_dir,
        )

        return tool_api.execute_ranker(
            bundle_dir=request.bundle_dir,
            execution_confirmed=True,
        )


__all__ = [
    "DEFAULT_AUTHORIZATION_TTL",
    "RuntimeAuthorizationAction",
    "RuntimeAuthorizationError",
    "RuntimeAuthorizationGrant",
    "TrustedAuthorizationBroker",
    "TrustedToolRuntime",
]
