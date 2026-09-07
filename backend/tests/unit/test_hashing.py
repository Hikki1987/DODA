from doda.application.hashing import hash_payload


def test_hash_is_stable_regardless_of_key_order() -> None:
    a = {"to": "boss@example.com", "subject": "Hi", "body": "..."}
    b = {"subject": "Hi", "body": "...", "to": "boss@example.com"}

    assert hash_payload(a) == hash_payload(b)


def test_hash_changes_when_a_value_changes() -> None:
    original = {"to": "boss@example.com", "amount": 100}
    tampered = {"to": "boss@example.com", "amount": 100_000}

    assert hash_payload(original) != hash_payload(tampered)
