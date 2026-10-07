from threading import RLock

from certmon.audit import AuditService


AUTO_REMOVE_KEY = "upload_auto_remove_successful"
COMPLETED_KEY = "upload_completed_certificates"
RECORDED_RUNS_KEY = "upload_recorded_runs"
_lock = RLock()


class UploadQueueService:
    def __init__(self, database):
        self.database = database

    def auto_remove(self):
        return self.database.get_setting(AUTO_REMOVE_KEY, False) is True

    def completed(self):
        return set(self.database.get_setting(COMPLETED_KEY, []))

    def finish(self, *, method, run_id, outcomes, remove_successful=False):
        # Persist every result before hiding anything. Keep private material
        # out of audit records and make completion idempotent.
        with _lock:
            recorded = self.database.get_setting(RECORDED_RUNS_KEY, [])
            if run_id in recorded:
                return
            audit = AuditService(self.database)
            for outcome in outcomes:
                audit.record(
                    "certificate_upload_succeeded" if outcome["ok"] else "certificate_upload_failed",
                    target=outcome["selector"], success=outcome["ok"],
                    details={"method": method, "run_id": run_id,
                             "certificate_id": outcome["certificate_id"],
                             "result": outcome["status"], "nic": outcome.get("nic")},
                )
            if remove_successful:
                completed = self.completed()
                completed.update(item["certificate_id"] for item in outcomes if item["ok"])
                self.database.put_setting(COMPLETED_KEY, sorted(completed))
            self.database.put_setting(RECORDED_RUNS_KEY, [*recorded, run_id])
