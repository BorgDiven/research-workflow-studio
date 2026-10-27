#!/usr/bin/env python3
"""Load explicit synthetic trial records through the same business service."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rws.core import Store


def seed(db):
    store = Store(db)
    known = {p['id'] for p in store.call('rws_project_list', {})['result']}
    ids = ('trial-image-edit', 'trial-training')
    if any(i in known for i in ids):
        raise SystemExit('Trial project already exists; use a fresh database or keep existing records. No overwrite performed.')
    refs = {}
    counter = 0

    def write(op, pid=None, **args):
        nonlocal counter
        counter += 1
        args['requestId'] = 'trial-seed-%03d' % counter
        if pid:
            args['projectId'] = pid
            args['expectedRevision'] = store.snapshot(pid)['revision']
        return store.call(op, args, actor=args.pop('_actor', 'model'))['result']

    def rec(op, pid, key, **fields):
        result = write(op, pid, record=dict(id=key, **fields))
        refs[(pid, key)] = result['ref']
        return result['ref']

    image, training = ids
    for pid, name, goal, domain in [
        (image, '图像编辑 · 共享材料试装', '验证研究关系、材料来源与固定报告的管理流程。全部记录与数值都是试装示例，不是科研结论。', '试装演示'),
        (training, '训练诊断 · 跨项目试装', '以合成训练曲线检查开放探索、跨项目引用和多种结果展示。没有运行训练。', '试装演示'),
    ]:
        write('rws_project_create', projectId=pid, name=name, goal=goal, domain=domain, demo=True)

    # Explicitly simulated human decisions inside synthetic demo projects only.
    foundation = write('rws_overview_propose', image, baseRevision=1, fields={
        'foundations':'合成形状数据：杯子与背包。原始规则作为对照；没有接入真实基础模型。',
        'approach':'先检查原始结果，再比较固定与自适应规则；用步骤诊断寻找变化位置。',
        'resources':'两份合成案例、三种示意实现与步骤 5 / 10 的诊断素材。',
        'consensus':'当前只验证工作流，方法效果尚无真实证据。'}, reason='合成演示的项目基础。')
    write('rws_overview_apply', image, _actor='human', proposalRef=foundation['ref'], baseRevision=1)
    write('rws_project_stages_set', image, _actor='human', activeStages=['idea'])

    h1 = rec('rws_research_save', image, 'H1', title='原始输出有哪些变化？', question='先登记基线材料，区分输入与实际输出。', kind='exploration', stage='idea', parentRefs=[])
    h2 = rec('rws_research_save', image, 'H2', title='固定回拉是否值得验证？', question='以同一批基线材料规划比较。', hypothesis='固定回拉可能减少背景变化。', kind='hypothesis', stage='idea', parentRefs=[h1])
    h3 = rec('rws_research_save', image, 'H3', title='变化集中在哪些步骤？', question='通过诊断材料寻找观察，不预设方法改进。', kind='exploration', stage='idea', parentRefs=[h1])
    h4 = rec('rws_research_save', image, 'H4', title='整合两条探索的证据', question='确认可比较材料与当前限制。', kind='exploration', stage='idea', parentRefs=[h2,h3])
    h5 = rec('rws_research_save', image, 'H5', title='扩大样本验证', question='等待人工确定样本和资源后再执行。', kind='exploration', stage='formal', parentRefs=[h4])
    e1 = rec('rws_experiment_save', image, 'E1', title='基线材料登记', researchRef=h1, config={'cfg':4,'steps':20,'seed':42}, status='completed')
    e2 = rec('rws_experiment_save', image, 'E2', title='回拉的演示比较', researchRef=h2, config={'cfg':4,'steps':20,'seed':42}, status='planned')
    rec('rws_experiment_save', image, 'E3', title='步骤诊断计划', researchRef=h3, config={}, status='planned')
    rec('rws_experiment_save', image, 'E4', title='证据整合', researchRef=h4, config={}, status='planned')
    rec('rws_experiment_save', image, 'E5', title='正式实验准备', researchRef=h5, config={}, status='planned')
    c0 = rec('rws_code_register', image, 'C0', title='原始图像编辑（示例登记）', kind='inference', version='v1', source={'description':'试装源代码记录，不执行程序'}, parentRefs=[])
    c1 = rec('rws_code_register', image, 'C1', title='固定回拉（示例登记）', kind='inference', version='v2', source={'description':'未连接真实源码'}, parentRefs=[c0])
    ec = rec('rws_code_register', image, 'EC1', title='统一评估记录器', kind='evaluation', version='v1', source={'description':'导入已有指标的示例'}, parentRefs=[])
    ac = rec('rws_code_register', image, 'AC1', title='配对分析说明', kind='analysis', version='v1', source={'description':'人工分析结构演示'}, parentRefs=[])
    rec('rws_code_register', image, 'RC1', title='报告文档模板', kind='report', version='v1', source={'description':'固定报告输入示例'}, parentRefs=[])
    r0 = rec('rws_run_register', image, 'R0', title='基线来源登记', kind='inference', codeRef=c0, config={'cfg':4,'steps':20,'seed':42}, status='completed', inputRefs=[], experimentRef=e1)
    r1 = rec('rws_run_register', image, 'R1', title='回拉来源登记', kind='inference', codeRef=c1, config={'cfg':4,'steps':20,'seed':42,'pullback':0.2}, status='completed', inputRefs=[], experimentRef=e2)
    a0 = rec('rws_artifact_register', image, 'A0', title='基线示意图（非模型产出）', kind='image', producerRef=r0, sampleId='S1', config={'cfg':4,'steps':20,'seed':42}, uri='/assets/demo-sheet.png', availability='available')
    a1 = rec('rws_artifact_register', image, 'A1', title='回拉示意图（同一演示素材）', kind='image', producerRef=r1, sampleId='S1', config={'cfg':4,'steps':20,'seed':42,'pullback':0.2}, uri='/assets/demo-sheet.png', availability='available')
    for eid, arts, role, label in [(e1,[a0],'baseline','本实验基线'),(e2,[a0],'control','复用基线运行的具体产物'),(e2,[a1],'treatment','回拉演示产物')]:
        write('rws_usage_save', image, experimentRef=eid, artifactRefs=arts, role=role, label=label)
    p1 = rec('rws_protocol_register', image, 'P1', title='演示图像指标约定', version='v1', inputKind='paired-image', metrics=[{'name':'psnr','label':'PSNR','unit':'dB','direction':'higher','granularity':'sample'}], preprocessing={'colorSpace':'RGB','dataRange':1,'resize':'none'}, aggregation='mean over successful samples', missingPolicy='report explicitly')
    ev = rec('rws_evaluation_import', image, 'EV1', title='已有指标导入示例（数值人为编排）', protocolRef=p1, codeRef=ec, inputRefs=[a0,a1], pairs=[{'sampleId':'S1','predictionRef':a1,'referenceRef':a0}], results=[{'kind':'metric','name':'psnr','label':'PSNR（演示）','value':28.5,'unit':'dB','direction':'higher','sampleId':'S1','status':'completed'},{'kind':'table','columns':[{'key':'sample','label':'样本','type':'string'},{'key':'value','label':'演示值','type':'number'}],'rows':[{'sample':'S1','value':28.5}]},{'kind':'image-set','items':[{'artifactRef':a0,'sampleId':'S1','caption':'基线示意素材'},{'artifactRef':a1,'sampleId':'S1','caption':'回拉示意素材'}]},{'kind':'attachment','uri':'demo-unresolved://trial-notes','mimeType':'text/plain','label':'不可用附件示例','availability':'unavailable'}], status='completed', experimentRef=e2)
    an = rec('rws_analysis_save', image, 'AN1', title='材料覆盖与限制', experimentRefs=[e1,e2], inputRefs=[a0,a1,ev], observations='两份示意材料已正确关联。', interpretation='当前只验证系统流程，不能判断回拉效果。', limitations='示意图和数值均为人为准备，没有运行图像模型。', codeRef=ac)
    rp = rec('rws_report_create_revision', image, 'RP1', title='试装固定报告', inputRefs=[a0,a1], analysisRefs=[an], evaluationRefs=[ev], researchRefs=[h2], markdown='# 试装记录\n\n这份报告验证材料引用和历史版本，不是科研结果。\n\n两份示意材料及其当时来源已固定。后续新材料不会自动加入。')
    ht = rec('rws_research_save', training, 'H1', title='训练曲线是否出现异常？', question='观察合成曲线并记录限制；无需先提出假设。', kind='exploration', stage='idea', parentRefs=[])
    et = rec('rws_experiment_save', training, 'E1', title='曲线与材料诊断', researchRef=ht, config={'axis':'optimizer_step'}, status='completed')
    ct = rec('rws_code_register', training, 'C0', title='训练日志记录器', kind='inference', version='v1', source={'description':'无真实训练，纯试装曲线'}, parentRefs=[])
    rt = rec('rws_run_register', training, 'R0', title='合成训练记录', kind='training', codeRef=ct, config={'demo':True}, status='completed', inputRefs=[], experimentRef=et)
    curve = {'kind':'series','name':'loss','label':'合成训练损失','xAxis':{'label':'optimizer_step','unit':'step'},'yAxis':{'label':'mean_squared_error','unit':'loss'},'points':[{'x':x,'y':y} for x,y in [(0,1.2),(10,.82),(20,.55),(30,.40),(40,.33)]]}
    at = rec('rws_artifact_register', training, 'A0', title='训练损失曲线（合成）', kind='series', producerRef=rt, config={'demo':True}, availability='available', content=curve)
    write('rws_usage_save', training, experimentRef=et, artifactRefs=[at], role='observation', label='本项目曲线')
    cross = write('rws_usage_save', training, experimentRef=et, artifactRefs=[a0], role='reference', label='跨项目引用：图像试装基线')
    rec('rws_comparison_save', training, 'CMP1', title='多种材料并列检查', inputRefs=[at,a0], fixedConditions={'purpose':'检查跨项目来源'}, varyingConditions=['material kind','source project'])
    ant = rec('rws_analysis_save', training, 'AN1', title='跨项目材料检查', experimentRefs=[et], inputRefs=[at,a0], observations='曲线与图像来自不同项目，界面应明确标注。', interpretation='只验证来源关联，不把图像和损失数值当作同一指标比较。', limitations='全部是试装材料。')
    rec('rws_report_create_revision', training, 'RP1', title='训练诊断试装报告', inputRefs=[at,a0], analysisRefs=[ant], evaluationRefs=[], researchRefs=[ht], markdown='开放探索可以直接记录曲线和观察，无需伪造评估协议。')
    write('rws_overview_propose', training, fields={'consensus':'试装已覆盖开放探索、合成曲线与跨项目来源；这不是科学结论。'}, reason='供人工在页面审阅确认的试装建议。', sourceRefs=[ant], baseRevision=1)
    from tools.seed_v3 import add_fixture
    v3 = add_fixture(write, rec, refs, image)
    result={'v3':v3,'projects':list(ids),'report':rp,'crossProjectUsage':cross,'records':'synthetic only; no model execution'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);seed(p.parse_args().db)
