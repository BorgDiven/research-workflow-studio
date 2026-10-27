"""Additional synthetic records exercising the version 0.3 evidence workflow."""


def add_fixture(write, rec, refs, project):
    dataset = rec('rws_dataset_register', project, 'DS-DEMO', title='Synthetic shapes / two cases', version='1', sampleIds=['S1', 'S2'], description='Illustration-only fixture; no image model or quality evaluation.')
    spec = rec('rws_spec_save', project, 'SPEC-IMAGE', title='图像方法 · 输入输出规则示例', schemaVersion=1, kind='inference', status='ready', purpose='输入案例和配置，输出最终图或带步骤的诊断图。此规则是教学示例，尚未登记满足它的真实实现。', inputs=[{'name':'cases','kind':'dataset','required':True,'multiple':False}], outputs=[{'name':'final','kind':'image','semantic':'final-image','multiple':True},{'name':'probe','kind':'image','semantic':'clean-estimate','multiple':True,'required':False}], configSchema={'type':'object','properties':{'cfg':{'type':'number'},'steps':{'type':'integer','minimum':1},'strength':{'type':'number','minimum':0,'maximum':1}},'additionalProperties':False}, dependencies=[], acceptanceChecks=[{'id':'two-cases','description':'同一实现接受两个不同案例，产出保留各自身份。'},{'id':'semantics','description':'最终图与中间预测显式区分。'}], capabilities=['final-image','clean-estimate'])
    code = rec('rws_code_register', project, 'C2', title='自适应规则（示意登记）', kind='inference', version='v3', source={'description':'仅用于可视化结构的模拟实现；没有执行，也不声称通过代码块验收。'}, parentRefs=[refs[(project,'C1')]])
    exp = refs[(project,'E2')]
    all_outputs=[]
    for index, (code_ref, label) in enumerate([(refs[(project,'C0')],'原始规则'),(refs[(project,'C1')],'固定规则'),(code,'自适应规则')]):
        run=rec('rws_run_register', project, 'DEMO-SOURCE-%d'%index, title=label+' · 合成来源记录', kind='inference', codeRef=code_ref, config={'cfg':4,'steps':20,'strength':0.2}, status='completed', inputRefs=[dataset], experimentRef=exp, sampleSelection={'datasetRef':dataset,'sampleIds':['S1','S2']}, purpose='演示案例对齐与产物类型筛选，没有实际模型执行。')
        for sample in ('S1','S2'):
            if index==2 and sample=='S2':
                continue  # Explicitly absent cell, not a fabricated output.
            base=dict(kind='image',producerRef=run,sampleId=sample,datasetRef=dataset,taskKey='recolor-shape',config={'cfg':4,'steps':20,'strength':0.2},inputRefs=[dataset],availability='available')
            image=rec('rws_artifact_register',project,'DEMO-%s-%d'%(sample,index),title='%s / %s · 合成最终图'%(sample,label),semantic='final-image',uri='/assets/synthetic-%s-%d.svg'%(sample.lower(),index),**base)
            all_outputs.append(image)
            for step in (5,10):
                all_outputs.append(rec('rws_artifact_register',project,'DEMO-%s-%d-STEP-%d'%(sample,index,step),title='%s / %s / 第 %d 步 · 合成诊断'%(sample,label,step),semantic='clean-estimate',observation={'step':step},uri='/assets/synthetic-%s-%d.svg'%(sample.lower(),index),**base))
    write('rws_usage_save',project,id='U-DEMO-V3',experimentRef=exp,artifactRefs=all_outputs,role='observation',label='合成演示 · 两个案例、三种规则及步骤诊断')
    cmp=rec('rws_comparison_save',project,'CMP-V3',title='同条件 · 两案例与三种规则',inputRefs=[a for a in all_outputs if '-STEP-' not in a['id']],fixedConditions={'cfg':4,'steps':20,'strength':0.2},varyingConditions=['implementation'],viewSpec={'mode':'multi','sampleIds':['S1','S2'],'semantics':['final-image'],'axis':'implementation','filters':{},'repeats':'all'})
    return {'spec':spec,'comparison':cmp,'dataset':dataset}
