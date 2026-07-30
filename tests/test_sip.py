"""SIP protocol unit tests."""

import json
from unittest.mock import AsyncMock, MagicMock

from custom_components.bticino_c100x.models import SipAccount
from custom_components.bticino_c100x.sip import (
    SipClient,
    SipFramer,
    SipMessage,
    digest_authorization,
    parse_digest_challenge,
)


def test_framer_handles_fragmented_body() -> None:
    framer = SipFramer()
    assert framer.feed(b"MESSAGE sip:x SIP/2.0\r\nCall-ID: abc\r\nContent-Length: 5\r\n\r\nhe") == []
    messages = framer.feed(b"llo")
    assert len(messages) == 1
    assert messages[0].method == "MESSAGE"
    assert messages[0].headers["call-id"] == "abc"
    assert messages[0].body == b"hello"


def test_framer_handles_multiple_messages() -> None:
    raw = b"SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\n" * 2
    messages = SipFramer().feed(raw)
    assert [message.status_code for message in messages] == [200, 200]


def test_framer_preserves_complete_record_route_set() -> None:
    raw = (
        b"SIP/2.0 200 OK\r\n"
        b"Record-Route: <sip:first.example;lr>\r\n"
        b"Record-Route: <sip:second.example;lr>\r\n"
        b"Content-Length: 0\r\n\r\n"
    )

    message = SipFramer().feed(raw)[0]

    assert message.headers["record-route"] == (
        "<sip:first.example;lr>, <sip:second.example;lr>"
    )


def test_provisional_response_is_identified_before_final_response() -> None:
    raw = (
        b"SIP/2.0 100 Trying\r\nCall-ID: abc\r\nCSeq: 2 MESSAGE\r\nContent-Length: 0\r\n\r\n"
        b"SIP/2.0 200 OK\r\nCall-ID: abc\r\nCSeq: 2 MESSAGE\r\nContent-Length: 0\r\n\r\n"
    )
    messages = SipFramer().feed(raw)
    assert [message.status_code for message in messages] == [100, 200]


def test_digest_matches_rfc_example(monkeypatch) -> None:
    monkeypatch.setattr("custom_components.bticino_c100x.sip.secrets.token_hex", lambda _: "0a4f113b")
    account = SipAccount("1", "Mufasa@testrealm@host.com", "Circle Of Life", "oid")
    challenge = parse_digest_challenge(
        'Digest realm="testrealm@host.com", nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", qop="auth"'
    )
    value = digest_authorization(account=account, method="GET", uri="/dir/index.html", challenge=challenge)
    assert 'response="6629fae49393a05397450978507c4ef1"' in value


async def test_close_ignores_tls_shutdown_failure() -> None:
    account = SipAccount("1", "user@example.com", "secret", "oid")
    client = SipClient(account, "certificate", "key", "ca", AsyncMock())
    writer = MagicMock()
    writer.wait_closed = AsyncMock(side_effect=OSError("TLS peer closed first"))
    client._writer = writer

    await client.close()

    writer.close.assert_called_once_with()
    assert client._writer is None


async def test_release_door_matches_classe_100x_json_rpc_message(monkeypatch) -> None:
    monkeypatch.setattr("custom_components.bticino_c100x.sip.secrets.randbelow", lambda _: 12345)
    account = SipAccount("1", "user@registration.bs.iotleg.com", "secret", "oid")
    client = SipClient(account, "certificate", "key", "ca", AsyncMock())
    client._authenticated_request = AsyncMock(return_value=SipMessage("SIP/2.0 200 OK", {}))

    await client.release_door("lock-module-id", "gateway-module-id")

    client._authenticated_request.assert_awaited_once()
    method, uri, body = client._authenticated_request.await_args.args
    assert method == "MESSAGE"
    assert uri == "sip:c100x@gateway-module-id.bs.iotleg.com"
    assert json.loads(body) == {
        "jsonrpc": "2.0",
        "id": "12345",
        "method": "lock.setStatus",
        "params": [
            {
                "status": "open",
                "receiver": {"plant": {"coal": {"id": "lock-module-id"}}},
            }
        ],
    }


