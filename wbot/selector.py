"""命名元素选择器，使用 wbot 自有元素库。"""
from __future__ import annotations

from os import PathLike
from typing import Any

from .elements import ElementLibrary, validate_xpath


class Selector:
    def __init__(self, value, meta=None):
        record = dict(value) if isinstance(value, dict) else dict(meta or {}, xpath=value)
        self._record = record
        self._record['xpath'] = validate_xpath(record.get('xpath'))

    def xpath(self) -> str:
        return self._record['xpath']

    @property
    def name(self) -> str:
        return self._record.get('name', '')

    @property
    def group(self) -> str:
        return self._record.get('group', '默认')

    @property
    def frame(self) -> dict[str, Any] | None:
        return self.to_dict().get('frame')

    @property
    def url(self) -> str:
        return self._record.get('url', '')

    def to_dict(self) -> dict[str, Any]:
        from copy import deepcopy
        return deepcopy(self._record)

    def __str__(self) -> str:
        return self.xpath()


class SelectorStore:
    """path 为 SQLite 文件路径；省略时与 XPath Studio 共享默认元素库。"""
    def __init__(self, path: str | PathLike[str] | None = None) -> None:
        self.library = ElementLibrary(path)

    def get(self, name: str, group: str = '默认') -> Selector:
        """按名称和分组读取元素；托管运行时自动使用发布包中的元素快照。"""
        return Selector(self.library.get_by_name(name, group))

    def __call__(self, name: str, group: str = '默认') -> Selector:
        return self.get(name, group)
