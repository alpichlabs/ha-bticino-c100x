"""SIP protocol unit tests."""

from custom_components.bticino_c100x.models import SipAccount
from custom_components.bticino_c100x.sip import SipFramer, digest_authorization, parse_digest_challenge


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
