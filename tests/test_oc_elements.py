"""共享元素版本、分支隔离与三方合并的持久化行为。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from uuid import uuid4

from app.oc.element_service import ElementRepositoryService
from wbot.element_versions import canonical_items, diff_items, merge_items


def element(identifier='login', **changes):
    return dict(id=identifier, name=identifier, group='登录页', xpath='//button',
                url='', frame=None, description='', **changes)


class ElementVersionsTests(unittest.TestCase):
    def test_versions_ignore_local_timestamps_and_do_not_mutate_inputs(self):
        original = element()
        original.update(created_at='2020-01-01T00:00:00Z', updated_at='2021-01-01T00:00:00Z')
        copied = deepcopy(original)
        normalized = canonical_items([original])
        self.assertEqual(normalized, [element()])
        self.assertEqual(original, copied)
        self.assertEqual(diff_items([original], [element()]), [])

    def test_invalid_xpath_duplicate_identity_and_name_are_rejected(self):
        for items in ([dict(element(), xpath='count(//button)')], [element(), element()],
                      [element(), dict(element('another'), name='login')]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                canonical_items(items)

    def test_snapshot_size_and_missing_identity_are_rejected(self):
        with self.assertRaises(ValueError):
            canonical_items([{'name': '无身份', 'xpath': '//button'}])
        large = [dict(element(str(index)), description='文' * 9000) for index in range(60)]
        with self.assertRaisesRegex(ValueError, '1.5 MiB'):
            canonical_items(large)

    def test_independent_fields_and_elements_merge_without_conflict(self):
        base = [element()]
        main = [dict(element(), description='主分支说明'), element('other')]
        source = [dict(element(), xpath='//button[@id="login"]')]
        result = merge_items(base, main, source)
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['items'], [dict(source[0], description='主分支说明'), element('other')])

    def test_same_field_changes_and_delete_modify_conflicts_are_explicit(self):
        base = [element()]
        main = [dict(element(), xpath='//button[@id="main"]')]
        source = [dict(element(), xpath='//button[@id="source"]')]
        conflict = merge_items(base, main, source)['conflicts'][0]
        self.assertEqual(conflict, {'id': 'login', 'field': 'xpath', 'base': '//button',
            'main': main[0]['xpath'], 'source': source[0]['xpath']})
        deletion = merge_items(base, main, [])['conflicts'][0]
        self.assertEqual(deletion['field'], '__record__')
        self.assertIsNone(deletion['source'])

    def test_same_change_is_not_a_conflict_and_addition_conflicts_keep_identity(self):
        main = [dict(element(), xpath='//input')]
        self.assertEqual(merge_items([element()], main, main)['conflicts'], [])
        addition = merge_items([], main, [element()])['conflicts'][0]
        self.assertEqual(addition['field'], '__record__')
        self.assertIsNone(addition['base'])


class ElementRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'elements.sqlite3'
        self.service = ElementRepositoryService(self.path)
        self.alice = {'id': 'device-a', 'name': '开发电脑 A'}
        self.bob = {'id': 'device-b', 'name': '开发电脑 B'}
        self.repo = self.service.create_repository(self.body(name='共享登录页', description='测试', items=[element()]))

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def body(**fields):
        return dict(fields, request_id=uuid4().hex)

    def branch(self, name='fix-login', device=None):
        return self.service.create_branch(self.repo['id'], device or self.alice,
            self.body(name=name, base_commit=self.repo['head']))

    def commit(self, branch, items, device=None):
        return self.service.commit_branch(self.repo['id'], branch['id'], device or self.alice,
            self.body(expected_head=branch['head'], message='修正元素', items=items))

    def request(self, branch, device=None):
        return self.service.open_request(self.repo['id'], branch['id'], device or self.alice,
            self.body(expected_head=branch['head'], title='合并 XPath 修正', description=''))

    def merge(self, request, **changes):
        review = self.service.review_request(self.repo['id'], request['id'])
        return self.service.merge_request(self.repo['id'], request['id'],
            self.body(expected_main=review['main_head'], expected_source=review['source_head'],
                      resolutions=changes.get('resolutions', [])))

    def test_repository_initial_commit_and_history_survive_restart(self):
        restored = ElementRepositoryService(self.path)
        detail = restored.get_repository(self.repo['id'])
        self.assertEqual(detail['head']['items'], [element()])
        self.assertEqual(detail['head']['author']['kind'], 'admin')
        self.assertNotIn('items', detail['commits'][0])
        self.assertEqual(restored.list_repositories(), [self.repo])
        with self.assertRaises(ValueError):
            restored.create_repository(self.body(name=self.repo['name'], description=''))

    def test_devices_can_only_commit_their_own_branch_and_main_is_protected(self):
        branch = self.branch()
        with self.assertRaises(PermissionError):
            self.commit(branch, [], self.bob)
        with self.assertRaises(ValueError):
            self.branch('main')
        with self.assertRaises(KeyError):
            self.service.commit_branch(self.repo['id'], 'main', self.alice,
                self.body(expected_head=self.repo['head'], message='非法覆盖', items=[]))
        self.assertEqual(self.service.get_repository(self.repo['id'])['head']['items'], [element()])

    def test_cross_repository_commits_and_malformed_references_are_rejected(self):
        other = self.service.create_repository(self.body(name='另一个仓库'))
        with self.assertRaises(KeyError):
            self.service.get_commit(other['id'], self.repo['head'])
        with self.assertRaises(KeyError):
            self.service.create_branch(other['id'], self.alice, self.body(name='cross', base_commit=self.repo['head']))
        with self.assertRaises(ValueError):
            self.service.create_branch(self.repo['id'], self.alice, self.body(name='bad', base_commit=[]))
        with self.assertRaises(ValueError):
            self.service.restore(self.repo['id'], self.body(expected_head=self.repo['head'], commit_id=[], message='bad'))

    def test_commit_updates_request_but_reviewed_old_head_cannot_merge(self):
        first = self.commit(self.branch(), [dict(element(), xpath='//input')])
        request = self.request(first['branch'])
        review = self.service.review_request(self.repo['id'], request['id'])
        latest = self.commit(first['branch'], [dict(element(), xpath='//a')])
        with self.assertRaises(RuntimeError):
            self.service.merge_request(self.repo['id'], request['id'], self.body(
                expected_main=review['main_head'], expected_source=review['source_head'], resolutions=[]))
        current = self.service.review_request(self.repo['id'], request['id'])
        self.assertEqual(current['source_head'], latest['commit']['id'])
        self.assertEqual(current['request']['source_head'], latest['commit']['id'])

    def test_disjoint_changes_merge_after_main_advances_and_branch_closes(self):
        a = self.commit(self.branch(), [dict(element(), description='补充说明')])
        b = self.commit(self.branch('fix-xpath', self.bob), [dict(element(), xpath='//input')], self.bob)
        ar, br = self.request(a['branch']), self.request(b['branch'], self.bob)
        self.merge(ar)
        result = self.merge(br)
        self.assertEqual(result['commit']['items'], [dict(element(), description='补充说明', xpath='//input')])
        self.assertEqual(len(result['commit']['parents']), 2)
        self.assertEqual(result['request']['state'], 'merged')
        with self.assertRaises(RuntimeError):
            self.commit(b['branch'], [], self.bob)

    def test_conflicts_require_exact_resolutions_and_invalid_xpath_rolls_back(self):
        a = self.commit(self.branch(), [dict(element(), xpath='//input')])
        b = self.commit(self.branch('second', self.bob), [dict(element(), xpath='//a')], self.bob)
        self.merge(self.request(a['branch']))
        request = self.request(b['branch'], self.bob)
        with self.assertRaises(RuntimeError):
            self.merge(request)
        with self.assertRaises(ValueError):
            self.merge(request, resolutions=[{'id': 'login', 'field': 'xpath', 'value': 'count(//a)'}])
        self.assertEqual(self.service.review_request(self.repo['id'], request['id'])['request']['state'], 'open')
        result = self.merge(request, resolutions=[{'id': 'login', 'field': 'xpath', 'value': '//a'}])
        self.assertEqual(result['commit']['items'][0]['xpath'], '//a')

    def test_delete_modify_conflict_can_be_resolved_without_changing_identity(self):
        changed = self.commit(self.branch(), [dict(element(), xpath='//input')])
        removed = self.commit(self.branch('remove', self.bob), [], self.bob)
        self.merge(self.request(changed['branch']))
        request = self.request(removed['branch'], self.bob)
        with self.assertRaises(ValueError):
            self.merge(request, resolutions=[{'id': 'login', 'field': '__record__', 'value': element('swapped')}])
        result = self.merge(request, resolutions=[{'id': 'login', 'field': '__record__', 'value': None}])
        self.assertEqual(result['commit']['items'], [])

    def test_merge_rejects_stale_main_and_extra_resolution_fields(self):
        a = self.commit(self.branch(), [dict(element(), description='A')])
        b = self.commit(self.branch('second', self.bob), [dict(element(), xpath='//a')], self.bob)
        request = self.request(a['branch'])
        review = self.service.review_request(self.repo['id'], request['id'])
        self.merge(self.request(b['branch'], self.bob))
        with self.assertRaises(RuntimeError):
            self.service.merge_request(self.repo['id'], request['id'], self.body(
                expected_main=review['main_head'], expected_source=review['source_head'], resolutions=[]))
        with self.assertRaises(ValueError):
            self.merge(request, resolutions=[{'id': 'login', 'field': 'xpath', 'value': '//hidden'}])

    def test_same_name_additions_never_silently_replace_other_element(self):
        a = self.commit(self.branch(), [element(), element('new')])
        b = self.commit(self.branch('second', self.bob),
                        [element(), dict(element('other'), name='new')], self.bob)
        self.merge(self.request(a['branch']))
        request = self.request(b['branch'], self.bob)
        with self.assertRaises(ValueError):
            self.merge(request)
        self.assertEqual(len(self.service.get_repository(self.repo['id'])['head']['items']), 2)

    def test_mutations_are_idempotent_and_request_id_cannot_change_payload(self):
        payload = self.body(name='once', base_commit=self.repo['head'])
        branch = self.service.create_branch(self.repo['id'], self.alice, payload)
        self.assertEqual(self.service.create_branch(self.repo['id'], self.alice, payload), branch)
        with self.assertRaises(RuntimeError):
            self.service.create_branch(self.repo['id'], self.alice, dict(payload, name='different'))
        commit_body = self.body(expected_head=branch['head'], message='修改', items=[])
        first = self.service.commit_branch(self.repo['id'], branch['id'], self.alice, commit_body)
        self.assertEqual(self.service.commit_branch(self.repo['id'], branch['id'], self.alice, commit_body), first)
        request = self.request(first['branch'])
        review = self.service.review_request(self.repo['id'], request['id'])
        merge_body = self.body(expected_main=review['main_head'], expected_source=review['source_head'], resolutions=[])
        result = self.service.merge_request(self.repo['id'], request['id'], merge_body)
        self.assertEqual(self.service.merge_request(self.repo['id'], request['id'], merge_body), result)

    def test_device_receipt_recovers_accepted_write_without_exposing_other_devices(self):
        body = self.body(name='receipt', base_commit=self.repo['head'])
        branch = self.service.create_branch(self.repo['id'], self.alice, body)
        restored = ElementRepositoryService(self.path)
        self.assertEqual(restored.get_device_operation(self.alice, body['request_id']), branch)
        with self.assertRaises(KeyError):
            restored.get_device_operation(self.bob, body['request_id'])
        with self.assertRaises(KeyError):
            restored.get_device_operation(self.alice, uuid4().hex)
        for request_id in ('', '../other', [], 'x' * 129):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                restored.get_device_operation(self.alice, request_id)

    def test_close_can_be_resubmitted_and_restore_adds_history_without_rewriting(self):
        committed = self.commit(self.branch(), [])
        request = self.request(committed['branch'])
        closed = self.service.close_request(self.repo['id'], request['id'], self.body(
            expected_source=committed['branch']['head'], reason='请补充验证'))
        self.assertEqual(closed['state'], 'closed')
        merged = self.merge(self.request(committed['branch']))
        restored = self.service.restore(self.repo['id'], self.body(expected_head=merged['commit']['id'],
            commit_id=self.repo['head'], message='恢复最初版本'))
        self.assertEqual(restored['items'], [element()])
        self.assertEqual(restored['parents'], [merged['commit']['id']])
        self.assertEqual(self.service.get_commit(self.repo['id'], merged['commit']['id'])['items'], [])

    def test_create_open_close_and_restore_retries_return_original_result(self):
        payload = self.body(name='重复创建')
        created = self.service.create_repository(payload)
        self.assertEqual(self.service.create_repository(payload), created)
        committed = self.commit(self.branch(), [])
        payload = self.body(expected_head=committed['branch']['head'], title='删除元素')
        request = self.service.open_request(self.repo['id'], committed['branch']['id'], self.alice, payload)
        self.assertEqual(self.service.open_request(self.repo['id'], committed['branch']['id'], self.alice, payload), request)
        payload = self.body(expected_source=request['source_head'], reason='暂不合并')
        closed = self.service.close_request(self.repo['id'], request['id'], payload)
        self.assertEqual(self.service.close_request(self.repo['id'], request['id'], payload), closed)
        payload = self.body(expected_head=self.repo['head'], commit_id=committed['commit']['id'], message='恢复已审阅历史')
        restored = self.service.restore(self.repo['id'], payload)
        self.assertEqual(self.service.restore(self.repo['id'], payload), restored)
        self.assertEqual(restored['restored_from'], committed['commit']['id'])

    def test_concurrent_writers_cannot_both_advance_the_same_head(self):
        branch = self.branch()
        barrier = threading.Barrier(2)
        outcomes = []
        def write(xpath):
            service = ElementRepositoryService(self.path)
            barrier.wait()
            try:
                result = service.commit_branch(self.repo['id'], branch['id'], self.alice,
                    self.body(expected_head=branch['head'], message='并发修改', items=[dict(element(), xpath=xpath)]))
                outcomes.append(result['commit']['id'])
            except RuntimeError:
                outcomes.append('conflict')
        threads = [threading.Thread(target=write, args=(xpath,)) for xpath in ('//a', '//input')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes.count('conflict'), 1)


if __name__ == '__main__':
    unittest.main()
