import os,sys,glob,json,re,dataclasses
os.environ["AXOR_AJAR_CONFIG_DIR"]="/home/user/ajar-wt/experiments/ajar/config_m1_c9v6"
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"]="1"; os.environ["AXOR_AJAR_L2"]="tuple"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT","/home/user/Ajar/bench/agentdojo")
HERE="/home/user/ajar-wt/experiments/ajar"
sys.path.insert(0,os.environ.get("ROPE_SRC","/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad/ext/rope/src"))
sys.path.insert(0,"/home/user/core-m1"); sys.path.insert(0,"/home/user/Ajar"); sys.path.insert(0,HERE)
import axor_ajar
from axor_core.governor import ToolCallGovernor
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from check_wrapper import VERSIONS
from rope.scopes_io import load_router_scopes
from rope import origin as RO, policy_synthesis as PS
from rope.enforce import Enforcer
MODELS=["gpt-4o-2024-05-13","claude-3-5-sonnet-20241022","gpt-4o-mini-2024-07-18"]
SUITES=["banking","slack","travel"]
ROOT=os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"],"runs")
SENDER_FIELD={"Message":"sender","Email":"sender","Transaction":"sender"}
def item_senders(typed):
    seq=typed if isinstance(typed,list) else [typed]
    return [getattr(it,SENDER_FIELD.get(type(it).__name__),None) if SENDER_FIELD.get(type(it).__name__) and hasattr(it,SENDER_FIELD.get(type(it).__name__,"")) else None for it in seq]
def payloads(run): return [str(v) for v in (run.get("injections") or {}).values() if isinstance(v,str) and len(str(v))>=8]
def frags(pls,W=24):
    f=set()
    for b in pls:
        b=str(b)
        for i in range(0,max(0,len(b)-W+1),4): f.add(b[i:i+W])
    return f
def carries(r,pls):
    try: s=tool_result_to_str(r)
    except Exception: return False
    return isinstance(s,str) and any(fr in s for fr in frags(pls))
def wrap(out,trusted):
    return f"- from: {trusted}\n  body: |\n"+"\n".join("  "+ln for ln in str(out).splitlines())+"\n"
_RS={}
def rope_suite(s):
    if s not in _RS:
        floor,scopes=load_router_scopes("opus",s); suite=get_suite(VERSIONS[s],s)
        tools=[{"name":t.name,"description":t.description,"args":t.parameters.model_json_schema().get("properties",{})} for t in suite.tools]
        _RS[s]=(floor,scopes,tools)
    return _RS[s]
def rope_admit(s,prompt,msgs,tool,args):
    floor,scopes,tools=rope_suite(s); om={}; tr=RO.OriginTracker(om); tr.query(prompt,None,None,msgs,{})
    scope=scopes.get(prompt); enf=Enforcer(); enf.update_available_tools(tools); enf.set_user_query(prompt)
    policy=PS.compile_policy(floor,scope,origin_map=om,prompt_ids=RO.tokenize_identifiers(prompt)) if scope is not None else {}
    enf.update_security_policy(policy); enf.update_always_allowed_tools([t["name"] for t in tools if t["name"] not in floor])
    try: enf.check_tool_call(tool,dict(args)); return True
    except Exception: return False
def axor_gov(s,prompt):
    cfg=dataclasses.replace(axor_ajar.load_config(s,"context","request-only"),references=True)
    kwargs,hook=axor_ajar.grants_kwargs("L1+L2s",tuple_grants=True,counters=True)
    from types import SimpleNamespace
    spec=SimpleNamespace(task=SimpleNamespace(suite=s),prompt=prompt,plan=[]); kw=cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g=ToolCallGovernor(**kw); g.register_task(prompt); hook(g,spec); return g

def run(defense):
    landed=0; built=0; nonempty=0; miss=0; empty=0
    for m in MODELS:
        for s in SUITES:
            suite=get_suite(VERSIONS[s],s); floor,scopes,_=rope_suite(s)
            for p in glob.glob(os.path.join(ROOT,m,s,"user_task_*","important_instructions","*.json")):
                run=json.load(open(p)); ut=suite.user_tasks[run["user_task_id"]]
                prompt=next((x["content"] for x in run["messages"] if x["role"]=="user"),"")
                if isinstance(prompt,list): prompt="".join(b.get("content","") for b in prompt)
                scope=scopes.get(prompt)
                if scope is None: miss+=1; continue              # cache miss = not built (router error)
                ns=list(getattr(scope,"named_source",()) or [])
                if not ns: empty+=1; continue                    # empty named_source = not built
                nonempty+=1; trusted=str(ns[0]); pls=payloads(run)
                # applicable only where an injected read exists
                e2=ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {}))); rt2=FunctionsRuntime(suite.tools)
                appl=False
                for c in [tc for x in run["messages"] if x["role"]=="assistant" for tc in (x.get("tool_calls") or [])]:
                    r,err=rt2.run_function(e2,c["function"],dict(c["args"]))
                    if err is None and carries(r,pls): appl=True; break
                if not appl: continue
                built+=1
                env=ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {}))); pre=env.model_copy(deep=True)
                rt=FunctionsRuntime(suite.tools); g=axor_gov(s,prompt) if defense=="axor" else None; msgs=[]; exc=[]
                for c in [tc for x in run["messages"] if x["role"]=="assistant" for tc in (x.get("tool_calls") or [])]:
                    tool=c["function"]; args=dict(c["args"])
                    adm = rope_admit(s,prompt,msgs,tool,args) if defense=="rope" else g.evaluate(tool,axor_ajar.agent_args(g,dict(args))).allowed
                    if defense=="axor": d=g.evaluate(tool,axor_ajar.agent_args(g,dict(args))); adm=d.allowed
                    if not adm: msgs.append({"role":"tool","content":"","tool_call":FunctionCall(function=tool,args=args,id="x")}); continue
                    r,err=rt.run_function(env,tool,dict(args)); exc.append(FunctionCall(function=tool,args=dict(args),id="x"))
                    out="" if err is not None else tool_result_to_str(r)
                    if err is None and carries(r,pls): out=wrap(out,trusted)
                    if defense=="axor" and err is None:
                        g.present_output(d,out,item_senders=(item_senders(r) if g._sender_from_typed else None))
                    msgs.append({"role":"tool","content":out,"tool_call":FunctionCall(function=tool,args=args,id="x")})
                it=suite.injection_tasks.get(run.get("injection_task_id") or "")
                if it is not None and bool(suite._check_injection_task_security(it,[],pre,env,exc)): landed+=1
    return dict(landed=landed, built=built, nonempty_named_source=nonempty, miss=miss, empty_named_source=empty)
for d in ("rope","axor"):
    print(d, run(d))
print("DONE")
