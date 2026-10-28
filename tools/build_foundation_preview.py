#!/usr/bin/env python3
"""Build the reviewed foundation design in an isolated, fictional workbench.

Reuses the actual desktop UI and its read-only demo adapter. No production
database, installed files, or public website output is opened or modified.
"""
import argparse
import shutil
import tempfile
from pathlib import Path

from build_site import ROOT, copy_ui, export_showcase, packed, replace_once
from seed_showcase import MAIN_PROJECT, seed

MARKER = '.rws-foundation-preview'


def adapt_ui(destination):
    source = ROOT / 'tools/foundation-preview'
    for name in ('preview-ui.js', 'preview.css'):
        shutil.copy2(source / name, destination / name)

    index = (destination / 'index.html').read_text()
    index = replace_once(index, '<script src="app.js"></script>',
                         '<script src="preview-ui.js"></script><script src="app.js"></script>', 'preview helpers')
    index = replace_once(index, '</head>', '<link rel="stylesheet" href="preview.css"></head>', 'preview styling')
    (destination / 'index.html').write_text(index)

    for name in ('studio-model.js', 'evidence.js'):
        text = (destination / name).read_text()
        text = text.replace("foundations:'模型、数据与基线'", "foundations:'基础模型'")
        text = text.replace("approach:'当前研究路线'", "approach:'研究起点与路线'")
        (destination / name).write_text(text)

    studio = (destination / 'studio.js').read_text().replace('模型、数据与基线尚未登记', '基础模型尚未登记')
    (destination / 'studio.js').write_text(studio)

    app = (destination / 'app.js').read_text()
    app = replace_once(app, "${button('experiment',e.id,'实验详情')}",
                       "${window.RWSFoundationPreview.experiment(e)}${button('experiment',e.id,'实验详情')}", 'experiment model and comparison')
    (destination / 'app.js').write_text(app)

    evidence = (destination / 'evidence.js').read_text()
    evidence = replace_once(evidence, "+refs('评估约定',r.protocolRef?[r.protocolRef]:[])",
                            "+facts([['使用模型',r.config?.base_model],['模型版本',r.config?.model_version],['本次用途',r.config?.comparison_role],['参照来源',r.config?.reference_source]])+refs('本实验比较的方法',r.config?.comparison_code_refs||[])+refs('评估约定',r.protocolRef?[r.protocolRef]:[])", 'experiment reader model and actual code links')
    (destination / 'evidence.js').write_text(evidence)

    demo = (destination / 'demo-ui.js').read_text()
    demo = replace_once(demo, "const research = window.RP_DATA.hypotheses.find(row => row.ref.id === 'H5' && row.isCurrent);\n      if (research)",
                        "const research = window.RP_DATA.hypotheses.find(row => row.ref.id === 'H1' && row.isCurrent);\n      if (research)", 'start at research origin')
    demo = demo.replace('<strong>虚构 · 离线 · 只读</strong>', '<strong>设计预览 · 虚构数据</strong>')
    demo = demo.replace('图形与数值人为编排，未运行模型。可选择节点、聚焦视图、查看材料与报告。',
                        '现有工作台上的基础模型与实验引用预览；图形与数值为示意，未执行模型。')
    demo = demo.replace('<a href="../index.html" target="_top">返回官网 ↗</a>', '')
    (destination / 'demo-ui.js').write_text(demo)


def build(output):
    output = Path(output).expanduser().resolve()
    if output == ROOT or output in ROOT.parents or output.is_relative_to(ROOT / 'web') or output.is_relative_to(ROOT / 'site'):
        raise ValueError('Use a dedicated preview output directory')
    if output.exists() and any(output.iterdir()) and not (output / MARKER).is_file():
        raise ValueError('Refusing to replace a directory not owned by this preview builder')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.foundation-preview-', dir=output.parent) as temp:
        stage = Path(temp) / 'preview'
        copy_ui(stage)
        metadata = seed(Path(temp) / 'fictional.sqlite3', stage / 'assets/showcase', preview_models=True)
        exported = export_showcase(Path(temp) / 'fictional.sqlite3', metadata)
        (stage / 'showcase.json').write_text(packed(exported), encoding='utf-8')
        adapt_ui(stage)
        (stage / MARKER).write_text('Isolated fictional workbench foundation preview.\n')
        if output.exists():
            shutil.rmtree(output)
        stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/foundation-workbench-preview')
    args = parser.parse_args()
    destination = build(args.output)
    print(str(destination / 'index.html') + '?projectId=' + MAIN_PROJECT)
