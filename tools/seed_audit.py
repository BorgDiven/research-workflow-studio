#!/usr/bin/env python3
"""Create an isolated, explicitly synthetic large UI audit fixture; never run models."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
import time

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from rws.core import Store

DENSE, EMPTY = 'qa-dense-20261025', 'qa-empty-20261025'
QA = '合成 QA，仅检查界面和记录关系；没有执行模型、计算指标或验证科研结论。'


def seed(destination, base=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise SystemExit('Refusing to overwrite an existing database. Choose a fresh isolated --db path.')
    if base and destination == Path(base).resolve():
        raise SystemExit('Source and destination must differ.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if base:
        source_path = Path(base).resolve()
        if not source_path.is_file():
            raise SystemExit('Read-only base database does not exist: ' + str(source_path))
        if Path(str(source_path) + '-wal').exists():
            raise SystemExit('Use a frozen backup without a WAL file as --base; never a live database.')
        with sqlite3.connect(source_path.as_uri() + '?mode=ro&immutable=1', uri=True) as source:
            with sqlite3.connect(str(destination)) as target:
                source.backup(target)
    store = Store(destination)
    counter, revisions, refs = 0, {}, {}

    def write(operation, project_id=None, actor='model', **arguments):
        nonlocal counter
        counter += 1
        arguments['requestId'] = 'large-qa-%04d' % counter
        if project_id:
            arguments.update(projectId=project_id, expectedRevision=revisions[project_id])
        response = store.call(operation, arguments, actor=actor)
        if response.get('projectId'):
            revisions[response['projectId']] = response['revision']
        return response['result']

    def record(operation, key, **fields):
        value = write(operation, DENSE, record=dict(id=key, **fields))
        refs[key] = value['ref']
        return value['ref']

    started = time.perf_counter()
    try:
        write('rws_project_create', projectId=DENSE, name='合成 QA · 36 研究节点与 600 图密集工作台', goal=QA + ' 覆盖研究树、阶段聚焦、代码分行、长标题、图像分页与固定报告。', domain='隔离 UI 压力检查', demo=True)
        write('rws_project_create', projectId=EMPTY, name='合成 QA · 空项目与外部材料入口', goal=QA + ' 此项目故意没有研究、实验或材料，供检查首次进入和创建流程。', domain='隔离 UI 空态检查', demo=True)
        # Human authority is intentionally simulated only inside this isolated QA DB.
        write('rws_project_stages_set', DENSE, actor='human', activeStages=['idea', 'formal', 'ablation'])
        proposal = write('rws_overview_propose', DENSE, baseRevision=1, fields={
            'foundations': '基础模型：不存在。所有图片均指向同一张随应用提供的演示素材。' + QA,
            'approach': '按 3 个阶段组织 36 个研究节点，保留分支与合并关系；用 6 个登记代码版本构造 100 个样本的对齐矩阵。',
            'resources': '仅本地 SQLite 合成记录、静态示意图片，无 GPU、无远程程序、无模型调用。',
            'consensus': '已有记录只说明浏览器能否正确显示来源、关系与大量材料。'}, reason='合成 QA 项目基础，供检查人类确认后的展示。')
        write('rws_overview_apply', DENSE, actor='human', proposalRef=proposal['ref'], baseRevision=1)

        stages, research = ['idea', 'formal', 'ablation'], []
        local_parents = [[], [0], [0], [1], [1, 2], [2], [3, 4], [4], [5], [6, 7], [7, 8], [9, 10]]
        for stage_index, stage in enumerate(stages):
            branch = []
            for index, parent_indices in enumerate(local_parents):
                number = stage_index * 12 + index + 1
                title = '合成 QA %02d · %s' % (number, ['基础观察', '分支探针', '条件探索', '局部诊断', '合并观察', '替代方向', '证据复用', '小样本检查', '反例分析', '整合解释', '条件边界', '阶段归纳'][index])
                if index == 4:
                    title += '：当研究问题标题非常长而且需要同时保留父节点连线与当前阶段高亮时应该保持可读并允许完整查看而不把其他卡片撑开'
                if index == 7:
                    title += 'SyntheticQAUnbrokenResearchTitleWithNoSpacesForOverflowInspection' * 3
                parents = [branch[i] for i in parent_indices]
                if not index and research:
                    parents = research[-2:]
                kind = 'hypothesis' if index % 3 == 1 else 'exploration'
                fields = dict(title=title, question=QA + ' 检查此节点的位置、父子关系和材料详情。', kind=kind, stage=stage, parentRefs=parents)
                if kind == 'hypothesis':
                    fields['hypothesis'] = '合成占位命题：多分支结构在缩略与聚焦后仍应保留逻辑关系。'
                branch.append(record('rws_research_save', 'H%02d' % number, **fields))
            research.extend(branch)

        codes = []
        for index in range(6):
            codes.append(record('rws_code_register', 'C%d' % (index + 1), title='合成 QA · 推理版本 %d（没有可执行源码）' % (index + 1), kind='inference', version='qa-v%d' % (index + 1), source={'description': QA}, parentRefs=codes[-1:] if codes else []))
        evaluation_code = record('rws_code_register', 'EC1', title='合成 QA · 评估格式记录器', kind='evaluation', version='qa-v1', source={'description': QA}, parentRefs=[])
        analysis_code = record('rws_code_register', 'AC1', title='合成 QA · 分析格式记录器', kind='analysis', version='qa-v1', source={'description': QA}, parentRefs=[])
        record('rws_code_register', 'RC1', title='合成 QA · 固定报告模板', kind='report', version='qa-v1', source={'description': QA}, parentRefs=[])
        experiments, runs, groups = [], [], []
        node_indices = [3, 11, 15, 23, 27, 35]
        for index, node_index in enumerate(node_indices):
            experiment = record('rws_experiment_save', 'E%d' % (index + 1), title='合成 QA · 第 %d 组 100 个样本' % (index + 1), researchRef=research[node_index], config={'synthetic': True, 'cfg': 4, 'steps': 20}, status='completed')
            experiments.append(experiment)
            run = record('rws_run_register', 'R%d' % (index + 1), title='合成 QA · 完成状态占位 %d（未运行模型）' % (index + 1), kind='inference', codeRef=codes[index], experimentRef=experiment, inputRefs=[], config={'synthetic': True, 'variant': index + 1, 'cfg': 4, 'steps': 20}, status='completed', notes=QA)
            runs.append(run)
            record('rws_conversation_save', 'S%d' % (index + 1), title='合成 QA · 会话占位 %d（无真实聊天）' % (index + 1), uri='qa-unavailable://conversation/%d' % (index + 1), researchRef=research[node_index], experimentRef=experiment, summary=QA)
            group = []
            for sample in range(1, 101):
                group.append(record('rws_artifact_register', 'IMG-%d-%03d' % (index + 1, sample), title='合成 QA · V%d / 样本 %03d' % (index + 1, sample), kind='image', producerRef=run, sampleId='S%03d' % sample, config={'synthetic': True, 'variant': index + 1, 'cfg': 4, 'steps': 20, 'seed': 1000 + sample}, uri='/assets/demo-sheet.png', availability='available', description='同一张示意素材重复引用，非模型输出。'))
            groups.append(group)
        for index, experiment in enumerate(experiments):
            write('rws_usage_save', DENSE, id='U%d-output' % (index + 1), experimentRef=experiment, artifactRefs=groups[index], role='observation', label='合成 QA · 本组 100 张示意材料')
            if index:
                write('rws_usage_save', DENSE, id='U%d-baseline' % (index + 1), experimentRef=experiment, artifactRefs=groups[0], role='control', label='合成 QA · 引用 V1 的固定材料，生产者不变')
        all_images = [ref for group in groups for ref in group]
        comparison = record('rws_comparison_save', 'CMP600', title='合成 QA · 100 样本 × 6 版本固定对比', inputRefs=all_images, fixedConditions={'synthetic': True, 'cfg': 4, 'steps': 20, 'sampleCount': 100, 'seedRule': '1000 + sampleIndex'}, varyingConditions=['inferenceCode', 'variant'])
        protocol = record('rws_protocol_register', 'P1', title='合成 QA · 宽表、长曲线与图集格式', version='qa-v1', inputKind='artifact', metrics=[], preprocessing='无计算，仅测试输入格式', aggregation='无统计结论', missingPolicy='所有值都是固定合成占位')
        columns = [{'key': 'sample', 'label': '合成样本', 'type': 'string'}] + [{'key': 'q%02d' % i, 'label': ('QA列%02d' % i) + ('VeryLongUnbrokenColumnLabelForOverflowInspection' if i == 12 else ''), 'type': 'number'} for i in range(1, 24)]
        table = {'kind': 'table', 'name': 'synthetic-wide-table', 'label': '合成 QA · 24 列 × 100 行，无测量意义', 'columns': columns, 'rows': [dict({'sample': 'S%03d' % sample}, **{'q%02d' % i: round((sample + i) / 100.0, 3) for i in range(1, 24)}) for sample in range(1, 101)]}
        series = {'kind': 'series', 'name': 'synthetic-long-series', 'label': '合成 QA · 1600 点周期曲线，无训练记录', 'xAxis': {'label': '合成索引', 'unit': 'index'}, 'yAxis': {'label': '合成占位值', 'unit': 'QA'}, 'points': [[i, (i % 100) / 100.0] for i in range(1600)]}
        images = {'kind': 'image-set', 'name': 'synthetic-gallery', 'label': '合成 QA · 600 图分页', 'items': [{'artifactRef': ref, 'sampleId': 'S%03d' % (i % 100 + 1), 'caption': '合成示意素材'} for i, ref in enumerate(all_images)]}
        evaluation = record('rws_evaluation_import', 'EV1', title='合成 QA · 多格式结果与宽内容', codeRef=evaluation_code, protocolRef=protocol, inputRefs=all_images, results=[table, series, images], status='completed', experimentRef=experiments[-1], notes=QA)
        analysis = record('rws_analysis_save', 'AN1', title='合成 QA · 多实验来源与长分析内容', experimentRefs=experiments, inputRefs=[comparison, evaluation], observations=('图集、宽表和曲线是人为构造的浏览器测试材料。' * 12), interpretation=QA, limitations='不得把合成数值解释为方法效果；没有真实推理、评估或训练。', codeRef=analysis_code)
        paragraphs = []
        for i in range(1, 13):
            paragraphs.append('## 合成 QA 检查章节 %02d\n\n' % i + (QA + ' 这里保留较长说明，以检查报告滚动、固定来源和返回操作。') * 5 + '\n\n- 检查来源引用。\n- 检查长内容不遮挡按钮。\n- 保持人工判断与合成数据的区别。')
        markdown = '# 合成 QA 长报告\n\n' + QA + '\n\n' + '\n\n'.join(paragraphs) + '\n\n```text\n' + 'SyntheticQAUnbrokenLineForHorizontalOverflow' * 16 + '\n```\n'
        report = record('rws_report_create_revision', 'REPORT-LONG', title='合成 QA · 长报告与完整固定来源', inputRefs=[comparison], analysisRefs=[analysis], evaluationRefs=[evaluation], researchRefs=[research[-1]], markdown=markdown)
        write('rws_overview_propose', DENSE, baseRevision=2, fields={'consensus': QA + ' 已准备密集画布、600 图、宽表、长曲线和长报告，请在浏览器检查后人工决定是否接受。'}, reason='待审阅的合成 QA 建议，不自动修改基础。', sourceRefs=[analysis])

        timings = {}
        for label, read in [
            ('projectList', lambda: store.call('rws_project_list', {})),
            ('denseSnapshot', lambda: store.snapshot(DENSE)),
            ('denseContext', lambda: store.call('rws_get_context', {'projectId': DENSE})),
            ('lastExperimentContext', lambda: store.call('rws_get_context', {'projectId': DENSE, 'experimentRef': experiments[-1]})),
        ]:
            samples = []
            for _ in range(3):
                tick = time.perf_counter()
                output = read()
                samples.append(round(time.perf_counter() - tick, 4))
            timings[label] = {'seconds': samples, 'jsonBytesUtf8': len(json.dumps(output, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))}
        snapshot = store.snapshot(DENSE)
        summary = {'database': str(destination), 'copiedReadOnlyBase': str(base) if base else None, 'projects': [p['id'] for p in snapshot['projects']], 'denseProjectId': DENSE, 'emptyProjectId': EMPTY, 'denseCounts': dict(sorted(Counter(e['ref']['type'] for e in snapshot['records']).items())), 'emptyRecordCount': len(store.snapshot(EMPTY)['records']), 'keyRefs': {'comparison': comparison, 'evaluation': evaluation, 'analysis': analysis, 'report': report, 'lastExperiment': experiments[-1]}, 'table': {'columns': 24, 'rows': 100}, 'seriesPoints': 1600, 'seedSeconds': round(time.perf_counter() - started, 3), 'reads': timings, 'notice': QA}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    finally:
        store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True, help='Fresh isolated output path; existing files are never overwritten.')
    parser.add_argument('--base', type=Path, default=None, help='Read-only fixture base copied via SQLite backup.')
    parser.add_argument('--without-base', action='store_true', help='Create only the two QA projects in a fresh database.')
    options = parser.parse_args()
    seed(options.db, None if options.without_base else options.base)
