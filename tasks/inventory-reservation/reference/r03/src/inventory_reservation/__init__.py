from .policy import ROUND


class IdempotencyConflict(ValueError):
    pass


class Inventory:
    def __init__(self, initial_stock):
        self._stock = {}
        for key, quantity in initial_stock.items():
            if not isinstance(key, tuple) or len(key) != 2 or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ValueError("invalid stock")
            self._stock[key] = quantity
        self._reservations = {}
        self._keys = {}
        self._next_id = 1

    def _active(self, sku, warehouse):
        return sum(r["quantity"] for r in self._reservations.values()
                   if r["sku"] == sku and r["warehouse"] == warehouse and r["status"] == "active")

    def availability(self, sku, warehouse):
        physical = self._stock.get((sku, warehouse), 0)
        active = self._active(sku, warehouse)
        if ROUND >= 5:
            return {"physical_on_hand": physical, "active_reserved": active,
                    "available": physical - active, "backordered": max(0, active - physical)}
        return physical - active

    def reserve(self, sku, warehouse, quantity, *, idempotency_key=None):
        if (sku, warehouse) not in self._stock or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("invalid reservation")
        payload = (sku, warehouse, quantity)
        if ROUND >= 1 and idempotency_key is not None and idempotency_key in self._keys:
            old_payload, reservation_id = self._keys[idempotency_key]
            if ROUND >= 4 and old_payload != payload:
                raise IdempotencyConflict(idempotency_key)
            return dict(self._reservations[reservation_id])
        available = self.availability(sku, warehouse)
        available = available["available"] if isinstance(available, dict) else available
        if ROUND < 2 and quantity > available:
            raise ValueError("insufficient stock")
        item = {"id": f"res-{self._next_id}", "sku": sku, "warehouse": warehouse,
                "quantity": quantity, "status": "active"}
        self._next_id += 1
        self._reservations[item["id"]] = item
        if ROUND >= 1 and idempotency_key is not None:
            self._keys[idempotency_key] = (payload, item["id"])
        return dict(item)

    def _get_active(self, reservation_id):
        if reservation_id not in self._reservations:
            raise KeyError(reservation_id)
        item = self._reservations[reservation_id]
        if item["status"] != "active":
            raise ValueError("reservation is not active")
        return item

    def release(self, reservation_id):
        item = self._get_active(reservation_id)
        if ROUND >= 3:
            item["status"] = "released"
        else:
            del self._reservations[reservation_id]

    def commit(self, reservation_id):
        item = self._get_active(reservation_id); key = (item["sku"], item["warehouse"])
        if ROUND < 2 and self._stock[key] < item["quantity"]:
            raise ValueError("negative stock")
        self._stock[key] = max(0, self._stock[key] - item["quantity"])
        if ROUND >= 3:
            item["status"] = "committed"
        else:
            del self._reservations[reservation_id]

    def get_reservation(self, reservation_id):
        if ROUND < 3 or reservation_id not in self._reservations:
            raise KeyError(reservation_id)
        return dict(self._reservations[reservation_id])

    def transfer(self, sku, source, destination, quantity):
        if ROUND < 6 or source == destination or (sku, source) not in self._stock or (sku, destination) not in self._stock:
            raise ValueError("invalid transfer")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0 or quantity > self._stock[(sku, source)]:
            raise ValueError("invalid quantity")
        self._stock[(sku, source)] -= quantity; self._stock[(sku, destination)] += quantity
        return {"source": self.availability(sku, source), "destination": self.availability(sku, destination)}
