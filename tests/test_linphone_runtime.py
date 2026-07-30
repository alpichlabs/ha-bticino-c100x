"""Linphone runtime contract tests."""

import hashlib

import pytest

from custom_components.bticino_c100x.linphone_runtime import (
    LinphoneRuntimeError,
    MonitoringRequest,
    runtime_supported,
    verify_runtime,
)


def test_monitoring_request_matches_vendor_application() -> None:
    request = MonitoringRequest.for_external_unit("external-unit-uuid")

    assert request.target == "c100x"
    assert request.device_address == "external-unit-uuid"
    assert request.video_direction == "recv_only"
    assert request.audio_direction == "send_recv"
    assert request.media_encryption == "srtp"
    assert request.media_encryption_mandatory is True
    assert request.microphone_enabled is False
    assert request.setup_timeout == 15
    assert request.no_media_timeout == 10


def test_runtime_support_is_amd64_only() -> None:
    assert runtime_supported("x86_64")
    assert runtime_supported("amd64")
    assert not runtime_supported("aarch64")


def test_runtime_checksum_is_mandatory_and_verified() -> None:
    data = b"runtime"
    verify_runtime(data, hashlib.sha256(data).hexdigest())
    with pytest.raises(LinphoneRuntimeError, match="checksum mismatch"):
        verify_runtime(data, "0" * 64)
    with pytest.raises(LinphoneRuntimeError, match="not published"):
        verify_runtime(data, "")
