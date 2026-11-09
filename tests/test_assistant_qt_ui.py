"""Qt 表单与窗口生命周期的行为回归；无桌面环境时使用离屏平台。"""
import importlib.util
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QTabWidget
    from app.assistant.qt_dialogs import ParameterDialog, JobDialog
    from app.assistant.qt_ui import AssistantWindow
    from app.assistant.qt_settings import SettingsPage


PACKAGE = {'id': 'demo@1.0.0', 'manifest': {'schemaVersion': 1, 'name': 'demo', 'version': '1.0.0',
    'entry': 'main.py', 'files': ['main.py'], 'requirements': {}, 'parameters': {
    'name': {'type': 'string', 'default': 'WBot', 'description': '问候对象'},
    'count': {'type': 'integer', 'required': True},
    'enabled': {'type': 'boolean', 'default': False},
}}}
JOB = {'id': 'job-one', 'package_id': 'demo@1.0.0', 'state': 'running', 'parameters': {},
       'created_at': 1700000000, 'started_at': 1700000001, 'finished_at': None,
       'result': None, 'error': ''}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.offline = False
        self.pending_run = None
        self.packages = [PACKAGE]
        self.jobs = []
        self.job_total = None
        self.job = JOB
        self.defer_job = False
        self.pending_job = None

    def request(self, method, path, body=None, on_success=None, on_error=None):
        self.calls.append((method, path, body))
        if method == 'POST' and path == '/api/jobs':
            self.pending_run = (on_success, on_error)
            return None
        if self.defer_job and method == 'GET' and path == '/api/jobs/job-one':
            self.pending_job = on_success
            return None
        if self.offline:
            QTimer.singleShot(0, lambda: on_error('后台服务未连接'))
            return None
        responses = {'/api/packages': {'items': self.packages},
                     '/api/updates': {'update': {'status': 'idle', 'version': '0.7.0', 'install_supported': False}},
                     '/api/settings': {'settings': {'server_url': '', 'device_name': '',
                                                   'binding_state': 'unconfigured'}},
                     '/api/jobs/summary': {'items': self.jobs, 'total': self.job_total or len(self.jobs)},
                     '/api/jobs/job-one': {'job': self.job}, '/api/jobs/job-one/log': {'log': '工作中\n'},
                     '/api/jobs/job-one/stop': {'job': dict(self.job, state='stopping')}}
        QTimer.singleShot(0, lambda: on_success(responses[path]))
        return None


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6-Essentials')
class AssistantQtUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.client = FakeClient()
        self.widgets = []

    def tearDown(self):
        for widget in reversed(self.widgets):
            if hasattr(widget, 'timer'):
                widget.timer.stop()
            if isinstance(widget, AssistantWindow):
                widget.tray_available = False
            widget.close()
            widget.deleteLater()
        QTest.qWait(10)

    def dialog(self):
        dialog = ParameterDialog(self.client, PACKAGE)
        self.widgets.append(dialog)
        dialog.show()
        QTest.qWait(5)
        return dialog

    def test_parameter_types_and_uncertain_retry_keep_same_request(self):
        dialog = self.dialog()
        dialog.fields['name'].setText('平台')
        QTest.keyClicks(dialog.fields['count'], '3')
        QTest.mouseClick(dialog.run_button, Qt.MouseButton.LeftButton)
        first = self.client.calls[-1][2]
        self.assertEqual(first['parameters'], {'name': '平台', 'count': 3, 'enabled': False})
        self.client.pending_run[1]('响应未确认')
        dialog.submit()
        self.assertEqual(self.client.calls[-1][2]['request_id'], first['request_id'])
        self.client.pending_run[1]('响应未确认')
        dialog.fields['count'].setText('4')
        dialog.submit()
        self.assertNotEqual(self.client.calls[-1][2]['request_id'], first['request_id'])

    def test_invalid_integer_never_submits_and_closed_dialog_ignores_response(self):
        dialog = self.dialog()
        dialog.fields['count'].setText('1.5')
        dialog.submit()
        self.assertEqual(self.client.calls, [])
        self.assertIn('整数', dialog.error.text())
        dialog.fields['count'].setText('2')
        dialog.submit()
        accepted = []
        dialog.submitted.connect(accepted.append)
        dialog.reject()
        self.client.pending_run[0]({'job': JOB})
        self.assertEqual(accepted, [])

    def test_long_string_input_is_submitted_without_silent_truncation(self):
        dialog = self.dialog()
        content = '完整参数' * 10000
        dialog.fields['name'].setText(content)
        dialog.fields['count'].setText('1')
        dialog.submit()
        self.assertEqual(self.client.calls[-1][2]['parameters']['name'], content)

    def test_refresh_preserves_open_form_and_offline_preserves_catalog(self):
        window = AssistantWindow(self.client, 'test-state')
        self.widgets.append(window)
        window.show()
        QTest.qWait(30)
        window.package_list.setCurrentRow(0)
        window.open_run_dialog()
        dialog = window.active_parameter_dialog
        dialog.fields['name'].setText('尚未提交的输入')
        window.refresh()
        QTest.qWait(30)
        self.assertEqual(dialog.fields['name'].text(), '尚未提交的输入')
        self.assertEqual(window.package_list.currentItem().data(256), PACKAGE['id'])
        self.client.offline = True
        window.refresh()
        QTest.qWait(30)
        self.assertEqual(window.package_list.count(), 1)
        self.assertFalse(window.run_button.isEnabled())
        self.assertFalse(dialog.run_button.isEnabled())

    def test_import_selects_new_package_after_clearing_search(self):
        window = AssistantWindow(self.client, 'test-state')
        self.widgets.append(window)
        window.show()
        QTest.qWait(20)
        window.search.setText('demo')
        imported = {'id': 'new@1.0.0', 'manifest': dict(PACKAGE['manifest'], name='new')}
        self.client.packages = [PACKAGE, imported]
        window._package_imported({'package': imported})
        QTest.qWait(20)
        self.assertEqual(window.search.text(), '')
        self.assertEqual(window.package_list.currentItem().data(256), imported['id'])

    def test_history_polls_summary_and_displays_bounded_history_count(self):
        summary = {key: JOB[key] for key in ('id', 'package_id', 'state', 'created_at')}
        self.client.jobs = [dict(summary, id=f'job-{index}', state='succeeded') for index in range(200)]
        self.client.job_total = 205
        window = AssistantWindow(self.client, 'test-state')
        self.widgets.append(window)
        window.show()
        QTest.qWait(30)
        paths = [path for method, path, _ in self.client.calls if method == 'GET']
        self.assertIn('/api/jobs/summary', paths)
        self.assertNotIn('/api/jobs', paths)
        self.assertEqual(window.job_list.count(), 200)
        self.assertIn('最近 200 条', window.history_count.text())
        self.assertIn('205', window.history_count.text())

    def test_close_to_tray_never_stops_background_execution(self):
        window = AssistantWindow(self.client, 'test-state')
        self.widgets.append(window)
        window.tray_available = True
        window.show()
        QTest.qWait(20)
        window.close()
        self.assertFalse(window.isVisible())
        window.show_window()
        self.assertTrue(window.isVisible())
        self.assertFalse(any(path.endswith('/stop') for _, path, _ in self.client.calls))

    def test_settings_button_reuses_one_page_and_updates_tooltip(self):
        window = AssistantWindow(self.client, 'test-state')
        self.widgets.append(window)
        window.show()
        QTest.qWait(20)
        QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
        window.open_settings()
        QTest.qWait(20)
        self.assertIsInstance(window.settings_page, SettingsPage)
        self.assertFalse(window.settings_page.isWindow())
        self.assertEqual(window.pages.count(), 2)
        self.assertEqual(window._dialogs, [])
        self.assertIn('OC：尚未连接', window.settings_button.toolTip())

    def test_job_stop_targets_only_selected_job(self):
        dialog = JobDialog(self.client, JOB)
        self.widgets.append(dialog)
        dialog.show()
        QTest.qWait(20)
        dialog.stop_job()
        QTest.qWait(20)
        posts = [(method, path) for method, path, _ in self.client.calls if method == 'POST']
        self.assertEqual(posts, [('POST', '/api/jobs/job-one/stop')])
        self.assertEqual(dialog.job['state'], 'stopping')
        self.assertFalse(dialog.stop_button.isEnabled())

    def test_old_poll_cannot_revert_an_accepted_stop(self):
        dialog = JobDialog(self.client, JOB)
        self.widgets.append(dialog)
        dialog.show()
        QTest.qWait(20)
        self.client.defer_job = True
        dialog.refresh()
        dialog.stop_job()
        QTest.qWait(20)
        self.client.pending_job({'job': JOB})
        self.assertEqual(dialog.job['state'], 'stopping')
        self.assertFalse(dialog.stop_button.isEnabled())

    def test_unchanged_detail_poll_preserves_selection_and_scroll(self):
        self.client.job = dict(JOB, state='succeeded', result={'rows': list(range(300))},
                               parameters={'name': '需要查看的输入'})
        dialog = JobDialog(self.client, self.client.job)
        self.widgets.append(dialog)
        dialog.show()
        dialog.findChild(QTabWidget).setCurrentIndex(1)
        QTest.qWait(20)
        for view in (dialog.result_view, dialog.parameters_view):
            cursor = view.textCursor()
            cursor.setPosition(0)
            cursor.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
            view.setTextCursor(cursor)
        scrollbar = dialog.result_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        position = scrollbar.value()
        self.assertGreater(position, 0)
        dialog.refresh()
        QTest.qWait(20)
        self.assertEqual(scrollbar.value(), position)
        for view in (dialog.result_view, dialog.parameters_view):
            self.assertEqual(len(view.textCursor().selectedText()), 10)


if __name__ == '__main__':
    unittest.main()
