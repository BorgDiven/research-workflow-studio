#!/usr/bin/env python3
"""Build a backend-free public website from a fresh fictional showcase only.

No database input is accepted. Existing research databases and material folders
are never opened. Production web sources are read, never edited.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rws.core import READS, Store, tool_definitions
from tools.seed_showcase import MAIN_PROJECT, PROJECTS, seed

MARKER = '.rws-public-build'
POLL = "  setInterval(()=>{if(document.visibilityState==='visible'&&!busy)load(activeProjectId,{quiet:true});},15000);"


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def ref_key(ref):
    return packed([ref['projectId'], ref['type'], ref['id'], ref['version']])


def context_key(args):
    return packed([args['projectId'], ref_key(args['researchRef']) if args.get('researchRef') else None,
                   ref_key(args['experimentRef']) if args.get('experimentRef') else None])


def selection_key(refs):
    return packed([ref_key(ref) for ref in refs])


def relative_assets(value):
    """Rewrite even frozen report records; reject unexpected absolute locations."""
    if isinstance(value, dict):
        return {key: relative_assets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [relative_assets(item) for item in value]
    if isinstance(value, str):
        if value.startswith('/assets/showcase/'):
            suffix = value.removeprefix('/assets/showcase/')
            if '/' in suffix or suffix.startswith('.'):
                raise ValueError('Unexpected showcase asset location')
            return 'assets/showcase/' + suffix
        if value.startswith(('/materials/', '/Users/', '/home/', 'file:', 'http://', 'https://', '/api/')):
            raise ValueError('Non-showcase location in generated data')
    return value


def export_showcase(db, metadata):
    store = Store(db)
    try:
        home = store.snapshot()
        if {p['id'] for p in home['projects']} != set(PROJECTS) or not all(p.get('demo') for p in home['projects']):
            raise ValueError('Public export accepts only the three fictional showcase projects')
        snapshots = {pid: store.snapshot(pid) for pid in PROJECTS}
        records, contexts, objects, object_ids, metrics = {}, {}, [], {}, {}

        def collect(value):
            if isinstance(value, dict):
                if 'ref' in value and 'record' in value:
                    records[ref_key(value['ref'])] = value
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(snapshots)
        for pid, snapshot in snapshots.items():
            current = snapshot['records']
            spec_ids = {e['ref']['id'] for e in current if e['ref']['type']=='spec' and e['record'].get('processMetrics')}
            code_ids = {e['ref']['id'] for e in current if e['ref']['type']=='code' and e['record'].get('specRef', {}).get('id') in spec_ids}
            run_refs = [e['ref'] for e in current if e['ref']['type']=='run' and e['record']['codeRef']['id'] in code_ids]
            if run_refs:
                metrics[pid] = store.call('rws_metrics_query', {'projectId': pid, 'runRefs': run_refs, 'limit': 5000})['result']
                if metrics[pid]['truncated']:
                    raise ValueError('Fictional metrics exceed the bounded static package')
            bases = [{'projectId': pid}]
            bases += [{'projectId': pid, 'researchRef': e['ref']} for e in current if e['ref']['type'] == 'research']
            for entry in current:
                if entry['ref']['type'] == 'experiment':
                    bases.append({'projectId': pid, 'researchRef': entry['record']['researchRef'], 'experimentRef': entry['ref']})
            # These cover every selection emitted by RPWorkbench: no selection,
            # a code or specification, an execution, or that execution with its code.
            selections = [[]] + [[e['ref']] for e in current if e['ref']['type'] in ('code', 'spec')]
            for entry in current:
                if entry['ref']['type'] in ('run', 'evaluation', 'analysis', 'report'):
                    selections.append([entry['ref']])
                    code = entry['record'].get('codeRef') or entry['record'].get('generatorCodeRef')
                    if code:
                        selections.append([code, entry['ref']])
            for args in bases:
                base, variants = None, {}
                for selected in selections:
                    response = store.call('rws_get_context', dict(args, selectionRefs=selected))['result']
                    indexes = []
                    for obj in response.pop('objects'):
                        serialized = packed(obj)
                        if serialized not in object_ids:
                            object_ids[serialized] = len(objects)
                            objects.append(obj)
                        indexes.append(object_ids[serialized])
                    variant = {key: response.pop(key) for key in ('objectCount', 'objectsTruncated')}
                    variant['objectIndexes'] = indexes
                    if base is None:
                        base = response
                    elif base != response:
                        raise ValueError('Context semantics changed: selection now affects non-object fields')
                    variants[selection_key(selected)] = variant
                contexts[context_key(args)] = {'base': base, 'variants': variants}
        return relative_assets({
            'schemaVersion': 1, 'mode': 'offline-fictional-readonly', 'mainProjectId': MAIN_PROJECT,
            'notice': metadata['notice'], 'home': home, 'snapshots': snapshots,
            'records': records, 'contexts': contexts, 'contextObjects': objects, 'metrics': metrics,
            'mutationNames': [tool['name'] for tool in tool_definitions() if tool['name'] not in READS],
            'comparisonRef': metadata['comparison'], 'selectedResearchRef': metadata['selectedResearch'],
        })
    finally:
        store.close()


def replace_once(text, old, new, description):
    if text.count(old) != 1:
        raise ValueError('Production UI changed; review the public adaptation: ' + description)
    return text.replace(old, new)


def copy_ui(destination):
    web, runtime = ROOT / 'web', ROOT / 'site/demo-runtime'
    destination.mkdir()
    # Only runtime source files; never copy a database, tests or research material.
    for source in web.iterdir():
        if source.is_file() and source.suffix in ('.js', '.css', '.html') and source.name != 'live-api.js':
            if source.is_symlink():
                raise ValueError('Production UI inputs must not be symbolic links')
            shutil.copy2(source, destination / source.name)
    for name in ('demo-api.js', 'demo-ui.js', 'demo.css'):
        shutil.copy2(runtime / name, destination / name)
    index = (destination / 'index.html').read_text()
    index = replace_once(index, '<body>', '<body data-demo="offline-fictional-readonly">', 'demo body marker')
    index = replace_once(index, '<script src="live-api.js"></script>', '<script src="demo-api.js"></script><script src="demo-ui.js"></script>', 'static data adapter')
    index = replace_once(index, '</head>', '<link rel="stylesheet" href="demo.css"></head>', 'read-only styling')
    index = index.replace('正在连接…', '正在读取虚构演示…').replace('共享记录', '虚构只读演示').replace('浏览器与 MCP 共用记录', '随网站提供的虚构静态数据').replace('设计与接口文档 ↗', '演示说明与示例 ↗')
    (destination / 'index.html').write_text(index)
    (destination / 'data.js').write_text('/* Populated only from the packaged fictional showcase. */\nwindow.RP_DATA = window.RWSAdapter.empty();\n')

    studio = (destination / 'studio.js').read_text()
    studio = replace_once(studio, POLL, '  // Static showcase: no backend polling.', '15-second live polling')
    studio = replace_once(studio, "const el=$('#live-status');el.textContent=text;", "const el=$('#live-status');el.textContent=bad?text:'离线演示 · 只读';", 'connection status')
    replacements = {
        '服务器保存': '随网站提供的虚构快照', '合成试装数据': '虚构演示数据',
        '浏览器与 MCP 读取同一份记录；执行与研究判断仍由你决定。': '仅浏览内置虚构材料；不连接 MCP、AI 或研究后端。',
        '来自当前服务器记录；不发送消息，也不执行任务。': '来自构建时导出的虚构上下文；未连接 AI，不发送消息或执行任务。',
        "openDialog('准备研究对话'": "openDialog('查看演示上下文'",
        '共享后端项目列表': '虚构演示项目列表', "p.demo?'合成试装':'共享记录'": "'虚构只读演示'",
    }
    for old, new in replacements.items():
        studio = studio.replace(old, new)
    (destination / 'studio.js').write_text(studio)
    app = (destination / 'app.js').read_text().replace('已载入共享记录', '已载入虚构演示').replace('共享后端项目列表', '虚构演示项目列表').replace('正在连接共享后端…', '正在读取虚构演示…')
    (destination / 'app.js').write_text(app)

    model = (destination / 'live-model.js').read_text()
    pattern = r"  function safeURL\(value\)\{.*?\n  \}\n"
    matches = list(re.finditer(pattern, model, flags=re.S))
    if len(matches) != 1:
        raise ValueError('Production safeURL changed; review the static asset adaptation')
    # Keep URLs relative to demo/index.html; the live helper resolves at host root.
    safe = """  function safeURL(value){
    if(typeof value!=='string'||!/^assets\\/showcase\\/[a-z0-9-]+\\.(svg|txt)$/.test(value))return null;
    return value;
  }
