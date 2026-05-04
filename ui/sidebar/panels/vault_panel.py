"""Vault panel — password manager sidebar tab.

Shows credentials and secure notes from the global (master) vault and an
optional per-project local vault.  Each entry row has action buttons for
copy / edit / delete.  Section-level buttons add new entries.

Event handlers (registered at import time):
* ``vault.needs_unlock`` — prompts for master password
* ``vault.needs_init`` — prompts to create a master password
"""

from __future__ import annotations

import os

import pyperclip
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from context import AppContext
from core.events import CodyEvent, register_handler
from core.vault import VaultManager
from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree import NodeSelected, NodeToggled, Tree
from ui.tree.tree_row import ActionRow, RowButton, TreeNode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EDIT = "edit"
_COPY = "copy"
_DEL = "del"


def _action_buttons() -> list[RowButton]:
    return [
        RowButton(_COPY, "Copy", "vault-copy"),
        RowButton(_EDIT, "Edit", "vault-edit"),
        RowButton(_DEL, "Del", "vault-del"),
    ]


def _build_entry_node(
    prefix: str, name: str, label: str, entry_type: str
) -> TreeNode:
    return TreeNode(
        f"{prefix}-{name}",
        label,
        data={"type": entry_type, "name": name},
        buttons=_action_buttons(),
    )


