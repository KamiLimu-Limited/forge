"""Unit tests for JWT utilities."""

import uuid

import pytest

from forge.core.jwt import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expiration,
    get_token_jti,
    get_token_payload,
    get_token_subject,
)


class TestTokenCreation:
    """Tests for token creation functions."""

    def test_create_access_token(self):
        """Test access token creation."""
        user_id = uuid.uuid4()
        token, jti, exp = create_access_token(user_id)

        assert token is not None
        assert len(token) > 0
        assert jti is not None
        assert exp is not None

    def test_create_refresh_token(self):
        """Test refresh token creation."""
        user_id = uuid.uuid4()
        token, jti, exp = create_refresh_token(user_id)

        assert token is not None
        assert len(token) > 0
        assert jti is not None
        assert exp is not None

    def test_access_token_type(self):
        """Test that access token has correct type claim."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)
        payload = decode_token(token)

        assert payload["type"] == "access"

    def test_refresh_token_type(self):
        """Test that refresh token has correct type claim."""
        user_id = uuid.uuid4()
        token, _, _ = create_refresh_token(user_id)
        payload = decode_token(token)

        assert payload["type"] == "refresh"

    def test_token_subject(self):
        """Test that token contains correct subject."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)
        payload = decode_token(token)

        assert payload["sub"] == str(user_id)

    def test_token_has_jti(self):
        """Test that token contains JTI claim."""
        user_id = uuid.uuid4()
        token, jti, _ = create_access_token(user_id)
        payload = decode_token(token)

        assert payload["jti"] == jti

    def test_token_with_additional_claims(self):
        """Test token creation with additional claims."""
        user_id = uuid.uuid4()
        additional = {"custom": "claim", "roles": ["admin"]}
        token, _, _ = create_access_token(user_id, additional_claims=additional)
        payload = decode_token(token)

        assert payload["custom"] == "claim"
        assert payload["roles"] == ["admin"]


class TestTokenDecoding:
    """Tests for token decoding functions."""

    def test_decode_valid_token(self):
        """Test decoding a valid token."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)
        payload = decode_token(token)

        assert payload["sub"] == str(user_id)
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_invalid_token(self):
        """Test that decoding invalid token raises error."""
        with pytest.raises(TokenError):
            decode_token("invalid.token.here")

    def test_decode_tampered_token(self):
        """Test that tampered token fails validation."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)

        # Tamper with the token by modifying a character
        tampered = token[:-5] + "XXXXX"

        with pytest.raises(TokenError):
            decode_token(tampered)


class TestTokenPayload:
    """Tests for get_token_payload function."""

    def test_get_payload_correct_type(self):
        """Test getting payload for correct token type."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)
        payload = get_token_payload(token, TokenType.ACCESS)

        assert payload["sub"] == str(user_id)

    def test_get_payload_wrong_type(self):
        """Test that wrong token type raises error."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)

        with pytest.raises(TokenError) as exc_info:
            get_token_payload(token, TokenType.REFRESH)

        assert "Invalid token type" in str(exc_info.value)


class TestTokenSubject:
    """Tests for get_token_subject function."""

    def test_get_subject(self):
        """Test extracting subject from token."""
        user_id = uuid.uuid4()
        token, _, _ = create_access_token(user_id)
        subject = get_token_subject(token, TokenType.ACCESS)

        assert subject == str(user_id)


class TestTokenJti:
    """Tests for get_token_jti function."""

    def test_get_jti(self):
        """Test extracting JTI from token."""
        user_id = uuid.uuid4()
        token, expected_jti, _ = create_access_token(user_id)
        jti = get_token_jti(token)

        assert jti == expected_jti

    def test_jti_is_unique(self):
        """Test that each token has unique JTI."""
        user_id = uuid.uuid4()
        _, jti1, _ = create_access_token(user_id)
        _, jti2, _ = create_access_token(user_id)

        assert jti1 != jti2


class TestTokenExpiration:
    """Tests for get_token_expiration function."""

    def test_get_expiration(self):
        """Test extracting expiration from token."""
        user_id = uuid.uuid4()
        token, _, expected_exp = create_access_token(user_id)
        exp = get_token_expiration(token)

        # Allow 1 second tolerance
        assert abs((exp - expected_exp).total_seconds()) < 1
