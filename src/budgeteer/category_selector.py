from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style


def select_category_chain_legacy(
    categories: dict[str, Any],
    select_prompt: Callable[..., Any],
) -> list[str]:
    """Select category path via sequential select prompts."""
    chain: list[str] = []
    cursor: Any = categories

    while isinstance(cursor, dict):
        options = sorted(cursor.keys())
        choice = select_prompt("Select category", choices=options).ask()
        if choice is None:
            raise KeyboardInterrupt
        chain.append(choice)
        cursor = cursor[choice]

    if isinstance(cursor, list) and cursor:
        choice = select_prompt("Select subcategory", choices=cursor).ask()
        if choice is None:
            raise KeyboardInterrupt
        chain.append(choice)

    return chain


def select_category_chain(
    categories: dict[str, Any],
    select_prompt: Callable[..., Any],
) -> list[str]:
    """Select category path with a richer TTY navigator and legacy fallback."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return select_category_chain_legacy(categories, select_prompt)

    locked_chain: list[str] = []
    indices: list[int] = [0]

    def current_node() -> Any:
        """Return the node referenced by the currently locked category segments."""
        cursor: Any = categories
        for segment in locked_chain:
            if not isinstance(cursor, dict) or segment not in cursor:
                return None
            cursor = cursor[segment]
        return cursor

    def options_for_node(node: Any) -> list[str]:
        """Return selectable option labels for a node."""
        if isinstance(node, dict):
            return sorted(node.keys())
        if isinstance(node, list):
            return [str(item) for item in node]
        return []

    def current_options() -> list[str]:
        """Return options for the current cursor position."""
        return options_for_node(current_node())

    def normalize_index() -> None:
        """Ensure the active index exists and stays within current option bounds."""
        depth = len(locked_chain)
        while len(indices) <= depth:
            indices.append(0)
        options = current_options()
        if not options:
            indices[depth] = 0
            return
        indices[depth] = min(max(indices[depth], 0), len(options) - 1)

    def selected_option() -> str | None:
        """Return the currently highlighted option at the active depth."""
        normalize_index()
        options = current_options()
        if not options:
            return None
        return options[indices[len(locked_chain)]]

    def preview_items() -> list[tuple[str, bool]]:
        """Return preview rows as (label, has_children) tuples."""
        node = current_node()
        choice = selected_option()
        if choice is None or not isinstance(node, dict):
            return []

        child = node.get(choice)
        if isinstance(child, dict):
            return [
                (name, len(options_for_node(child.get(name))) > 0)
                for name in sorted(child.keys())
            ]
        if isinstance(child, list):
            return [(str(item), False) for item in child]
        return []

    def is_leaf_choice(choice: str) -> bool:
        """Check whether a highlighted option resolves to a terminal selection."""
        node = current_node()
        if isinstance(node, dict):
            child = node.get(choice)
            return len(options_for_node(child)) == 0
        return True

    def at_end_of_path() -> bool:
        """Return True when locked segments point to the final list level."""
        return isinstance(current_node(), list)

    def move(delta: int) -> None:
        """Move active selection up/down with wraparound."""
        normalize_index()
        options = current_options()
        if not options:
            return
        depth = len(locked_chain)
        indices[depth] = (indices[depth] + delta) % len(options)

    def drill() -> None:
        """Move one level deeper into highlighted option if child options exist."""
        choice = selected_option()
        if choice is None:
            return

        node = current_node()
        if isinstance(node, dict):
            child = node.get(choice)
            child_options = options_for_node(child)
            if child_options:
                locked_chain.append(choice)
                normalize_index()

    def confirm_if_leaf() -> list[str] | None:
        """Return a complete category chain if current state is saveable."""
        choice = selected_option()
        if choice is None:
            return None
        # Only selections from the terminal level (right-most path position) can be saved.
        if at_end_of_path() and is_leaf_choice(choice):
            return [*locked_chain, choice]

        return None

    def go_back() -> None:
        """Move one level up and normalize selection indexes."""
        if not locked_chain:
            return
        locked_chain.pop()
        del indices[len(locked_chain) + 1 :]
        normalize_index()

    def breadcrumb_text() -> list[tuple[str, str]]:
        """Render breadcrumb text for current path and highlighted option."""
        selected = selected_option()
        parts = [*locked_chain]
        if selected is not None:
            parts.append(selected)
        if not parts:
            suffix = "  [END]" if at_end_of_path() else ""
            return [("class:muted", f"Path: (root){suffix}")]

        chain = " > ".join(parts)
        if at_end_of_path():
            return [("class:muted", "Path: "), ("", chain), ("class:end", "  [END]")]
        return [("class:muted", "Path: "), ("", chain)]

    def current_text() -> list[tuple[str, str]]:
        """Render the current column with active item highlighting."""
        normalize_index()
        options = current_options()
        if not options:
            return [("class:muted", "(no options)\n")]

        depth = len(locked_chain)
        active = indices[depth]
        lines: list[tuple[str, str]] = []
        for idx, option in enumerate(options):
            prefix = "> " if idx == active else "  "
            style = "class:active" if idx == active else ""
            lines.append((style, f"{prefix}{option}\n"))
        return lines

    def preview_text() -> list[tuple[str, str]]:
        """Render the right-side preview aligned with the active row."""
        depth = len(locked_chain)
        active = indices[depth]
        padding: list[tuple[str, str]] = [("", "\n")] * active

        if at_end_of_path():
            return [
                *padding,
                ("class:end", "End of path reached. Press Enter to save.\n"),
            ]

        items = preview_items()
        if not items:
            return [*padding, ("class:muted", "(no subcategories)\n")]
        return padding + [
            ("class:preview", f"{name}{'...' if has_children else ''}\n")
            for name, has_children in items
        ]

    help_text = "Arrows navigate | Right moves deeper | Enter saves only at [END]"

    center = Window(
        FormattedTextControl(current_text),
        always_hide_cursor=True,
        dont_extend_width=True,
    )
    right = Window(FormattedTextControl(preview_text), always_hide_cursor=True)

    root = HSplit(
        [
            Window(height=1, content=FormattedTextControl(lambda: [("class:muted", help_text)])),
            Window(height=1, content=FormattedTextControl(breadcrumb_text)),
            VSplit(
                [
                    center,
                    Window(width=1, char=" "),
                    right,
                ]
            ),
        ]
    )

    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        """Move selection up one row."""
        move(-1)
        event.app.invalidate()

    @kb.add("down")
    def _down(event: Any) -> None:
        """Move selection down one row."""
        move(1)
        event.app.invalidate()

    @kb.add("left")
    def _left(event: Any) -> None:
        """Go back one level in the category hierarchy."""
        go_back()
        event.app.invalidate()

    @kb.add("right")
    def _right(event: Any) -> None:
        """Drill into the currently highlighted category branch."""
        drill()
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event: Any) -> None:
        """Save selection when positioned at a terminal category path."""
        result = confirm_if_leaf()
        if result is None:
            event.app.invalidate()
            return
        event.app.exit(result=result)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event: Any) -> None:
        """Cancel category selection and return control to caller."""
        event.app.exit(result=None)

    style = Style.from_dict(
        {
            "active": "bold fg:#00afff",
            "muted": "fg:#888888",
            "preview": "fg:#666666",
            "end": "bold fg:#00af5f",
        }
    )

    normalize_index()
    app = Application(
        layout=Layout(root, focused_element=center),
        key_bindings=kb,
        full_screen=False,
        style=style,
    )
    result = app.run()
    if result is None:
        raise KeyboardInterrupt
    return result
