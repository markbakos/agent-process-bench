from datetime import datetime, time, timedelta

from .policy import ROUND


class Scheduler:
    def __init__(self, provider_hours=None):
        self.provider_hours = provider_hours or {}
        self._appointments = {}
        self._next_id = 1

    def _hours(self, provider, weekday):
        if ROUND >= 3 and provider in self.provider_hours:
            return self.provider_hours[provider].get(weekday)
        defaults = ({day: (time(9), time(17)) for day in range(5)} if ROUND == 0 else
                    {day: (time(9), time(17)) for day in range(1, 5)} | {5: (time(9), time(13))})
        return defaults.get(weekday)

    def _validate(self, provider, start, duration, ignore=None, extra=()):
        if not isinstance(start, datetime) or start.tzinfo is not None:
            raise ValueError("naive datetime required")
        allowed = {30} if ROUND < 2 else {30, 60, 90}
        if isinstance(duration, bool) or duration not in allowed:
            raise ValueError("invalid duration")
        hours = self._hours(provider, start.weekday())
        end = start + timedelta(minutes=duration)
        if not hours or start.time() < hours[0] or end.date() != start.date() or end.time() > hours[1]:
            raise ValueError("outside working hours")
        candidates = [a for a in self._appointments.values() if a["status"] == "active"] + list(extra)
        for item in candidates:
            if item["id"] == ignore or item["provider"] != provider:
                continue
            item_end = item["start"] + timedelta(minutes=item["duration_minutes"])
            if start < item_end and item["start"] < end:
                raise ValueError("overlap")

    def _create(self, provider, start, duration):
        item = {"id": f"appt-{self._next_id}", "provider": provider, "start": start,
                "duration_minutes": duration, "status": "active"}
        self._next_id += 1
        self._appointments[item["id"]] = item
        return dict(item)

    def book(self, provider, start, *, duration_minutes=30):
        self._validate(provider, start, duration_minutes)
        return self._create(provider, start, duration_minutes)

    def cancel(self, appointment_id):
        if appointment_id not in self._appointments:
            raise KeyError(appointment_id)
        if ROUND >= 6:
            self._appointments[appointment_id]["status"] = "cancelled"
        else:
            del self._appointments[appointment_id]

    def reschedule(self, appointment_id, new_start, *, duration_minutes=None):
        if appointment_id not in self._appointments:
            raise KeyError(appointment_id)
        item = self._appointments[appointment_id]
        if item["status"] != "active":
            raise ValueError("cancelled appointment")
        duration = item["duration_minutes"] if duration_minutes is None else duration_minutes
        self._validate(item["provider"], new_start, duration, ignore=appointment_id)
        item["start"], item["duration_minutes"] = new_start, duration
        return dict(item)

    def list_appointments(self, provider=None):
        return [dict(a) for a in sorted(self._appointments.values(), key=lambda x: (x["start"], x["id"]))
                if a["status"] == "active" and (provider is None or a["provider"] == provider)]

    def history(self, provider=None):
        if ROUND < 6:
            raise AttributeError("history")
        return [dict(a) for a in sorted(self._appointments.values(), key=lambda x: (x["start"], x["id"]))
                if provider is None or a["provider"] == provider]

    def book_recurring(self, provider, start, count, *, interval_weeks=1, duration_minutes=30):
        if ROUND < 4 or isinstance(count, bool) or count <= 0 or isinstance(interval_weeks, bool) or interval_weeks <= 0:
            raise ValueError("invalid recurrence")
        starts = [start + timedelta(weeks=interval_weeks * n) for n in range(count)]
        if ROUND >= 5:
            pending = []
            for value in starts:
                self._validate(provider, value, duration_minutes, extra=pending)
                pending.append({"id": "pending", "provider": provider, "start": value,
                                "duration_minutes": duration_minutes, "status": "active"})
            return {"created": [self._create(provider, value, duration_minutes) for value in starts], "skipped": []}
        created, skipped = [], []
        for value in starts:
            try:
                created.append(self.book(provider, value, duration_minutes=duration_minutes))
            except ValueError:
                skipped.append(value)
        return {"created": created, "skipped": skipped}
