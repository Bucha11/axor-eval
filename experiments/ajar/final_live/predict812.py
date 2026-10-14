import json,glob,re,sys,ast,os
sys.path.insert(0,'/home/user/core-m1')
from agentdojo.task_suite.load_suites import get_suite
from axor_core.config import GovernanceConfig
from axor_core.governor import ToolCallGovernor
from axor_core.kernel.handles import canonicalize, split_kind
from axor_core.policy.content_tokens import extract
R='/home/user/ajar-wt/experiments/ajar/results/live_final'
C='/home/user/ajar-wt/experiments/ajar/config_m1_c812'
temporal=re.compile(r"(date|time|day)",re.I)
def proj(kinds,args):
    out=[]
    for k,spec in sorted(kinds.items()):
        if temporal.search(k): continue
        kind=split_kind(spec)[0]; v=args.get(k)
        vals=v if isinstance(v,(list,tuple)) else ([] if v is None else [v])
        try: out.append((k,tuple(sorted(canonicalize(kind,x) for x in vals))))
        except ValueError: out.append((k,("<bad>",)))
    return tuple(out)
res=[]
for f in sorted(glob.glob(R+'/B/pass*/traj/*/*.json')):
    d=json.load(open(f)); s=json.dumps(d['messages'])
    if '(content_projection)' not in s: continue
    suite=d['suite']; tid=d['user_task_id']
    S=get_suite('v1',suite); ut=S.user_tasks[tid]
    env=ut.init_environment(S.load_and_inject_default_environment({}))
    gt=list(ut.ground_truth(env.model_copy(deep=True)))
    cfg=GovernanceConfig.from_yaml(f'{C}/{suite}.yaml')
    g=ToolCallGovernor(**cfg.as_governor_kwargs()); g.register_task(ut.PROMPT)
    for m in d['messages']:
        if m['role']!='tool' or '(content_projection)' not in json.dumps(m): continue
        tc=m['tool_call']; mm=re.match(r"function='(\w+)' args=(\{.*\}) id=",tc)
        tool=mm.group(1); args=ast.literal_eval(mm.group(2))
        gd,flagged=g._content_refusal(tool,args)
        kinds=cfg.grant_args.get(tool,{})
        match=[c for c in gt if c.function==tool and proj(kinds,dict(c.args))==proj(kinds,args)]
        ok=any(set(flagged)<={v for _k,v in extract(dict(c.args))} for c in match)
        res.append((f.split('/')[-4],suite,tid,tool,flagged,bool(match),ok,d['utility']))
for r in res: print(r)
print('calls',len(res),'grant-args match',sum(r[5] for r in res),'oracle approves',sum(r[6] for r in res))
