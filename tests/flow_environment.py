"""Create an isolated flow environment from installed test dependencies, offline."""
import importlib.metadata
from pathlib import Path
import shutil
import sys
import venv


def prepare_environment(project):
    environment = Path(project) / '.venv'
    venv.EnvBuilder(with_pip=False, symlinks=False).create(environment)
    site = environment / ('Lib/site-packages' if sys.platform == 'win32' else
                          f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    for name in ('wbot', 'lxml'):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files:
            if relative.parts[0] != name and not relative.parts[0].endswith(('.dist-info', '.egg-info')):
                continue
            source = Path(distribution.locate_file(relative))
            target = site / relative
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    return environment
