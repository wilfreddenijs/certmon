def ordered_credentials(individual=None, shared=None):
    """Use configured credential pairs before the Extron factory default."""
    result = []
    for value in (individual, shared, {"username": "admin", "password": "extron"}):
        if not value or not value.get("password"):
            continue
        candidate = {"username": value.get("username") or "admin", "password": value["password"]}
        if candidate not in result:
            result.append(candidate)
    return result
