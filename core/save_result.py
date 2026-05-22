from typing import Any

SAVE_STATUS_SUCCESS = "success"
SAVE_STATUS_FAILED = "failed"
SAVE_STATUS_CANCELLED = "cancelled"


def save_success(message: str = "", **extra) -> dict:
    result = {"status": SAVE_STATUS_SUCCESS}
    if message:
        result["message"] = message
    result.update(extra)
    return result


def save_failed(message: str = "", **extra) -> dict:
    result = {"status": SAVE_STATUS_FAILED}
    if message:
        result["message"] = message
    result.update(extra)
    return result


def save_cancelled(message: str = "", **extra) -> dict:
    result = {"status": SAVE_STATUS_CANCELLED}
    if message:
        result["message"] = message
    result.update(extra)
    return result


def normalize_save_result(result: Any) -> dict:
    if isinstance(result, dict):
        status = result.get("status")
        if status in {SAVE_STATUS_SUCCESS, SAVE_STATUS_FAILED, SAVE_STATUS_CANCELLED}:
            return result
        if "cancelled" in result:
            return save_cancelled(**{k: v for k, v in result.items() if k != "cancelled"})
        if "success" in result:
            payload = {k: v for k, v in result.items() if k != "success"}
            return save_success(**payload) if result.get("success") else save_failed(**payload)

    if result is True:
        return save_success()
    if result is False:
        return save_failed()
    if result is None:
        return save_failed()
    return save_success(value=result)


def save_result_status(result: Any) -> str:
    return normalize_save_result(result).get("status", SAVE_STATUS_FAILED)


def save_result_message(result: Any) -> str:
    return str(normalize_save_result(result).get("message", "") or "")


def is_save_success(result) -> bool:
    return save_result_status(result) == SAVE_STATUS_SUCCESS


def is_save_failed(result) -> bool:
    return save_result_status(result) == SAVE_STATUS_FAILED


def is_save_cancelled(result) -> bool:
    return save_result_status(result) == SAVE_STATUS_CANCELLED
