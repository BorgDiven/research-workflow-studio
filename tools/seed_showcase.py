#!/usr/bin/env python3
"""Create an isolated, fictional UI showcase; never runs a research model.

Run with a new database, for example:
    python3 tools/seed_showcase.py --db .local/showcase.sqlite3

Only this showcase's demo projects are accepted on replay. All writes use Store
operations with the same request IDs and expected revisions as the initial seed.
Human-only decisions below are explicitly simulated for these fictional projects.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rws.core import Store


MAIN_PROJECT = 'showcase-shapes'
PROJECTS = (MAIN_PROJECT, 'showcase-signals', 'showcase-materials')
SAMPLES = ('circle', 'triangle', 'hexagon')
ASSET_PREFIX = '/assets/showcase/'
NOTICE = '全部内容为虚构演示；图形与数值由脚本编排，没有训练、推理或质量评测执行。'


def shape_svg(sample, method):
    """Draw vector artwork directly. It is not a model result or evaluated mask."""
    shapes = {
        'circle': '<circle cx="320" cy="200" r="90"/>',
        'triangle': '<path d="M320 102L424 282H216Z"/>',
        'hexagon': '<path d="M272 112H368L416 196L368 280H272L224 196Z"/>',
    }
    names = {'input': 'INPUT SHAPE', 'base': 'THRESHOLD VIEW',
             'local': 'LOCAL CONTRAST VIEW', 'multi': 'MULTISCALE VIEW',
             'probe': 'BOUNDARY PROBE'}
    colors = {'input': '#74849b', 'base': '#4476c5', 'local': '#168b83',
              'multi': '#9065c5', 'probe': '#d18c38'}
    color = colors[method]
    shift = {'input': 0, 'base': 9, 'local': 4, 'multi': 0, 'probe': 0}[method]
    marks = ''.join('<circle cx="%d" cy="%d" r="%s" fill="#9aabc2" opacity=".35"/>'
                    % (92 + i * 37 % 460, 95 + i * 53 % 210, 1.5 + i % 3)
                    for i in range(26))
    outline = ('<g fill="none" stroke="%s" stroke-width="3" stroke-dasharray="8 5" '
               'transform="translate(%d -4)">%s</g>' % (color, shift, shapes[sample]))
    probe = ('<path d="M180 200H460M320 80V312" stroke="#d18c38" opacity=".65" '
             'stroke-width="2" stroke-dasharray="4 5"/>') if method == 'probe' else ''
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420">
<defs><linearGradient id="paper" x2="1" y2="1"><stop stop-color="#f5f8fc"/><stop offset="1" stop-color="#e4edf7"/></linearGradient></defs>
<rect width="640" height="420" rx="20" fill="url(#paper)"/>
<rect x="24" y="22" width="592" height="44" rx="11" fill="white" opacity=".8"/>
<text x="42" y="50" font-family="system-ui,sans-serif" font-size="16" font-weight="600" fill="#536882">%s · %s</text>
<path d="M80 330H560" stroke="#d2ddec"/><g>%s</g>
<g fill="%s" fill-opacity=".16" stroke="%s" stroke-width="2">%s</g>%s%s
<rect x="24" y="354" width="592" height="42" rx="10" fill="#fff" opacity=".85"/>
<text x="42" y="380" font-family="system-ui,sans-serif" font-size="12" letter-spacing=".7" fill="#667892">SYNTHETIC ILLUSTRATION · NO MODEL EXECUTION</text></svg>''' % (
        sample.upper(), names[method], marks, color, color, shapes[sample], outline, probe)


def build_assets(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for sample in SAMPLES:
        for method in ('input', 'base', 'local', 'multi', 'probe'):
            if sample == 'hexagon' and method == 'multi':
                continue  # Deliberately absent comparison cell.
            (directory / (sample + '-' + method + '.svg')).write_text(
                shape_svg(sample, method), encoding='utf-8')
    examples = {
        'inference': '''# ILLUSTRATIVE PSEUDOCODE — NOT AN EXECUTABLE OR VERIFIED IMPLEMENTATION
# The case and ordinary settings are inputs, never part of the method identity.
def segment_shapes(cases, config, rule):
    for case in cases:
        yield illustrate(case, rule=rule, settings=config)
# The showcase registers hand-constructed SVG illustrations, not these outputs.
''',
        'evaluation': '''# ILLUSTRATIVE PSEUDOCODE — NO METRICS WERE COMPUTED
def summarize_pairs(predictions, references, protocol):
    match_exact_case_and_task(predictions, references)
    return table_for_each_case(protocol), explicitly_missing_cases()
# Displayed IoU and boundary errors are human-chosen demonstration values.
''',
        'analysis': '''# ILLUSTRATIVE PSEUDOCODE — NO SCIENTIFIC ANALYSIS WAS EXECUTED
def compare_evidence(frozen_comparison, metric_table):
    return dict(observations=describe_selected_items(),
                interpretation=state_conditional_reading(),
                limitations=list_missing_inputs_and_demo_limits())
''',
        'report': '''# ILLUSTRATIVE PSEUDOCODE — THE REPORT IS AN AUTHORED DEMO DOCUMENT
def render_report(exact_evidence_refs, analysis_ref, foundation_version):
    return document_with_fixed_inputs(exact_evidence_refs, analysis_ref,
                                      foundation_version)
# Reopening the report must not silently include later evidence.
''',
    }
    for kind, source in examples.items():
        (directory / (kind + '-example.txt')).write_text(source, encoding='utf-8')


def seed(db, assets_dir=None, *, preview_models=False):
    store = Store(db)
    try:
        known = store.call('rws_project_list', {})['result']
        if any(p['id'] not in PROJECTS or not p.get('demo') for p in known):
            raise ValueError('Showcase seed requires an empty database or only its own demo projects. No records were changed.')
        preview_name = '轮廓模型研究 · 设计预览'
        if any(p['id'] == MAIN_PROJECT and (p['name'] == preview_name) != preview_models for p in known):
            raise ValueError('Use a separate database for the model preview and the public showcase. No records were changed.')
        build_assets(assets_dir or Path(__file__).resolve().parents[1] / 'web/assets/showcase')
        revisions, refs = {}, {}
        sequence = 0

        def write(op, pid=None, _actor='model', **args):
            nonlocal sequence
            sequence += 1
            args['requestId'] = ('model-preview-v1-' if preview_models else 'showcase-v1-') + '%04d' % sequence
            if pid:
                args.update(projectId=pid, expectedRevision=revisions[pid])
            response = store.call(op, args, actor=_actor)
            revisions[response['projectId']] = response['revision']
            return response['result']

        def rec(op, pid, rid, **fields):
            if preview_models and pid == MAIN_PROJECT and op in ('rws_run_register', 'rws_artifact_register'):
                fields['config'] = dict(fields.get('config', {}), base_model='轮廓模型 A', model_version='a1')
            result = write(op, pid, record=dict(id=rid, **fields))
            refs[(pid, rid)] = result['ref']
            return result['ref']

        def usage(pid, eid, key, artifacts, role, label):
            return write('rws_usage_save', pid, id=key, experimentRef=eid,
                         artifactRefs=artifacts, role=role, label=label)

        def foundation(pid, fields, stages):
            proposal = write('rws_overview_propose', pid, baseRevision=1, fields=fields,
                             reason='虚构演示项目的预设基础；模拟人工确认，仅作用于独立演示数据库。')
            write('rws_overview_apply', pid, _actor='human', proposalRef=proposal['ref'], baseRevision=1)
            write('rws_project_stages_set', pid, _actor='human', activeStages=stages)

        for pid, name, goal in [
            (MAIN_PROJECT, preview_name if preview_models else '合成图形稳健性研究 · 演示', '探索噪声、局部对比与尺度对几何轮廓示意结果的影响，展示从观察到对照、消融和报告的半自动流程。'),
            ('showcase-signals', '周期信号诊断 · 演示', '用人为编排的曲线展示观察、异常定位与证据整理。'),
            ('showcase-materials', '材料复用工作室 · 演示', '用虚构案例演示项目准备与材料复用，不包含真实研究记录。'),
        ]:
            write('rws_project_create', projectId=pid, name=name, goal=goal,
                  domain='独立虚构演示', demo=True)

        pid = MAIN_PROJECT
        main_foundation = {
            'goal': '如何在噪声变化下保留几何图形轮廓？先观察边界，再比较规则，最后检查各模块贡献。',
            'foundations': '圆、三角形、六边形三类 SVG；阈值规则为基线。图形从零绘制，不依赖真实数据集或基础模型。',
            'approach': '基线观察 → 边界探针与局部对比两条探索 → 同条件比较 → 模块消融。发现可以产生下一轮问题，结论仍由人确认。',
            'resources': '固定三个样本与示意噪声等级；对比阈值、局部对比、多尺度三种规则。统一指标只用于演示表格。',
            'consensus': '已确认的是演示材料的归属与覆盖范围；没有真实方法优劣结论。六边形的多尺度结果故意留空。',
        }
        if preview_models:
            main_foundation.update({
                'foundations': '起点：轮廓模型 A / a1\n从原始流程的边界变化提出研究问题。\n\n扩展：轮廓模型 B / b1\n在正式实验中引入，通用性待验证。',
                'approach': '原始流程观察 → 局部对比 / 边界探针 → 同条件比较 → 通用性与消融。\n研究问题和观察推动假设演进。',
                'resources': '圆、三角形、六边形三类合成 SVG；固定样本与示意噪声等级，比较阈值、局部对比、多尺度规则。所有图形和数值均人为编排，没有执行任何模型。',
                'consensus': '当前材料只演示模型 A 的证据组织，不代表模型 A 已复现或方法有效。模型 B 尚无产物；六边形的多尺度示意单元仍缺失。',
            })
        foundation(pid, main_foundation, ['formal'])

        research_defs = [
            ('H1', '噪声下的轮廓发生了什么？', '观察三类图形的边界变化，为后续对照建立共同起点。', 'exploration', 'idea', [], None),
            ('H2', '局部对比能稳定边界吗？', '在相同输入和噪声条件下比较阈值与局部对比规则。', 'hypothesis', 'idea', ['H1'], '局部对比可能减少弱边界的遗漏；需通过真实实验验证。'),
            ('H3', '误差集中在哪些位置？', '用边界探针观察角点与平滑轮廓，不预设方法改进。', 'exploration', 'idea', ['H1'], None),
            ('H4', '汇合两条观察路线', '把规则比较和位置探针连起来，明确下一轮测什么。', 'exploration', 'idea', ['H2', 'H3'], None),
            ('H5', '三种规则的同条件比较', '固定案例、输入与显示条件，对齐已有材料并显式标记缺失。', 'hypothesis', 'formal', ['H4'], '多尺度规则可能在不同轮廓上表现不同；演示数值不能验证此假设。'),
            ('H6', '噪声强度的敏感性', '基于同条件比较，追踪示意曲线的变化范围。', 'exploration', 'formal', ['H5'], None),
            ('H7', '移除归一化会怎样？', '仅关闭归一化模块，保留其余设计以规划一个明确对照。', 'hypothesis', 'ablation', ['H5'], '归一化模块可能影响对噪声等级的敏感性。'),
            ('H8', '只保留单尺度会怎样？', '沿已有对照检查尺度模块，区分模块贡献与样本差异。', 'hypothesis', 'ablation', ['H7'], '尺度模块的贡献可能取决于轮廓类型。'),
            ('H9', '哪些观察值得继续验证？', '结合敏感性与消融计划，整理下一轮研究问题和证据缺口。', 'exploration', 'ablation', ['H6', 'H8'], None),
        ]
        for rid, title, question, kind, stage, parents, hypothesis in research_defs:
            if preview_models and rid == 'H1':
                question = '从模型 A / a1 的原始阈值流程观察三类轮廓在噪声下的变化，为局部对比和探针探索提出问题；当前材料仅是合成示意。'
            if preview_models and rid == 'H5':
                title = '多尺度规则能跨条件保持稳健吗？'
                question = '依据前两条探索，先在模型 A 上比较三种规则，再计划在模型 B 上检验同一假设；两种模型各用自己的原始对照。'
                hypothesis = '多尺度规则可能在不同轮廓与模型条件下减少边界变化；需要各条件的对照证据，当前虚构材料不能验证该假设。'
            fields = dict(title=title, question=question, kind=kind, stage=stage,
                          parentRefs=[refs[(pid, parent)] for parent in parents])
            if hypothesis:
                fields['hypothesis'] = hypothesis
            rec('rws_research_save', pid, rid, **fields)

        protocol = rec('rws_protocol_register', pid, 'P-SHAPES', title='统一轮廓指标 · 演示约定', version='demo-v1',
                       inputKind='artifact', metrics=[
                           {'name': 'iou', 'label': 'IoU（演示）', 'unit': '', 'direction': 'higher', 'granularity': 'sample'},
                           {'name': 'boundary_error', 'label': '边界偏差（演示）', 'unit': 'px', 'direction': 'lower', 'granularity': 'sample'}],
                       preprocessing={'canvas': '640x420', 'alignment': 'exact sample and task'},
                       aggregation='各样本单独展示；不补齐缺失单元。', missingPolicy='显式留空并记录覆盖范围。',
                       description='指标名称用于展示统一评估结构；所有值手工设定，未计算。')
        def experiments():
            for index, (rid, title, *_rest) in enumerate(research_defs, 1):
                config = {'noise_level': 0.25, 'resolution': 256, 'threshold': 0.4}
                if preview_models:
                    config.update(base_model='轮廓模型 A', model_version='a1')
                    if rid == 'H5':
                        title = '模型 A · 三种规则的同条件比较'
                        config.update(comparison_code_refs=[refs[(pid, cid)] for cid in ('C0', 'C1', 'C2')],
                                      comparison_role='模型 A 内的方法比较',
                                      reference_source='精确引用模型 A 的合成示意材料；全部为布局演示，没有执行模型。')
                rec('rws_experiment_save', pid, 'E%d' % index, title=title + ' · 演示实验',
                    researchRef=refs[(pid, rid)], protocolRef=protocol, config=config,
                    status='completed' if index <= 6 else 'planned')
        if not preview_models:
            experiments()
        dataset = rec('rws_dataset_register', pid, 'DS-SHAPES', title='三类几何图形 · 合成演示集',
                      version='demo-v1', sampleIds=list(SAMPLES), split='illustration', description=NOTICE)

        # Method contracts are shown as drafts. No invented commit or check claim
        # is used to represent the illustrative code as a registered implementation.
        for kind, title, output_kind in [('inference', '轮廓规则的输入输出', 'image'),
                                        ('evaluation', '统一指标的输入输出', 'table'),
                                        ('analysis', '证据分析的输入输出', 'analysis'),
                                        ('report', '固定报告的输入输出', 'report')]:
            rec('rws_spec_save', pid, 'SPEC-' + kind.upper(), title=title + ' · 示例草案',
                schemaVersion=1, kind=kind, status='draft', purpose='以独立案例和配置组织可复用的 ' + kind + ' 模块；当前仅示意，没有已验证实现。',
                inputs=[{'name': 'inputs', 'kind': 'artifact', 'multiple': True}],
                outputs=[{'name': 'outputs', 'kind': output_kind, 'multiple': True}],
                configSchema={'type': 'object', 'additionalProperties': True}, dependencies=[],
                acceptanceChecks=[{'id': 'case-agnostic', 'description': '后续实际实现应接受外部案例，不将单个案例写入方法身份。'}],
                capabilities=['illustration-only'])

        code_defs = [
            ('C0', '阈值轮廓规则', 'inference', 'v1', [], '以统一阈值定义轮廓基线；案例和配置作为外部输入。'),
            ('C1', '局部对比规则', 'inference', 'v2', ['C0'], '在基线结构上增加局部对比步骤，保持同一案例接口。'),
            ('C2', '多尺度轮廓规则', 'inference', 'v3', ['C1'], '沿局部规则增加尺度汇合；用于演示方法继承。'),
            ('C-PROBE', '边界位置探针', 'inference', 'v1', ['C0'], '只观察轮廓位置与噪声响应，不修改其他方法的结果。'),
            ('C-EVAL', '统一轮廓评估器', 'evaluation', 'v1', [], '多种方法共用同一指标约定，按案例输出表格并保留缺失。'),
            ('C-ANALYSIS', '覆盖与差异分析器', 'analysis', 'v1', [], '读取固定对比与指标，分别记录观察、解释和限制。'),
            ('C-REPORT', '固定证据报告模板', 'report', 'v1', [], '按选定证据、分析和项目基础生成固定阅读快照。'),
        ]
        for cid, title, kind, version, parents, description in code_defs:
            rec('rws_code_register', pid, cid, title=title + ' · 演示', kind=kind, version=version,
                description=description + ' 伪代码示意，不代表实际执行或通过验收。',
                source={'uri': ASSET_PREFIX + kind + '-example.txt', 'description': NOTICE,
                        'format': 'illustrative-pseudocode', 'execution': 'none'},
                parentRefs=[refs[(pid, parent)] for parent in parents])

        # Declare purpose before any run is registered. A draft contract can
        # already serve a research question; that does not create evidence.
        purpose_links = {
            'H1': [('C0', 'control')],
            'H2': [('C0', 'control'), ('C1', 'implementation')],
            'H3': [('C-PROBE', 'diagnostic')],
            'H4': [('SPEC-ANALYSIS', 'diagnostic')],
            'H5': [('C0', 'control'), ('C1', 'implementation'), ('C2', 'implementation')],
            'H7': [('SPEC-INFERENCE', 'implementation')],
        }
        for rid, targets in purpose_links.items():
            rec('rws_research_save', pid, rid, implementationLinks=[
                {'targetRef': refs[(pid, target)], 'role': role,
                 'note': '虚构研究用途；是否已有材料请查看实际使用与引用。'}
                for target, role in targets])

        base_config = {'noise_level': 0.25, 'resolution': 256, 'threshold': 0.4}
        if preview_models:
            experiments()
            base_config.update(base_model='轮廓模型 A', model_version='a1')
        outputs, methods = {}, [('C0', 'base', '阈值规则'), ('C1', 'local', '局部对比'), ('C2', 'multi', '多尺度')]
        for cid, method, label in methods:
            run = rec('rws_run_register', pid, 'R-' + method.upper(), title=label + ' · 虚构来源记录',
                      kind='inference', codeRef=refs[(pid, cid)], config=base_config,
                      status='partial' if method == 'multi' else 'completed', inputRefs=[dataset],
                      experimentRef=refs[(pid, 'E5')], sampleSelection={'datasetRef': dataset, 'sampleIds': list(SAMPLES)},
                      purpose='演示同一方法覆盖多个案例与跨版本对比；没有模型执行。',
                      notes='此运行及输出身份均为虚构 UI 示例。多尺度六边形单元故意缺失。')
            for sample in SAMPLES:
                if sample == 'hexagon' and method == 'multi':
                    continue
                outputs[(sample, method)] = rec('rws_artifact_register', pid, 'A-' + sample.upper() + '-' + method.upper(),
                    title=sample + ' / ' + label + ' · 合成示意图', kind='image', semantic='final-image',
                    producerRef=run, sampleId=sample, datasetRef=dataset, taskKey='shape-outline',
                    config=base_config, inputRefs=[dataset], uri=ASSET_PREFIX + sample + '-' + method + '.svg',
                    availability='available', description=NOTICE)
        all_images = list(outputs.values())
        usage(pid, refs[(pid, 'E5')], 'U-COMPARE', all_images, 'observation', '演示同条件比较：三案例与三方法，保留缺失单元。')
        usage(pid, refs[(pid, 'E1')], 'U-BASELINE', [outputs[(s, 'base')] for s in SAMPLES], 'baseline', '精确引用基线示意图；来源不移动。')
        usage(pid, refs[(pid, 'E2')], 'U-LOCAL', [a for (s, m), a in outputs.items() if m in ('base', 'local')], 'comparison', '复用基线与局部对比的同一份产物。')
        usage(pid, refs[(pid, 'E4')], 'U-MERGE', all_images, 'reference', '汇合探索时引用已登记产物，无需重复生成。')

        probe_run = rec('rws_run_register', pid, 'R-PROBE', title='边界探针 · 虚构观察记录',
                        kind='inference', codeRef=refs[(pid, 'C-PROBE')], config=base_config,
                        status='completed', inputRefs=[dataset], experimentRef=refs[(pid, 'E3')],
                        sampleSelection={'datasetRef': dataset, 'sampleIds': list(SAMPLES)}, purpose=NOTICE)
        probes = [rec('rws_artifact_register', pid, 'A-' + s.upper() + '-PROBE', title=s + ' / 边界探针 · 合成示意图',
                      kind='image', semantic='diagnostic-image', producerRef=probe_run, sampleId=s, datasetRef=dataset,
                      taskKey='shape-outline', config=base_config, inputRefs=[dataset], observation={'step': 12},
                      uri=ASSET_PREFIX + s + '-probe.svg', availability='available', description=NOTICE) for s in SAMPLES]
        curves = []
        for index, label in enumerate(('阈值规则', '局部对比', '多尺度')):
            curves.append(rec('rws_artifact_register', pid, 'A-CURVE-%d' % index,
                title=label + ' / 噪声响应 · 合成曲线', kind='series', semantic='diagnostic-curve', producerRef=probe_run,
                config={'illustrated_method': label}, inputRefs=[dataset], availability='available', description=NOTICE,
                content={'kind': 'series', 'name': 'boundary_response', 'label': label + ' · 人为编排的响应曲线',
                         'xAxis': {'label': '示意噪声强度', 'unit': ''}, 'yAxis': {'label': '示意边界偏差', 'unit': 'px'},
                         'points': [{'x': x, 'y': y} for x, y in zip([0, .1, .2, .3, .4],
                                    [[1.2, 2.5, 4.8, 7.7, 10.1], [.9, 1.7, 2.9, 4.5, 6.9], [1.1, 1.5, 2.3, 3.9, 6.4]][index])]}))
        usage(pid, refs[(pid, 'E3')], 'U-PROBES', probes, 'observation', '边界位置的合成探针材料。')
        usage(pid, refs[(pid, 'E6')], 'U-CURVES', curves, 'observation', '三条人为编排曲线；不代表运行质量。')

        comparison = rec('rws_comparison_save', pid, 'CMP-SHAPES', title='同条件 · 三案例 × 三方法',
                         inputRefs=all_images, fixedConditions=base_config, varyingConditions=['implementation'],
                         description='8 个合成单元；六边形的多尺度单元未准备，不以其他图替代。' + NOTICE,
                         viewSpec={'mode': 'multi', 'sampleIds': list(SAMPLES), 'semantics': ['final-image'],
                                   'axis': 'implementation', 'filters': {}, 'repeats': 'all'})
        rec('rws_comparison_save', pid, 'CMP-PROBES', title='边界探针 · 三类轮廓', inputRefs=probes,
            fixedConditions=base_config, varyingConditions=['sample'], description=NOTICE,
            viewSpec={'mode': 'multi', 'sampleIds': list(SAMPLES), 'semantics': ['diagnostic-image'],
                      'axis': 'implementation', 'filters': {}, 'repeats': 'all'})

        evaluations = []
        metric_rows = []
        values = {'base': [(0.71, 5.2), (0.68, 6.1), (0.74, 4.8)],
                  'local': [(0.82, 3.3), (0.79, 4.0), (0.83, 3.0)],
                  'multi': [(0.86, 2.7), (0.84, 3.1)]}
        for cid, method, label in methods:
            refs_for_method = [outputs[(s, method)] for s in SAMPLES if (s, method) in outputs]
            metric_results = []
            rows = []
            for sample, (iou, error) in zip(SAMPLES, values[method]):
                metric_results += [
                    {'kind': 'metric', 'name': 'iou', 'label': 'IoU · 演示值', 'value': iou, 'unit': '', 'direction': 'higher', 'sampleId': sample, 'status': 'completed'},
                    {'kind': 'metric', 'name': 'boundary_error', 'label': '边界偏差 · 演示值', 'value': error, 'unit': 'px', 'direction': 'lower', 'sampleId': sample, 'status': 'completed'}]
                row = {'sample': sample, 'method': label, 'iou': iou, 'boundary_error': error, 'note': '人为设定，未计算'}
                rows.append(row); metric_rows.append(row)
            metric_results.append({'kind': 'table', 'label': label + ' · 演示指标表',
                'columns': [{'key': 'sample', 'label': '案例', 'type': 'string'}, {'key': 'method', 'label': '方法', 'type': 'string'},
                            {'key': 'iou', 'label': 'IoU（演示）', 'type': 'number'}, {'key': 'boundary_error', 'label': '边界偏差（演示）', 'type': 'number', 'unit': 'px'},
                            {'key': 'note', 'label': '说明', 'type': 'string'}], 'rows': rows})
            evaluations.append(rec('rws_evaluation_import', pid, 'EV-' + method.upper(), title=label + ' · 演示指标',
                protocolRef=protocol, codeRef=refs[(pid, 'C-EVAL')], inputRefs=refs_for_method, results=metric_results,
                status='completed', experimentRef=refs[(pid, 'E5')], datasetRef=dataset,
                notes='仅针对已准备的合成单元登记人为设定值；不意味着方法已实际运行。'))
        metric_rows.append({'sample': 'hexagon', 'method': '多尺度', 'iou': None, 'boundary_error': None, 'note': '未准备对应合成图，不补值'})
        table_run = rec('rws_run_register', pid, 'R-EVAL-TABLE', title='指标总表 · 虚构整理记录',
                        kind='evaluation', codeRef=refs[(pid, 'C-EVAL')], config={'synthetic': True},
                        status='completed', inputRefs=all_images, experimentRef=refs[(pid, 'E5')],
                        purpose='将人为设定的展示数值编排为表格；未计算质量指标。', notes=NOTICE)
        table = rec('rws_artifact_register', pid, 'A-METRIC-TABLE', title='三方法指标总表 · 人为设定', kind='table',
                    semantic='metric-table', producerRef=table_run, config={'synthetic': True},
                    inputRefs=all_images, availability='available', description=NOTICE,
                    content={'kind': 'table', 'label': '演示数值与缺失单元', 'columns': [
                        {'key': 'sample', 'label': '案例', 'type': 'string'}, {'key': 'method', 'label': '方法', 'type': 'string'},
                        {'key': 'iou', 'label': 'IoU · 演示', 'type': 'number'}, {'key': 'boundary_error', 'label': '偏差 · 演示', 'type': 'number', 'unit': 'px'},
                        {'key': 'note', 'label': '边界说明', 'type': 'string'}], 'rows': metric_rows})
        usage(pid, refs[(pid, 'E5')], 'U-METRIC-TABLE', [table], 'evaluation', '统一展示演示数值与缺失单元。')
        analysis = rec('rws_analysis_save', pid, 'AN-COVERAGE', title='轮廓差异与证据边界 · 演示分析',
                       experimentRefs=[refs[(pid, 'E5')], refs[(pid, 'E6')]], inputRefs=all_images + evaluations + curves + [table],
                       codeRef=refs[(pid, 'C-ANALYSIS')], comparisonRefs=[comparison],
                       observations=['已准备三类图形、三种规则的 8 个合成单元，保留了一个缺失单元。',
                                     '图像、曲线和指标可按同一案例定位；这些差异均为编排。'],
                       interpretation='本示例只展示如何组织对比和限定结论。不能据此认定某种规则更稳健。',
                       limitations=[NOTICE, '多尺度六边形缺失；示例不含模型运行或统计显著性检验。'],
                       scope={'sampleIds': list(SAMPLES), 'description': ('仅限模型 A 的合成示意材料；不包含模型 B，不能判断通用性。' if preview_models else '') + '仅限本演示中的 3×3 单元，8 格已准备。'},
                       coverage={'expected': 9, 'observed': 8, 'missingSampleIds': ['hexagon']})
        report = rec('rws_report_create_revision', pid, 'REPORT-SHAPES', title='轮廓研究阶段记录 · 演示报告',
                     inputRefs=all_images + curves + [table], analysisRefs=[analysis], evaluationRefs=evaluations,
                     researchRefs=[refs[(pid, 'H5')], refs[(pid, 'H6')]], comparisonRefs=[comparison],
                     generatorCodeRef=refs[(pid, 'C-REPORT')], markdown=('> 范围：仅展示轮廓模型 A / a1 的合成材料组织。轮廓模型 B / b1 尚无产物，未包含在本报告证据中；不能判断通用性。\n\n' if preview_models else '') + '''# 合成图形稳健性研究 · 演示报告

> 全部材料、研究问题、方法身份和数值均为虚构演示。没有执行模型或计算评测指标。

## 本阶段查看什么

在相同的三个几何案例与显示条件下，并列查看阈值、局部对比、多尺度规则的示意材料。

## 已准备的证据

三案例 × 三方法共九个预期单元，已有八个；多尺度六边形明确留空。统一指标表、三条噪声响应曲线和案例图像都固定在本快照中。

## 当前判断

材料可以正确对齐和复用；这是工作流演示的结果，不是对方法效果的判断。人为设定的指标不能支持科学结论。

## 下一步建议

若开展真实研究，应先由人确认实际方法与数据、评估约定和资源，再执行实验。归一化和尺度消融仍只是演示计划。
''')

        if preview_models:
            rec('rws_experiment_save', pid, 'E-MODEL-B', title='模型 B · 同一假设的适用性验证',
                researchRef=refs[(pid, 'H5')], protocolRef=protocol, status='planned',
                config={'base_model': '轮廓模型 B', 'model_version': 'b1',
                        'comparison_code_refs': [refs[(pid, cid)] for cid in ('C0', 'C2')],
                        'comparison_role': '在新模型上检验同一假设',
                        'reference_source': '需准备模型 B 自己的原始对照与多尺度结果；暂无产物，不使用模型 A 的图片替代。',
                        'noise_level': 0.25, 'resolution': 256, 'threshold': 0.4})

        signals = 'showcase-signals'
        foundation(signals, {'foundations': '从零编排的正弦样式数列，不采集设备或个人数据。',
                            'approach': '先看趋势，再定位异常区段；只演示记录流程。',
                            'resources': '一条合成曲线。', 'consensus': NOTICE}, ['idea'])
        hs = rec('rws_research_save', signals, 'H1', title='波动集中在哪些区段？', question='观察人为编排的周期信号，区分趋势与局部波动。',
                 kind='exploration', stage='idea', parentRefs=[])
        es = rec('rws_experiment_save', signals, 'E1', title='合成信号观察', researchRef=hs, config={}, status='completed')
        cs = rec('rws_code_register', signals, 'C1', title='信号记录示例', kind='inference', version='v1', parentRefs=[],
                 source={'description': NOTICE}, description='人工编排曲线的来源示意，没有设备采样或模型执行。')
        rs = rec('rws_run_register', signals, 'R1', title='虚构信号来源记录', codeRef=cs, config={}, inputRefs=[], status='completed', experimentRef=es, purpose=NOTICE)
        signal = rec('rws_artifact_register', signals, 'A1', title='周期变化 · 合成曲线', kind='series', producerRef=rs,
                     config={}, availability='available', description=NOTICE,
                     content={'kind': 'series', 'name': 'wave', 'label': '人为编排的周期变化',
                              'xAxis': {'label': '示意时刻', 'unit': ''}, 'yAxis': {'label': '示意幅值', 'unit': ''},
                              'points': [{'x': i, 'y': y} for i, y in enumerate([0, .6, 1, .7, 0, -.7, -1, -.6, 0, .7, 1.3, .6, 0])]})
        usage(signals, es, 'U1', [signal], 'observation', '合成曲线的观察引用。')
        foundation('showcase-materials', {'foundations': '尚未添加素材；保留空项目以演示项目准备。',
                                        'approach': '先确认目的与材料，再登记研究问题。',
                                        'resources': '无真实数据与外部服务。', 'consensus': NOTICE}, [])
        return {'projectId': MAIN_PROJECT, 'projects': list(PROJECTS), 'researchCount': 9,
                'comparison': comparison, 'report': report, 'notice': NOTICE,
                'selectedResearch': refs[(pid, 'H5')], 'selectedCode': refs[(pid, 'C1')],
                'revisions': revisions}
    finally:
        store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='An empty or previously seeded showcase-only database.')
    args = parser.parse_args()
    print(json.dumps(seed(args.db), ensure_ascii=False, indent=2))
