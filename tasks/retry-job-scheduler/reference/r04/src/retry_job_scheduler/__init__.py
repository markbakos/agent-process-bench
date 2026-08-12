from datetime import timedelta

from .policy import ROUND


class JobScheduler:
    def __init__(self,base_delay_seconds=60,max_attempts=3,max_backoff_seconds=None):
        if base_delay_seconds<=0 or max_attempts<=0 or (ROUND>=1 and (max_backoff_seconds is None or max_backoff_seconds<=0)): raise ValueError("invalid policy")
        self.base=base_delay_seconds; self.maximum=max_attempts; self.cap=max_backoff_seconds; self.jobs={}; self.series={}; self._order=0

    def _new(self,job_id,due_at,dependencies=(),series_id=None,occurrence=None):
        self._order+=1; self.jobs[job_id]={"id":job_id,"due_at":due_at,"status":"pending","attempts":0,
                                             "dependencies":list(dependencies),"order":self._order,"series_id":series_id,"occurrence":occurrence}

    def schedule(self,job_id,due_at,*,recurrence_seconds=None,dependencies=()):
        if job_id in self.jobs or job_id in self.series: raise ValueError("duplicate id")
        if ROUND < 4 and dependencies: raise ValueError("dependencies unavailable")
        if any(dep not in self.jobs for dep in dependencies): raise ValueError("unknown dependency")
        if ROUND>=2 and recurrence_seconds is not None:
            if recurrence_seconds<=0 or dependencies: raise ValueError("invalid recurrence")
            self.series[job_id]={"interval":recurrence_seconds,"next":2,"paused":False}
            self._new(f"{job_id}#1",due_at,series_id=job_id,occurrence=1); return
        self._new(job_id,due_at,dependencies)

    def get(self,job_id):
        if job_id not in self.jobs: raise KeyError(job_id)
        return dict(self.jobs[job_id])

    def _propagate_skips(self):
        if ROUND<5: return
        changed=True
        while changed:
            changed=False
            for job in self.jobs.values():
                if job["status"]=="pending" and any(self.jobs[d]["status"] in {"failed","skipped"} for d in job["dependencies"]):
                    job["status"]="skipped"; changed=True

    def pop_due(self,now):
        self._propagate_skips()
        candidates=[j for j in self.jobs.values() if j["status"]=="pending" and j["due_at"]<=now and all(self.jobs[d]["status"]=="succeeded" for d in j["dependencies"])]
        if not candidates: return None
        job=min(candidates,key=lambda j:(j["due_at"],j["order"])); job["status"]="running"; job["attempts"]+=1; return dict(job)

    def _next_occurrence(self,job,due_at=None):
        sid=job["series_id"]
        if not sid: return
        series=self.series[sid]; number=series["next"]; series["next"]+=1
        self._new(f"{sid}#{number}",due_at or (job["due_at"]+timedelta(seconds=series["interval"])),series_id=sid,occurrence=number)

    def record_result(self,job_id,success,finished_at,*,failure_kind="transient"):
        job=self.jobs.get(job_id)
        if job is None: raise KeyError(job_id)
        if job["status"]!="running": raise ValueError("job not running")
        if success:
            job["status"]="succeeded"; self._next_occurrence(job); self._propagate_skips(); return
        if ROUND>=3 and failure_kind=="permanent": terminal=True
        elif failure_kind not in {"transient","permanent"}: raise ValueError("invalid failure kind")
        else: terminal=job["attempts"]>=self.maximum
        if terminal:
            job["status"]="failed"
            if job["series_id"] and ROUND>=6: self.series[job["series_id"]]["paused"]=True
            else: self._next_occurrence(job)
            self._propagate_skips(); return
        delay=self.base*2**(job["attempts"]-1)
        if ROUND>=1: delay=min(delay,self.cap)
        job["due_at"]=finished_at+timedelta(seconds=delay); job["status"]="pending"

    def resume(self,series_id,due_at):
        if ROUND<6 or series_id not in self.series or not self.series[series_id]["paused"]: raise ValueError("series not paused")
        previous=max((j for j in self.jobs.values() if j["series_id"]==series_id),key=lambda j:j["occurrence"])
        self.series[series_id]["paused"]=False; self._next_occurrence(previous,due_at)
