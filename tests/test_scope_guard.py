"""Unit tests for scripts.autobuild.scope_guard.

These tests exercise the helper logic in isolation so the guard module can be
validated without a real git repo context.
"""

from scripts.autobuild.scope_guard import _function_defs, _parse_shortstat


class TestParseShortstat:
    def test_full_stat(self):
        stat = _parse_shortstat(" 3 files changed, 10 insertions(+), 4 deletions(-)")
        assert stat.files_changed == 3
        assert stat.insertions == 10
        assert stat.deletions == 4

    def test_single_file_no_deletions(self):
        stat = _parse_shortstat(" 1 file changed, 2 insertions(+)")
        assert stat.files_changed == 1
        assert stat.insertions == 2
        assert stat.deletions == 0

    def test_only_deletions(self):
        stat = _parse_shortstat(" 5 files changed, 12 deletions(-)")
        assert stat.files_changed == 5
        assert stat.insertions == 0
        assert stat.deletions == 12

    def test_empty_stat(self):
        stat = _parse_shortstat("")
        assert stat.files_changed == 0
        assert stat.insertions == 0
        assert stat.deletions == 0

    def test_large_insertions(self):
        stat = _parse_shortstat(" 81 files changed, 12345 insertions(+), 89 deletions(-)")
        assert stat.files_changed == 81
        assert stat.insertions == 12345
        assert stat.deletions == 89


class TestFunctionDefs:
    def test_finds_top_level_functions(self):
        source = (
            "def alpha():\n"
            "    pass\n"
            "\n"
            "def beta(x, y):\n"
            "    return x + y\n"
        )
        assert _function_defs(source) == {"alpha", "beta"}

    def test_ignores_nested_functions(self):
        source = (
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    return inner\n"
        )
        assert _function_defs(source) == {"outer"}

    def test_ignores_class_methods(self):
        source = (
            "class Foo:\n"
            "    def method(self):\n"
            "        pass\n"
            "\n"
            "def standalone():\n"
            "    pass\n"
        )
        assert _function_defs(source) == {"standalone"}

    def test_no_functions(self):
        assert _function_defs("x = 1\n") == set()
