"""在同一元素数据库中原子保存工作副本和共享版本基线。"""
import json

from wbot.elements import ElementLibrary, normalize_element
from wbot.element_versions import canonical_items


EMPTY_STATE = {'binding': None, 'baseline': [], 'pending': None, 'last_operation': None}


class ElementWorkspace(ElementLibrary):
    def __init__(self, path):
        super().__init__(path)
        with self._connect() as database:
            database.execute('CREATE TABLE IF NOT EXISTS shared_element_state '
                             '(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')

    @staticmethod
    def _state(database):
        row = database.execute('SELECT payload FROM shared_element_state WHERE id=1').fetchone()
        return json.loads(row['payload']) if row else dict(EMPTY_STATE)

    def snapshot(self):
        with self._connect() as database:
            database.execute('BEGIN')
            items = [self._decode(row) for row in database.execute('SELECT * FROM elements')]
            return canonical_items(items), self._state(database)

    def save(self, expected_state, state, *, expected_items=None, replacement=None):
        payload = json.dumps(state, ensure_ascii=False, allow_nan=False)
        prepared = None
        if replacement is not None:
            prepared = [normalize_element(item) for item in canonical_items(replacement)]
        with self._connect() as database:
            database.execute('BEGIN IMMEDIATE')
            if self._state(database) != expected_state:
                raise RuntimeError('工作副本状态已变化，请刷新后重试')
            current = [self._decode(row) for row in database.execute('SELECT * FROM elements')]
            if expected_items is not None and canonical_items(current) != expected_items:
                raise RuntimeError('本地元素已变化，请重新查看差异后重试；未覆盖任何元素')
            if prepared is not None:
                previous = {item['id']: item for item in current}
                database.execute('DELETE FROM elements')
                for item in prepared:
                    if item['id'] in previous:
                        item['created_at'] = previous[item['id']]['created_at']
                    item['frame'] = json.dumps(item['frame'], ensure_ascii=False, allow_nan=False)
                    self._write(database, item)
            database.execute('INSERT INTO shared_element_state VALUES (1, ?) '
                             'ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (payload,))
