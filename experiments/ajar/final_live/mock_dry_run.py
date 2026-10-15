import sys; sys.path.insert(0,"/home/user/core-m1")
import os,sys,json,ast,re
sys.path.insert(0,'/home/user/core-m1/examples/agentdojo')
os.environ.setdefault('AXOR_BENCH_SUITE','slack')
os.environ['AXOR_BENCH_GRANT_LEVELS']='L1+L4'; os.environ['AXOR_BENCH_L4_BUDGET']='5'
os.environ['AXOR_BENCH_L4_CONFIRM']='view'
import agentdojo_adapter as AD
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.functions_runtime import FunctionsRuntime, FunctionCall
from axor_core.config import GovernanceConfig
from axor_core.governor import ToolCallGovernor
CFG='/home/user/ajar-wt/experiments/ajar/config_m1_c9v5'
LIVE='/home/user/ajar-wt/experiments/ajar/results/live_final'
CALL=re.compile(r"(\w+)\((.*)\)$",re.S)
picks=[('B/pass1','slack','user_task_7'),('B/pass1','workspace','user_task_20'),('B/pass1','banking','user_task_0')]
for passdir,suite_name,ut_id in picks:
    p=os.path.join(LIVE,passdir,'traj',suite_name,ut_id+'.json')
    if not os.path.exists(p): print('MISSING',p); continue
    d=json.load(open(p)); suite=get_suite('v1',suite_name); ut=suite.user_tasks[ut_id]
    env=ut.init_environment(suite.load_and_inject_default_environment({}))
    rt=FunctionsRuntime(suite.tools)
    def mkgov():
        cfg=GovernanceConfig.from_yaml(os.path.join(CFG,f'{suite_name}.yaml'))
        return ToolCallGovernor(**cfg.as_governor_kwargs())
    ex=AD.GovernedToolsExecutor(mkgov, grant_levels='L1+L4', confirm='view')
    ex.current_user_task=ut
    msgs=[{'role':'user','content':ut.PROMPT}]
    for m in d['messages']:
        if m['role']!='assistant': continue
        tcs=m.get('tool_calls') or []
        fcs=[]
        for tc in tcs:
            if isinstance(tc,dict):
                fcs.append(FunctionCall(id=tc.get('id','x'),function=tc.get('function'),args=dict(tc.get('args') or {})))
            else:  # recorded as a repr string: function='X' args={...} id='Y'
                mf=re.search(r"function='([^']+)'",tc); ma=re.search(r"args=(\{.*?\})\s+id=",tc,re.S); mi=re.search(r"id='([^']+)'",tc)
                args=ast.literal_eval(ma.group(1)) if ma else {}
                fcs.append(FunctionCall(id=mi.group(1) if mi else 'x',function=mf.group(1),args=args))
        if not fcs: continue
        am={'role':'assistant','content':m.get('content') or [],'tool_calls':fcs}
        _,_,env,msgs2,_=ex.query(ut.PROMPT,rt,env,[*msgs,am],{})
        msgs=msgs2
    tid=ut.ID
    print('==',suite_name,ut_id)
    print('  calls     :',json.dumps(ex.calls_log.get(tid))[:300])
    print('  l4_stats  :',ex.l4_stats.get(tid))
    print('  l4_decis  :',json.dumps(ex.l4_log.get(tid))[:300])
    print('  confirms  :',ex.confirmations.get(tid))
