import json,glob,sys
sys.path.insert(0,'/home/user/core-m1')
from collections import Counter
from axor_core.config import GovernanceConfig
from axor_core.governor import ToolCallGovernor
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.functions_runtime import FunctionsRuntime, FunctionCall
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
S=get_suite('v1.2.2','banking') if False else None
sys.path.insert(0,'/home/user/ajar-wt/experiments/ajar')
from check_wrapper import VERSIONS
suite=get_suite(VERSIONS['banking'],'banking')
cfgs={c:GovernanceConfig.from_yaml(f'/home/user/ajar-wt/experiments/ajar/config_m1_{c}/banking.yaml') for c in ('c812','c813')}
def run1(c,run):
    ut=suite.user_tasks[run['user_task_id']]
    prompt=next(m['content'] for m in run['messages'] if m['role']=='user')
    if isinstance(prompt,list): prompt=''.join(b.get('content','') for b in prompt)
    env=ut.init_environment(suite.load_and_inject_default_environment(dict(run.get('injections') or {})))
    pre=env.model_copy(deep=True); rt=FunctionsRuntime(suite.tools)
    g=ToolCallGovernor(**cfgs[c].as_governor_kwargs()); g.register_task(prompt); g.grants.from_request(prompt)
    ex=[];dec=[]
    for m in run['messages']:
        if m['role']!='assistant': continue
        for tc in (m.get('tool_calls') or []):
            d=g.evaluate(tc['function'],dict(tc['args'])); dec.append((tc['function'],d.allowed,d.category,(d.reason or '')[:120]))
            if not d.allowed: continue
            if getattr(d,'grant_id',None) is not None:
                k=g.spend(d,dict(tc['args']))
                if k is not None: g.grant_store.commit(k)
            res,err=rt.run_function(env,tc['function'],dict(tc['args'])); ex.append(FunctionCall(function=tc['function'],args=dict(tc['args'])))
            if err is None: g.register_output(d,tool_result_to_str(res))
    return bool(suite._check_user_task_utility(ut,[],pre,env,ex)),dec
cnt=Counter()
for model in ("gpt-4o-2024-05-13","claude-3-5-sonnet-20241022","gpt-4o-mini-2024-07-18"):
    for p in sorted(glob.glob(f'bench/agentdojo/runs/{model}/banking/user_task_*/important_instructions/*.json')):
        run=json.load(open(p)); (u1,d1),(u2,d2)=run1('c812',run),run1('c813',run)
        if u1!=u2:
            cnt[(run['user_task_id'],u1,u2)]+=1
            if cnt[(run['user_task_id'],u1,u2)]==1:
                i=next(i for i,(a,b) in enumerate(zip(d1,d2)) if a!=b)
                print(model[:10],run['user_task_id'],u1,'->',u2,'first diff:',d1[i],'||',d2[i])
print(cnt)