@register_sidebar_tab(name="vault", icon="󰦝", side="right", tooltip="Vault")
class VaultPanel(Container):
    """Sidebar panel showing vault credentials and secure notes in two trees
    (global + local) with inline action buttons.
    """

    def __init__(self):
        super().__init__()
        self._vault: VaultManager | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_vault(self, vault: VaultManager | None) -> None:
        """Bind a :class:`VaultManager` and rebuild all trees."""
        self._vault = vault
        if self.is_mounted:
            self._rebuild()

    # ------------------------------------------------------------------
    # Mount — self-wire from app context
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        if self._vault is None:
            app = self.app
            if hasattr(app, 'context') and app.context is not None:
                self._vault = app.context.vault
        self._rebuild()

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # -- Global vault --
        yield Static("󰋘  Global Vault", classes="vault-section-header")
        self._global_tree = Tree(TreeNode("global-root", "Global Vault"))
        self._global_tree.id = "global-tree"
        yield self._global_tree

        with Horizontal(classes="vault-actions", id="global-actions"):
            yield Button("+ Credential", id="add-global-cred")
            yield Button("+ Note", id="add-global-note")

        # -- Local vault (hidden unless a local vault exists) --
        yield Static("󰋘  Local Vault", id="local-vault-header",
                     classes="vault-section-header")
        self._local_tree = Tree(TreeNode("local-root", "Local Vault"))
        self._local_tree.id = "local-tree"
        yield self._local_tree

        with Horizontal(classes="vault-actions", id="local-actions"):
            yield Button("+ Credential", id="add-local-cred")
            yield Button("+ Note", id="add-local-note")

        yield Button("− Remove Local Vault", id="remove-local-vault")

        # Shown when no local vault exists yet
        yield Button("+ Add Local Vault", id="create-local-vault",
                     classes="vault-add-local")

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Read vault data and repopulate both trees.

        Posts ``vault.needs_unlock`` or ``vault.needs_init`` when needed.
        """
        if self._vault is None:
            return

        # Locked?
        if self._vault.is_locked():
            self.post_message(CodyEvent("vault.needs_unlock", {}))
            return

        # Needs init?
        if not os.path.exists(self._vault.master._filepath):
            self.post_message(CodyEvent("vault.needs_init", {}))
            return

        # Local vault visibility
        has_local = self._vault.has_local_vault()
        self.set_class(has_local, "has-local")
        self.set_class(not has_local, "no-local")

        # Build global tree
        self._build_tree(
            self._global_tree,
            "global",
            self._vault.master,
            show_empty=True,
        )

        # Build local tree
        if has_local and self._vault._local is not None:
            self._build_tree(
                self._local_tree,
                "local",
                self._vault._local,
                show_empty=True,
            )
        else:
            # Empty placeholder
            self._local_tree.set_root(
                TreeNode("local-root", "Local Vault",
                         children=[
                             TreeNode("local-creds", "󰢥  Credentials"),
                             TreeNode("local-notes", "󰢥  Notes"),
                         ])
            )
            self._local_tree.expand_all()

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _build_tree(self, tree: Tree, prefix: str, vault, *,
                    show_empty: bool = False) -> None:
        """Populate *tree* with credential and note nodes from *vault*."""
        # Credentials (exclude internal vault:* passkey entries)
        cred_nodes: list[TreeNode] = []
        try:
            creds = [
                n for n in vault.list_credentials()
                if not n.startswith("vault:")
            ]
            for name in creds:
                entry = vault.get_credential(name)
                if entry is None:
                    continue
                username, _ = entry
                label = f"  {name}  ({username})"
                cred_nodes.append(
                    _build_entry_node(f"{prefix}-cred", name, label, "credential")
                )
        except Exception:
            pass

        # Notes
        note_nodes: list[TreeNode] = []
        try:
            notes = vault.list_secure_notes()
            for name in notes:
                note_nodes.append(
                    _build_entry_node(f"{prefix}-note", name,
                                      f"  {name}", "note")
                )
        except Exception:
            pass

        root_children: list[TreeNode] = [
            TreeNode(f"{prefix}-creds", "󰢥  Credentials", children=cred_nodes),
            TreeNode(f"{prefix}-notes", "󰢥  Notes", children=note_nodes),
        ]

        root = TreeNode(f"{prefix}-root",
                        "Local Vault" if prefix == "local" else "Global Vault",
                        children=root_children)
        tree.set_root(root)
        tree.expand_all()

    # ------------------------------------------------------------------
    # Button handlers — section-level Add buttons
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route section-level buttons to the appropriate handler."""
        event.stop()
        btn_id = event.button.id

        if btn_id == "add-global-cred":
            self._prompt_add("global", "credential")
        elif btn_id == "add-global-note":
            self._prompt_add("global", "note")
        elif btn_id == "add-local-cred":
            self._prompt_add("local", "credential")
        elif btn_id == "add-local-note":
            self._prompt_add("local", "note")
        elif btn_id == "create-local-vault":
            self._create_local_vault()
        elif btn_id == "remove-local-vault":
            self._remove_local_vault()

    # ------------------------------------------------------------------
    # ActionRow button handlers — Copy / Edit / Delete
    # ------------------------------------------------------------------

    def on_action_row_button_pressed(self, event: ActionRow.ButtonPressed) -> None:
        """Handle copy / edit / delete from an entry row."""
        event.stop()
        node = event.node
        entry_type: str = node.data.get("type", "")
        entry_name: str = node.data.get("name", "")

        if event.action_id == _COPY:
            self._copy_entry(entry_type, entry_name)
        elif event.action_id == _EDIT:
            self._prompt_edit(entry_type, entry_name)
        elif event.action_id == _DEL:
            self._delete_entry(entry_type, entry_name)

    # ------------------------------------------------------------------
    # Actions — Copy
    # ------------------------------------------------------------------

    def _copy_entry(self, entry_type: str, name: str) -> None:
        """Copy a credential password or note text to the system clipboard."""
        if self._vault is None:
            return
        try:
            if entry_type == "credential":
                cred = self._vault.get_credential(name)
                if cred:
                    _, password = cred
                    pyperclip.copy(password)
            else:
                text = self._vault.get_secure_note(name)
                if text is not None:
                    pyperclip.copy(text)
            self.app.notify("Copied to clipboard.")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Actions — Add
    # ------------------------------------------------------------------

    def _prompt_add(self, scope: str, entry_type: str) -> None:
        """Push a modal to create a new credential or note."""
        from ui.widgets.input_modal import InputModal

        async def do_add() -> None:
            if entry_type == "credential":
                name_modal = InputModal("Credential name:", "Name")
                name = await self.app.push_screen_wait(name_modal)
                if not name:
                    return

                user_modal = InputModal("Username:", "Username")
                username = await self.app.push_screen_wait(user_modal)
                if username is None:
                    return

                pw_modal = InputModal("Password:", "Password", password=True)
                password = await self.app.push_screen_wait(pw_modal)
                if password is None:
                    return

                if scope == "local" and self._vault is not None:
                    self._vault._local.register_credential(name, username, password)
                elif self._vault is not None:
                    self._vault.register_credential(name, username, password)
            else:
                name_modal = InputModal("Note name:", "Name")
                name = await self.app.push_screen_wait(name_modal)
                if not name:
                    return

                text_modal = InputModal("Note text:", "Text")
                text = await self.app.push_screen_wait(text_modal)
                if text is None:
                    return

                if scope == "local" and self._vault is not None:
                    self._vault._local.register_secure_note(name, text)
                elif self._vault is not None:
                    self._vault.register_secure_note(name, text)

            self._rebuild()

        self.app.run_worker(do_add())

    # ------------------------------------------------------------------
    # Actions — Edit
    # ------------------------------------------------------------------

    def _prompt_edit(self, entry_type: str, name: str) -> None:
        """Push modals to edit an existing credential or note."""
        from ui.widgets.input_modal import InputModal

        async def do_edit() -> None:
            if self._vault is None:
                return

            if entry_type == "credential":
                cred = self._vault.get_credential(name)
                if cred is None:
                    return
                old_user, old_pass = cred

                user_modal = InputModal("Username:", "Username", default=old_user)
                username = await self.app.push_screen_wait(user_modal)
                if username is None:
                    return

                pw_modal = InputModal("Password:", "Password",
                                      password=True, default=old_pass)
                password = await self.app.push_screen_wait(pw_modal)
                if password is None:
                    return

                self._vault.register_credential(name, username, password)
            else:
                old_text = self._vault.get_secure_note(name)
                if old_text is None:
                    return

                text_modal = InputModal("Note text:", "Text", default=old_text)
                text = await self.app.push_screen_wait(text_modal)
                if text is None:
                    return

                self._vault.register_secure_note(name, text)

            self._rebuild()

        self.app.run_worker(do_edit())

    # ------------------------------------------------------------------
    # Actions — Delete
    # ------------------------------------------------------------------

    def _delete_entry(self, entry_type: str, name: str) -> None:
        """Delete a credential or note after confirmation."""
        from ui.widgets.input_modal import InputModal

        async def do_delete() -> None:
            modal = InputModal(
                f"Delete '{name}'? Type 'yes' to confirm:", "Confirm"
            )
            result = await self.app.push_screen_wait(modal)
            if result != "yes":
                return

            if self._vault is None:
                return
            try:
                if entry_type == "credential":
                    self._vault.delete_credential(name)
                else:
                    self._vault.delete_secure_note(name)
                self._rebuild()
            except Exception:
                pass

        self.app.run_worker(do_delete())

    # ------------------------------------------------------------------
    # Actions — Local vault
    # ------------------------------------------------------------------

    def _create_local_vault(self) -> None:
        """Create a local (project) vault."""
        if self._vault is None or self._vault.is_locked():
            return
        try:
            self._vault.create_local_vault()
            self._rebuild()
        except Exception:
            pass

    def _remove_local_vault(self) -> None:
        """Remove the local vault after confirmation."""
        from ui.widgets.input_modal import InputModal

        async def do_remove() -> None:
            modal = InputModal(
                "Delete local vault? Type 'yes' to confirm:", "Confirm"
            )
            result = await self.app.push_screen_wait(modal)
            if result != "yes":
                return
            try:
                if self._vault is not None:
                    self._vault.remove_local_vault()
                self._rebuild()
            except Exception:
                pass

        self.app.run_worker(do_remove())


