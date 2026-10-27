#!/usr/bin/env python3
"""Create a portable code block from a contract-first template."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

KINDS = ('inference', 'analysis', 'evaluation', 'report')
TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'


def scaffold(kind, destination, title=None, template_root=TEMPLATES):
    if kind not in KINDS:
        raise ValueError('Choose inference, analysis, evaluation or report.')
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError('Destination already exists; choose a new directory.')
    source = Path(template_root) / kind
    if not source.is_dir():
        raise ValueError('Template directory is unavailable: ' + kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rws-scaffold-', dir=str(target.parent)) as folder:
        stage = Path(folder) / 'block'
        shutil.copytree(source, stage)
        shutil.copy2(Path(template_root) / '_shared' / 'runtime.py', stage / '_runtime.py')
        contract_path = stage / 'contract.json'
        contract = json.loads(contract_path.read_text(encoding='utf-8'))
        if title:
            contract['spec']['title'] = title
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        stage.rename(target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', required=True, choices=KINDS)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--title')
    args = parser.parse_args(argv)
    try:
        target = scaffold(args.kind, args.destination, args.title)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(str(target))


if __name__ == '__main__':
    main()