"""
    match = matches[0]
    model = model[:match.start()] + safe + model[match.end():]
    model = model.replace("label:'共享后端'", "label:'虚构只读演示'").replace("p?.demo?'合成试装记录':'服务器记录'", "'虚构演示快照'")
    (destination / 'live-model.js').write_text(model)
    evidence = (destination / 'evidence.js').read_text()
    lines = [line for line in evidence.splitlines() if 'const links=candidates.flatMap(' in line]
    if len(lines) != 1:
        raise ValueError('Production source-link reader changed; review the static adaptation')
    evidence = evidence.replace(lines[0], "    const links=candidates.flatMap(([label,value])=>{const url=A.safeURL(value);if(!url||seen.has(url))return [];seen.add(url);return [{label,url}];});")
    evidence = evidence.replace('从共享后端读取项目基础、当前位置与已登记材料。', '读取构建时导出的虚构项目基础、当前位置与演示材料。').replace('<h2>准备研究对话</h2>', '<h2>查看演示上下文</h2>')
    (destination / 'evidence.js').write_text(evidence)
    (destination / 'docs').mkdir()
    shutil.copy2(runtime / 'help.html', destination / 'docs/index.html')
    shutil.copy2(web / 'docs/format-guide.md', destination / 'docs/format-guide.md')
    shutil.copytree(web / 'examples', destination / 'examples')


def build_site(output=ROOT / '.local/public-site'):
    output = Path(output).expanduser().resolve()
    if output == ROOT or output in ROOT.parents or output.is_relative_to(ROOT / 'web') or output.is_relative_to(ROOT / 'site'):
        raise ValueError('Choose a dedicated generated output directory')
    if output.exists() and any(output.iterdir()) and not (output / MARKER).is_file():
        raise ValueError('Refusing to replace a nonempty directory not created by this builder')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rws-site-', dir=output.parent) as stage_dir:
        stage = Path(stage_dir) / 'site'
        stage.mkdir()
        site = ROOT / 'site'
        for source in site.rglob('*'):
            relative = source.relative_to(site)
            if relative.parts[0] == 'demo-runtime' or any(part.startswith('.') for part in relative.parts):
                continue
            if source.is_symlink():
                raise ValueError('Public site inputs must not contain symbolic links')
            if source.is_file() and source.suffix in ('.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.json'):
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        copy_ui(stage / 'demo')
        with tempfile.TemporaryDirectory(prefix='rws-fictional-seed-') as isolated:
            db = Path(isolated) / 'showcase.sqlite3'
            metadata = seed(db, stage / 'demo/assets/showcase')
            exported = export_showcase(db, metadata)
        (stage / 'demo/showcase.json').write_text(packed(exported), encoding='utf-8')
        (stage / MARKER).write_text('Generated fictional read-only public website.\n')
        (stage / '.nojekyll').touch()
        if output.exists():
            shutil.rmtree(output)
        stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/public-site')
    args = parser.parse_args()
    destination = build_site(args.output)
    print('Built public site: ' + str(destination))
    print('Demo entry: demo/index.html?projectId=' + MAIN_PROJECT)
