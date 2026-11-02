"""Print exact installed application dependency versions, including transitives."""
from importlib.metadata import distribution

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOTS = ('pydantic', 'python-dotenv', 'PyMuPDF', 'pytesseract', 'Pillow',
         'extract-msg', 'openpyxl', 'fastapi', 'uvicorn', 'python-multipart',
         'pywin32', 'tzdata')


def installed_runtime():
    selected = {}
    pending = list(ROOTS)
    while pending:
        name = canonicalize_name(pending.pop())
        if name in selected:
            continue
        package = distribution(name)
        selected[name] = package.version
        for value in package.requires or []:
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
                pending.append(requirement.name)
    return selected


if __name__ == '__main__':
    print('# Windows runtime snapshot; generated from application dependencies only.')
    for name, version in sorted(installed_runtime().items()):
        print(f'{name}=={version}')