async def test_invite_is_accepted_only_from_selected_classe_100x_gateway() -> None:
    account = SipAccount("1", "user@gateway.bs.iotleg.com", "secret", "oid")
    on_ring = AsyncMock()
    client = SipClient(account, "certificate", "key", "ca", on_ring)
    client._respond = AsyncMock()
    client._delayed_busy = AsyncMock()

    valid = SipMessage(
        "INVITE sip:user SIP/2.0",
        {"from": "<sip:c100x@gateway.bs.iotleg.com>", "call-id": "valid"},
    )
    await client._handle_request(valid)

    on_ring.assert_awaited_once_with({"call_id": "valid"})
    client._respond.assert_awaited_once_with(valid, 180, "Ringing")


async def test_invite_from_another_gateway_is_declined_without_ring_event() -> None:
    account = SipAccount("1", "user@gateway.bs.iotleg.com", "secret", "oid")
    on_ring = AsyncMock()
    client = SipClient(account, "certificate", "key", "ca", on_ring)
    client._respond = AsyncMock()

    invalid = SipMessage(
        "INVITE sip:user SIP/2.0",
        {"from": "<sip:c100x@other.bs.iotleg.com>", "call-id": "invalid"},
    )
    await client._handle_request(invalid)

    on_ring.assert_not_awaited()
    client._respond.assert_awaited_once_with(invalid, 486, "Busy Here")


async def test_monitoring_dialog_sends_ack_and_bye_to_remote_contact() -> None:
    account = SipAccount("1", "user@gateway.bs.iotleg.com", "secret", "oid")
    client = SipClient(account, "certificate", "key", "ca", AsyncMock())
    writer = MagicMock()
    writer.drain = AsyncMock()
    client._writer = writer
    client._last_transaction = {"call_id": "call-1", "tag": "local", "sequence": 22}
    client._authenticated_request = AsyncMock(
        return_value=SipMessage(
            "SIP/2.0 200 OK",
            {
                "content-type": "application/sdp",
                "to": "<sip:c100x@gateway.bs.iotleg.com>;tag=remote",
                "contact": "<sip:media@198.51.100.20:5061;transport=tls>",
                "record-route": "<sip:first;lr>, <sip:second;lr>",
            },
            b"v=0\r\n",
        )
    )

    answer = await client.start_monitoring("v=0\r\n")

    assert answer == b"v=0\r\n"
    ack = writer.write.call_args.args[0].decode()
    assert ack.startswith("ACK sip:media@198.51.100.20:5061;transport=tls SIP/2.0")
    assert ack.index("Route: <sip:second;lr>") < ack.index("Route: <sip:first;lr>")

    client._dialog_request = AsyncMock(return_value=SipMessage("SIP/2.0 200 OK", {}))
    await client.end_monitoring()
    client._dialog_request.assert_awaited_once()
    assert client._dialog_request.await_args.args[1:] == ("BYE", 23)


async def test_authenticated_invite_acknowledges_proxy_challenge_before_retry() -> None:
    account = SipAccount("1", "user@gateway.bs.iotleg.com", "secret", "oid")
    client = SipClient(account, "certificate", "key", "ca", AsyncMock())
    writer = MagicMock()
    writer.drain = AsyncMock()
    client._writer = writer
    responses = iter(
        (
            SipMessage(
                "SIP/2.0 407 Proxy Authentication Required",
                {
                    "proxy-authenticate": (
                        'Digest realm="gateway.bs.iotleg.com", nonce="abc", qop="auth"'
                    ),
                    "to": "<sip:c100x@gateway.bs.iotleg.com>;tag=challenge",
                },
            ),
            SipMessage("SIP/2.0 200 OK", {}),
        )
    )

    async def request(*_args, **kwargs):
        transaction = kwargs["transaction"]
        transaction.setdefault("call_id", "call-1")
        transaction.setdefault("tag", "local")
        transaction.setdefault("sequence", 10)
        transaction["branch"] = "z9hG4bK.test"
        transaction["from"] = "<sip:user@gateway.bs.iotleg.com>;tag=local"
        if kwargs.get("authorization"):
            transaction["sequence"] += 1
        return next(responses)

    client._request = AsyncMock(side_effect=request)

    response = await client._authenticated_request(
        "INVITE",
        "sip:c100x@gateway.bs.iotleg.com",
        b"v=0\r\n",
        content_type="application/sdp",
    )

    assert response.status_code == 200
    written = b"".join(call.args[0] for call in writer.write.call_args_list).decode()
    assert "ACK sip:c100x@gateway.bs.iotleg.com SIP/2.0" in written
    assert "CSeq:" in written and " ACK\r\n" in written
