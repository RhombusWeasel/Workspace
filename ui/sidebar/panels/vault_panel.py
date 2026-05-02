"""Vault panel — sidebar tab showing credentials and secure notes."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Label, Static

from ui.sidebar.registry import register_sidebar_tab
from ui.tree.tree_row import TreeNode
from ui.tree.tree import Tree, NodeSelected, NodeToggled


@register_sidebar_tab(name="vault", icon="󰦝", side="right", tooltip="Vault")
class VaultPanel(Container):
    """Sidebar panel showing vault credentials and secure notes in a tree.

    Requires ``set_vault(vault)`` to be called before data is shown.
    """

    DEFAULT_CSS = """
    VaultPanel {
        height: 1fr;
        padding: 1;
    }

    VaultPanel Tree {
        height: 1fr;
    }
    """

    def __init__(self):
        super().__init__()
        self._vault = None

    def set_vault(self, vault) -> None:
        """Bind a :class:`Vault` instance and rebuild the tree."""
        self._vault = vault
        if self.is_mounted:
            self._rebuild()

    def compose(self) -> ComposeResult:
        root = TreeNode("vault-root", "Vault")
        self._tree = Tree(root)
        yield self._tree

    def on_mount(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        """Read vault data and repopulate the tree."""
        if self._vault is None:
            return

        # Build credential nodes
        cred_nodes: list[TreeNode] = []
        try:
            creds = self._vault.list_credentials()
            for cred_name in creds:
                cred = self._vault.get_credential(cred_name)
                if cred:
                    username, _password = cred
                    label = f"\uf007  {cred_name}  ({username})"
                    cred_nodes.append(TreeNode(
                        f"cred-{cred_name}", label,
                        data={"type": "credential", "name": cred_name}
                    ))
        except Exception:
            pass

        # Build note nodes
        note_nodes: list[TreeNode] = []
        try:
            notes = self._vault.list_secure_notes()
            for note_name in notes:
                note = self._vault.get_secure_note(note_name)
                if note:
                    label = f"\uf278  {note_name}"
                    note_nodes.append(TreeNode(
                        f"note-{note_name}", label,
                        data={"type": "note", "name": note_name}
                    ))
        except Exception:
            pass

        # Rebuild root
        root = TreeNode("vault-root", "Vault", children=[
            TreeNode("creds", f"\uf023  Credentials", children=cred_nodes),
            TreeNode("notes", f"\uf278  Notes", children=note_nodes),
        ])
        self._tree.set_root(root)
        self._tree.expand_all()
