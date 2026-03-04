"""Tests for src.main — entry point."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch


class TestMain:
    def test_calls_mcp_run(self):
        with patch("src.main.mcp") as mock_mcp:
            from src.main import main

            main()

            mock_mcp.run.assert_called_once_with(
                transport="streamable-http",
                host="0.0.0.0",
                port=8080,
            )

    def test_uses_config_host_and_port(self):
        with (
            patch("src.main.HOST", "127.0.0.1"),
            patch("src.main.PORT", 9090),
            patch("src.main.mcp") as mock_mcp,
        ):
            from src.main import main

            main()

            mock_mcp.run.assert_called_once_with(
                transport="streamable-http",
                host="127.0.0.1",
                port=9090,
            )

    def test_name_main_guard_executes(self):
        """Verify the __name__ == '__main__' guard calls main() when run as script.

        Uses subprocess to actually run the module, but patches mcp.run to exit
        immediately so we don't start a real server.
        """
        code = (
            "import sys; "
            "from unittest.mock import MagicMock; "
            "import src.server; "
            "src.server.mcp = MagicMock(); "
            "import runpy; "
            "runpy.run_module('src.main', run_name='__main__'); "
            "assert src.server.mcp.run.called, 'mcp.run was not called'; "
            "print('GUARD_OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert (
            "GUARD_OK" in result.stdout
        ), f"Guard test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
