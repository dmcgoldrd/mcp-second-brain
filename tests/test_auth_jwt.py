"""Tests for src.auth.jwt — JWT validation via JWKS."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID


class TestValidateToken:
    def test_returns_decoded_payload(self, mock_jwt_payload):
        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-rsa-key"

        mock_jwks = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("src.auth.jwt._get_jwks_client", return_value=mock_jwks),
            patch("src.auth.jwt.jwt.decode", return_value=mock_jwt_payload),
        ):
            from src.auth.jwt import validate_token

            result = validate_token("fake-token")
            assert result == mock_jwt_payload
            assert result["sub"] == TEST_USER_ID

    def test_calls_jwt_decode_with_correct_args(self, mock_jwt_payload):
        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-rsa-key"

        mock_jwks = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("src.auth.jwt._get_jwks_client", return_value=mock_jwks),
            patch("src.auth.jwt.jwt.decode", return_value=mock_jwt_payload) as mock_decode,
        ):
            from src.auth.jwt import validate_token

            validate_token("my-token")

            mock_decode.assert_called_once_with(
                "my-token",
                "fake-rsa-key",
                algorithms=["RS256"],
                audience="authenticated",
                issuer="https://test.supabase.co/auth/v1",
            )

    def test_raises_on_invalid_token(self):
        import jwt as pyjwt

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-rsa-key"

        mock_jwks = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("src.auth.jwt._get_jwks_client", return_value=mock_jwks),
            patch(
                "src.auth.jwt.jwt.decode",
                side_effect=pyjwt.exceptions.InvalidTokenError("bad token"),
            ),
        ):
            from src.auth.jwt import validate_token

            with pytest.raises(pyjwt.exceptions.InvalidTokenError):
                validate_token("bad-token")

    def test_raises_on_jwks_failure(self):
        mock_jwks = MagicMock()
        mock_jwks.get_signing_key_from_jwt.side_effect = Exception("JWKS unavailable")

        with patch("src.auth.jwt._get_jwks_client", return_value=mock_jwks):
            from src.auth.jwt import validate_token

            with pytest.raises(Exception, match="JWKS unavailable"):
                validate_token("some-token")


class TestExtractUserId:
    def test_returns_sub_claim(self, mock_jwt_payload):
        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-rsa-key"

        mock_jwks = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("src.auth.jwt._get_jwks_client", return_value=mock_jwks),
            patch("src.auth.jwt.jwt.decode", return_value=mock_jwt_payload),
        ):
            from src.auth.jwt import extract_user_id

            user_id = extract_user_id("fake-token")
            assert user_id == TEST_USER_ID

    def test_raises_on_missing_sub(self):
        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-rsa-key"

        mock_jwks = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        payload_no_sub = {"aud": "authenticated", "exp": 9999999999}

        with (
            patch("src.auth.jwt._get_jwks_client", return_value=mock_jwks),
            patch("src.auth.jwt.jwt.decode", return_value=payload_no_sub),
        ):
            from src.auth.jwt import extract_user_id

            with pytest.raises(KeyError):
                extract_user_id("token-no-sub")


class TestGetJwksClient:
    def test_singleton_pattern(self):
        import src.auth.jwt

        src.auth.jwt._jwks_client = None

        with patch("src.auth.jwt.PyJWKClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            c1 = src.auth.jwt._get_jwks_client()
            c2 = src.auth.jwt._get_jwks_client()

            assert c1 is c2
            mock_cls.assert_called_once()

        src.auth.jwt._jwks_client = None
