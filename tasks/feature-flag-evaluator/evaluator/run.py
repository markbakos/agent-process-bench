import argparse
import hashlib
import json
import sys
sys.dont_write_bytecode = True
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--round",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); tests=[]; errors=[]
    def check(name,fn):
        try: fn(); tests.append(True)
        except Exception as exc: tests.append(False); errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        sys.path.insert(0,str(a.workspace/"src")); import feature_flag_evaluator as m; F=m.FlagEvaluator; i=int(a.round[1:])
        def base():
            e=F({"off":{"enabled":False},"on":{"enabled":True,"rollout":100},"none":{"enabled":True,"rollout":0}}); user={"id":"u"}; assert not e.evaluate("off",user) and e.evaluate("on",user) and not e.evaluate("none",user) and e.evaluate("on",user)==e.evaluate("on",user)
            if i<3: assert not e.evaluate("missing",user)
            else:
                try: e.evaluate("missing",user)
                except m.UnknownFlagError: pass
                else: raise AssertionError("unknown false")
        check("boolean rollout and unknown policy",base)
        if i>=1:
            def rules():
                if i==1:
                    flags={"f":{"enabled":True,"rollout":0,"rules":[{"attribute":"country","equals":"RS"}]}}; assert F(flags).evaluate("f",{"id":"u","country":"RS"})
                else:
                    flags={"f":{"enabled":True,"rollout":100,"rules":[{"attribute":"country","equals":"RS","value":False},{"attribute":"plan","equals":"pro","value":True}]}}; assert not F(flags).evaluate("f",{"id":"u","country":"RS","plan":"pro"})
            check("targeting semantics",rules)
        if i>=4:
            def flag_hash():
                user={"id":"u0"}; flags={"a":{"enabled":True,"rollout":50},"b":{"enabled":True,"rollout":50}}; e=F(flags)
                expected=[]
                for key in ("a","b"):
                    n=int.from_bytes(hashlib.sha256(f"{key}:u0".encode()).digest()[:8],"big"); expected.append(n%10000<5000)
                assert [e.evaluate("a",user),e.evaluate("b",user)]==expected
            check("flag-specific hash",flag_hash)
        if i>=5:
            def prereqs():
                e=F({"base":{"enabled":False},"child":{"enabled":True,"prerequisites":["base"]}}); assert not e.evaluate("child",{"id":"u"})
                bad=F({"a":{"enabled":True,"prerequisites":["b"]},"b":{"enabled":True,"prerequisites":["a"]}})
                if i==5: assert not bad.evaluate("a",{"id":"u"})
                else:
                    try: bad.evaluate("a",{"id":"u"})
                    except m.FlagConfigurationError: return
                    raise AssertionError("cycle not error")
            check("prerequisites",prereqs)
        if i>=6:
            def missing_prereq():
                try: F({"a":{"enabled":True,"prerequisites":["missing"]}}).evaluate("a",{"id":"u"})
                except m.FlagConfigurationError: return
                raise AssertionError("missing prerequisite")
            check("missing prerequisite error",missing_prereq)
        status,build="ok","passed"
    except Exception as exc: tests.append(False); errors.append(f"import/build: {type(exc).__name__}: {exc}"); status,build="error","failed"
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"status":status,"tests_passed":sum(tests),"tests_total":len(tests),"build_status":build,"errors":errors})+"\n")
if __name__=="__main__": main()
