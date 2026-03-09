import ast
import os
import re


def _load_main_function(tree: ast.AST) -> ast.FunctionDef:
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("main() not found in praxans_game.py")


def test_main_has_no_bare_except_handlers() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    source_path = os.path.join(repo_root, "praxans_game.py")

    with open(source_path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    main_func = _load_main_function(tree)
    bare_handlers = [
        handler.lineno
        for handler in ast.walk(main_func)
        if isinstance(handler, ast.ExceptHandler) and handler.type is None
    ]

    assert not bare_handlers, f"Bare except handlers in main() at lines: {bare_handlers}"


def test_main_does_not_silence_display_error_banner_failure() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    source_path = os.path.join(repo_root, "praxans_game.py")

    with open(source_path, "r", encoding="utf-8") as fh:
        source = fh.read()

    # Regression guard: fallback banner render failures must not be silently swallowed.
    legacy_silent_fallback = re.search(
        r"except Exception:\\s*pass\\s*# Can't even show error, give up",
        source,
    )
    assert legacy_silent_fallback is None

def test_main_overlay_exceptions_are_not_silently_swallowed() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    source_path = os.path.join(repo_root, "praxans_game.py")

    with open(source_path, "r", encoding="utf-8") as fh:
        source = fh.read()

    debug_overlay_silent = re.search(
        r"if current_time - game_start_time < 3\.0:.*?except Exception:\\s*pass",
        source,
        re.DOTALL,
    )
    storyteller_overlay_silent = re.search(
        r"# Storyteller Debug Overlay.*?except Exception:\\s*pass",
        source,
        re.DOTALL,
    )

    assert debug_overlay_silent is None
    assert storyteller_overlay_silent is None