# ---------------------------------------------------------------------------
# Event handlers — registered at import time via decorator
# ---------------------------------------------------------------------------


@register_handler("vault.needs_unlock")
def _on_vault_needs_unlock(data: dict, ctx: AppContext) -> None:
    """Prompt for master password and unlock the vault."""
    _prompt_vault_password(
        ctx, "Enter master password:",
        lambda v, pw: v.unlock(pw),
    )


@register_handler("vault.needs_init")
def _on_vault_needs_init(data: dict, ctx: AppContext) -> None:
    """Prompt to create a master password."""
    _prompt_vault_password(
        ctx, "Create master password:",
        lambda v, pw: v.initialize_master(pw),
    )


def _prompt_vault_password(ctx: AppContext, prompt: str, action) -> None:
    """Push an :class:`InputModal` and call *action(vault, result)* on submit.

    After the action completes, rebuilds the VaultPanel so its contents
    are visible.
    """
    from ui.widgets.input_modal import InputModal

    app = ctx.app
    if app is None or ctx.vault is None:
        return

    async def do_prompt() -> None:
        modal = InputModal(prompt, "Password", password=True)
        result = await app.push_screen_wait(modal)
        if result is None:
            return
        try:
            action(ctx.vault, result)
            panel = app.query_one("VaultPanel")
            panel._rebuild()
        except Exception:
            pass

    app.run_worker(do_prompt())
