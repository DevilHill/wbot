"""验证任务运行上下文无需编辑器即可交换经过校验的 JSON。"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wbot import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / 'input.json'
        self.result = self.root / 'result.json'
        self.input.write_text(json.dumps({'job_id': 'job-1', 'parameters': {'name': '中文'}}), encoding='utf-8')
        self.environment = patch.dict(os.environ, {
            'WBOT_RUN_INPUT': str(self.input), 'WBOT_RUN_RESULT': str(self.result)})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_parameters_and_result_round_trip(self):
        self.assertEqual(runtime.parameters(), {'name': '中文'})
        self.assertEqual(runtime.job_id(), 'job-1')
        runtime.set_result({'message': runtime.parameters()['name'], 'count': 3})
        self.assertEqual(json.loads(self.result.read_text(encoding='utf-8')), {'message': '中文', 'count': 3})

    def test_missing_context_is_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            for action in (runtime.parameters, runtime.job_id, lambda: runtime.set_result({})):
                with self.assertRaisesRegex(RuntimeError, '运行上下文'):
                    action()

    def test_invalid_result_does_not_replace_previous_output(self):
        runtime.set_result({'ok': True})
        for result in ([], {'invalid': float('nan')}, {'large': 'x' * 1_100_000}):
            with self.subTest(result_type=type(result).__name__):
                with self.assertRaises((TypeError, ValueError)):
                    runtime.set_result(result)
        self.assertEqual(json.loads(self.result.read_text()), {'ok': True})

    def test_malformed_context_is_rejected(self):
        self.input.write_text('{"parameters": []}', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, '运行上下文'):
            runtime.parameters()


if __name__ == '__main__':
    unittest.main()
