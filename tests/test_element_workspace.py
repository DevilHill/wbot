"""共享工作副本与本地元素必须在同一事务中变更。"""
from pathlib import Path
import tempfile
import unittest

from app.assistant.element_workspace import ElementWorkspace
from wbot.elements import ElementLibrary


class ElementWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'elements.sqlite3'
        self.workspace = ElementWorkspace(self.path)

    def test_checkout_and_binding_are_atomic_and_reject_concurrent_edits(self):
        items, state = self.workspace.snapshot()
        ElementLibrary(self.path).upsert({'id': 'local', 'name': '本地', 'xpath': '//button'})
        with self.assertRaisesRegex(RuntimeError, '本地元素'):
            self.workspace.save(state, {'binding': {'head': 'c1'}}, expected_items=items,
                                replacement=[{'id': 'shared', 'name': '共享', 'xpath': '//input'}])
        self.assertIsNone(self.workspace.snapshot()[1]['binding'])
        self.assertEqual([item['id'] for item in self.workspace.list()], ['local'])

    def test_metadata_save_preserves_edits_made_during_remote_commit(self):
        _, state = self.workspace.snapshot()
        ElementLibrary(self.path).upsert({'id': 'local', 'name': '本地', 'xpath': '//button'})
        updated = dict(state, binding={'head': 'c1'})
        self.workspace.save(state, updated)
        self.assertEqual(self.workspace.snapshot()[1], updated)
        self.assertEqual(len(self.workspace.list()), 1)
        with self.assertRaisesRegex(RuntimeError, '工作副本'):
            self.workspace.save(state, dict(state, binding={'head': 'stale'}))

    def test_invalid_replacement_preserves_elements_and_state(self):
        before, state = self.workspace.snapshot()
        with self.assertRaises(ValueError):
            self.workspace.save(state, dict(state, binding={'head': 'bad'}), expected_items=before,
                                replacement=[{'id': 'bad', 'name': '非法', 'xpath': 'count(//div)'}])
        self.assertEqual(self.workspace.snapshot(), (before, state))


if __name__ == '__main__':
    unittest.main()
