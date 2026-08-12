import hashlib

from .policy import ROUND


class UnknownFlagError(KeyError): pass
class FlagConfigurationError(ValueError): pass


class FlagEvaluator:
    def __init__(self,flags):
        self.flags=flags
        for flag in flags.values():
            rollout=flag.get("rollout",100)
            if isinstance(rollout,bool) or not isinstance(rollout,int) or not 0<=rollout<=100: raise ValueError("invalid rollout")
            if ROUND>=1:
                for rule in flag.get("rules",[]):
                    if rule.get("attribute") not in {"country","plan"}: raise ValueError("invalid attribute")

    def evaluate(self,flag_key,user):
        if not isinstance(user.get("id"),str): raise ValueError("user id required")
        return self._evaluate(flag_key,user,[])

    def _evaluate(self,key,user,stack):
        if key not in self.flags:
            if ROUND>=3: raise UnknownFlagError(key)
            return False
        if key in stack:
            if ROUND>=6: raise FlagConfigurationError("prerequisite cycle")
            return False
        flag=self.flags[key]
        if ROUND>=5:
            for dependency in flag.get("prerequisites",[]):
                if dependency not in self.flags:
                    if ROUND>=6: raise FlagConfigurationError(f"missing prerequisite: {dependency}")
                    return False
                if not self._evaluate(dependency,user,stack+[key]): return False
        if not flag.get("enabled",False): return False
        if ROUND>=1:
            for rule in flag.get("rules",[]):
                if user.get(rule["attribute"])==rule.get("equals"):
                    return bool(rule.get("value")) if ROUND>=2 else True
        value=f"{key}:{user['id']}" if ROUND>=4 else user["id"]
        bucket=int.from_bytes(hashlib.sha256(value.encode()).digest()[:8],"big")%10000
        return bucket<flag.get("rollout",100)*100
