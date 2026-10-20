"""Unit tests for security utilities."""

import bcrypt

from forge.core.security import (
    generate_secure_token,
    hash_password,
    validate_password,
    verify_password,
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_hash(self):
        """New hashes use Argon2id."""
        password = "TestPassword123"
        hashed = hash_password(password)

        assert hashed != password
        assert hashed.startswith("$argon2id$")

    def test_verify_legacy_bcrypt_hash(self):
        """Hashes created before the Argon2 switch still verify."""
        legacy = bcrypt.hashpw(b"TestPassword123", bcrypt.gensalt()).decode()

        assert verify_password("TestPassword123", legacy) is True
        assert verify_password("WrongPassword123", legacy) is False

    def test_hash_password_different_for_same_input(self):
        """Test that hashing the same password twice produces different hashes."""
        password = "TestPassword123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test that verify_password returns True for correct password."""
        password = "TestPassword123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that verify_password returns False for incorrect password."""
        password = "TestPassword123"
        hashed = hash_password(password)

        assert verify_password("WrongPassword", hashed) is False


class TestPasswordValidation:
    """Tests for password validation."""

    def test_valid_password(self):
        """Test that a valid password passes all checks."""
        result = validate_password("ValidPass123")

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_password_too_short(self):
        """Test that a short password fails validation."""
        result = validate_password("Short1")

        assert result.is_valid is False
        assert any("at least 8 characters" in e for e in result.errors)

    def test_password_missing_uppercase(self):
        """Test that a password without uppercase fails."""
        result = validate_password("lowercase123")

        assert result.is_valid is False
        assert any("uppercase" in e for e in result.errors)

    def test_password_missing_lowercase(self):
        """Test that a password without lowercase fails."""
        result = validate_password("UPPERCASE123")

        assert result.is_valid is False
        assert any("lowercase" in e for e in result.errors)

    def test_password_missing_digit(self):
        """Test that a password without digits fails."""
        result = validate_password("NoDigitsHere")

        assert result.is_valid is False
        assert any("digit" in e for e in result.errors)

    def test_password_multiple_failures(self):
        """Test that multiple failures are reported."""
        result = validate_password("abc")

        assert result.is_valid is False
        assert len(result.errors) >= 2


class TestSecureToken:
    """Tests for secure token generation."""

    def test_generate_token_default_length(self):
        """Test that default token has expected length."""
        token = generate_secure_token()

        # URL-safe base64 encoding of 32 bytes produces ~43 characters
        assert len(token) >= 40

    def test_generate_token_unique(self):
        """Test that generated tokens are unique."""
        tokens = {generate_secure_token() for _ in range(100)}

        assert len(tokens) == 100

    def test_generate_token_custom_length(self):
        """Test token generation with custom byte length."""
        short_token = generate_secure_token(nbytes=16)
        long_token = generate_secure_token(nbytes=64)

        assert len(short_token) < len(long_token)
