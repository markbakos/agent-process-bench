from .policy import ROUND


class ApprovalWorkflow:
    def __init__(self, finance_threshold_cents=None, department_managers=None, finance_approver="finance"):
        self.threshold=finance_threshold_cents; self.managers=department_managers or {}; self.finance_approver=finance_approver
        self.requests={}; self.delegations=[]; self._next=1

    def _event(self,req,action,actor,comment=None):
        req["_history"].append({"action":action,"actor":actor,"comment":comment,"sequence":len(req["_history"])+1})

    def _public(self,req): return {k:v for k,v in req.items() if not k.startswith("_")}

    def submit(self,submitter,department,amount_cents,comment=None):
        if isinstance(amount_cents,bool) or not isinstance(amount_cents,int) or amount_cents<0: raise ValueError("invalid amount")
        rid=f"request-{self._next}"; self._next+=1
        req={"id":rid,"submitter":submitter,"department":department,"amount_cents":amount_cents,"status":"pending_manager","_history":[]}
        self.requests[rid]=req; self._event(req,"submitted",submitter,comment); return self._public(req)

    def get(self,request_id):
        if request_id not in self.requests: raise KeyError(request_id)
        return self._public(self.requests[request_id])

    def _required(self,req): return "manager" if req["status"]=="pending_manager" else "finance" if req["status"]=="pending_finance" else None

    def _authorized(self,req,actor,role,on_date):
        if role!=self._required(req): return False
        if role=="manager" and ROUND>=2: owner=self.managers.get(req["department"])
        elif role=="finance" and ROUND>=5: owner=self.finance_approver
        else: return True
        if owner is None: return False
        if actor==owner: return True
        if ROUND>=5 and on_date is not None:
            if ROUND == 5:
                authorized={owner}
                changed=True
                while changed:
                    changed=False
                    for delegation in self.delegations:
                        if delegation["approver"] in authorized and delegation["start"]<=on_date<=delegation["end"] and delegation["delegate"] not in authorized:
                            authorized.add(delegation["delegate"]); changed=True
                return actor in authorized
            return any(d["approver"]==owner and d["delegate"]==actor and d["start"]<=on_date<=d["end"] for d in self.delegations)
        return False

    def approve(self,request_id,actor,role,comment=None,*,on_date=None):
        req=self.requests.get(request_id)
        if req is None: raise KeyError(request_id)
        if actor==req["submitter"] or not self._authorized(req,actor,role,on_date): raise ValueError("not authorized")
        if role=="manager":
            req["status"]=("pending_finance" if ROUND==0 or (ROUND>=1 and req["amount_cents"]>self.threshold) else "approved")
            action="approved_manager"
        else: req["status"]="approved"; action="approved_finance"
        self._event(req,action,actor,comment); return self._public(req)

    def reject(self,request_id,actor,role,comment=None,*,on_date=None):
        req=self.requests.get(request_id)
        if req is None: raise KeyError(request_id)
        if not self._authorized(req,actor,role,on_date): raise ValueError("not authorized")
        req["status"]="rejected"; self._event(req,"rejected",actor,comment); return self._public(req)

    def comment(self,request_id,actor,text):
        if ROUND<3 or not isinstance(text,str) or not text.strip(): raise ValueError("invalid comment")
        req=self.requests.get(request_id)
        if req is None: raise KeyError(request_id)
        self._event(req,"commented",actor,text)

    def history(self,request_id):
        if ROUND<3: raise AttributeError("history unavailable")
        if request_id not in self.requests: raise KeyError(request_id)
        return [dict(x) for x in self.requests[request_id]["_history"]]

    def resubmit(self,request_id,actor,*,amount_cents=None,comment=None):
        if ROUND<4: raise ValueError("resubmission unavailable")
        req=self.requests.get(request_id)
        if req is None: raise KeyError(request_id)
        if req["status"]!="rejected" or actor!=req["submitter"]: raise ValueError("cannot resubmit")
        if amount_cents is not None:
            if isinstance(amount_cents,bool) or not isinstance(amount_cents,int) or amount_cents<0: raise ValueError("invalid amount")
            req["amount_cents"]=amount_cents
        req["status"]="pending_manager"; self._event(req,"resubmitted",actor,comment); return self._public(req)

    def delegate(self,approver,delegate,start_date,end_date):
        if ROUND<5 or end_date<start_date: raise ValueError("invalid delegation")
        self.delegations.append({"approver":approver,"delegate":delegate,"start":start_date,"end":end_date})
