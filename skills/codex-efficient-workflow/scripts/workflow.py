#!/usr/bin/env python3
"""Local configuration/receipt helper. No network, credentials or model API calls."""
import argparse
import copy
import hashlib
import json
import math
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

SKILL = Path(__file__).resolve().parents[1]
ROLES = ("planner", "executor", "executor_complex", "reviewer")
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")


def now():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def date(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def recent(value, days):
    age = now() - date(value)
    return timedelta(minutes=-5) <= age <= timedelta(days=days)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("refusing symlink target: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def fingerprint(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(config):
    if config.get("schema_version") != 1:
        raise ValueError("unsupported config schema")
    for role in ROLES:
        entry = config["roles"][role]
        for key in ("model", "provider", "family", "instructions"):
            if not nonempty(entry.get(key)):
                raise ValueError(role + ": missing " + key)
        if entry.get("reasoning_effort") not in EFFORTS:
            raise ValueError(role + ": invalid reasoning effort")
        if type(entry.get("generation")) is not int or entry["generation"] < 1:
            raise ValueError(role + ": generation must be a positive integer")
        if entry.get("update_mode") not in ("auto_major", "pinned"):
            raise ValueError(role + ": invalid update_mode")
    for key in ("max_parallel", "max_dispatches", "packet_target_chars"):
        if type(config["limits"].get(key)) is not int or config["limits"][key] < 1:
            raise ValueError("limits." + key + " must be positive")
    for key in ("same_model_repairs", "max_escalations"):
        if type(config["limits"].get(key)) is not int or config["limits"][key] < 0:
            raise ValueError("limits." + key + " must be nonnegative")
    updates = config["updates"]
    for key in ("check_interval_days", "retry_interval_hours", "evidence_max_age_days", "min_eval_cases"):
        if type(updates.get(key)) is not int or updates[key] < 1:
            raise ValueError("updates." + key + " must be positive")
    if not number(updates.get("max_quality_drop")) or not 0 <= updates["max_quality_drop"] <= 1:
        raise ValueError("invalid max_quality_drop")
    if not number(updates.get("min_acceptance_rate")) or not 0 <= updates["min_acceptance_rate"] <= 1:
        raise ValueError("invalid min_acceptance_rate")
    if not number(updates.get("max_usage_ratio")) or updates["max_usage_ratio"] <= 0:
        raise ValueError("invalid max_usage_ratio")
    hosts = updates.get("allowed_source_hosts")
    if not isinstance(hosts, list) or not hosts or any(not nonempty(x) or "/" in x or ":" in x for x in hosts):
        raise ValueError("allowed_source_hosts must contain exact hostnames")
    return config


def root(project):
    return Path(project).expanduser().resolve()


def folder(project):
    project = root(project)
    result = project / ".codex-efficient-workflow"
    if result.is_symlink() or not result.resolve().is_relative_to(project):
        raise ValueError("state directory escapes project")
    return result


@contextmanager
def locked(project):
    base = folder(project)
    base.mkdir(parents=True, exist_ok=True)
    lock = base / ".lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError("another operation is active; inspect stale .lock before removing it")
    try:
        yield base
    finally:
        lock.rmdir()


def load(project):
    base = folder(project)
    config = validate(read(base / "config.json"))
    state = read(base / "state.json")
    return base, config, state


def init(project):
    with locked(project) as base:
        config_path = base / "config.json"
        state_path = base / "state.json"
        # Never overwrite a user config, including one copied in before init.
        config = validate(read(config_path)) if config_path.exists() else validate(read(SKILL / "defaults.json"))
        if not config_path.exists():
            config["created_at"] = stamp()
            config["updated_at"] = stamp()
            write(config_path, config)
        if not state_path.exists():
            write(state_path, {"schema_version": 1, "created_at": stamp(), "last_check_attempt_at": None,
                              "last_successful_check_at": None, "last_config_change_at": None,
                              "check_failed": False, "pending": [], "generated": {}})
    return status(project)


def status(project):
    base = folder(project)
    if not (base / "config.json").exists():
        return {"initialized": False, "project": str(root(project)), "refresh_due": True}
    base, config, state = load(project)
    successful = state.get("last_successful_check_at")
    due = not successful or now() >= date(successful) + timedelta(days=config["updates"]["check_interval_days"])
    retry = None
    if state.get("check_failed") and state.get("last_check_attempt_at"):
        retry = date(state["last_check_attempt_at"]) + timedelta(hours=config["updates"]["retry_interval_hours"])
        due = due and now() >= retry
    return {"initialized": True, "config_path": str(base / "config.json"),
            "config_fingerprint": fingerprint(config), "config": config,
            "refresh_due": due, "retry_after": stamp(retry) if retry else None, "state": state}


def backup(base, config):
    ident = now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    if not (base / "backups").resolve().is_relative_to(base.resolve()):
        raise ValueError("backup directory escapes state directory")
    write(base / "backups" / (ident + ".json"), config)
    return ident


def audit(base, record):
    record = dict(record, at=stamp())
    ident = now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    if not (base / "audit").resolve().is_relative_to(base.resolve()):
        raise ValueError("audit directory escapes state directory")
    write(base / "audit" / (ident + ".json"), record)


def set_role(project, args):
    with locked(project):
        base, config, state = load(project)
        old = copy.deepcopy(config)
        entry = config["roles"][args.role]
        if args.provider and args.provider != entry["provider"] and (not args.family or args.generation is None):
            raise ValueError("provider change requires --family and --generation")
        if args.family and args.family != entry["family"] and args.generation is None:
            raise ValueError("family change requires --generation")
        for field in ("model", "provider", "family", "generation"):
            value = getattr(args, field)
            if value is not None:
                entry[field] = value
        if args.effort:
            entry["reasoning_effort"] = args.effort
        entry["update_mode"] = args.update_mode
        validate(config)
        config["updated_at"] = stamp()
        ident = backup(base, old)
        audit(base, {"action": "set-role", "role": args.role, "backup": ident,
                     "before": old["roles"][args.role], "after": entry})
        write(base / "config.json", config)
        state["last_config_change_at"] = stamp()
        write(base / "state.json", state)
    return {"changed": args.role, "backup": ident, "runtime_applied": False}


def check_catalog(catalog, config):
    if catalog.get("fixture") is True:
        raise ValueError("synthetic example/fixture cannot update real configuration")
    if catalog.get("schema_version") != 1 or catalog.get("check_complete") is not True:
        raise ValueError("catalog must be a completed schema_version=1 check")
    if not recent(catalog.get("checked_at"), config["updates"]["evidence_max_age_days"]):
        raise ValueError("catalog evidence is stale or in the future")
    hosts = config["updates"]["allowed_source_hosts"]
    def official_sources(sources):
        if not isinstance(sources, list) or not sources:
            raise ValueError("check needs official source URLs")
        for source in sources:
            url = urlsplit(source)
            if url.scheme != "https" or url.hostname not in hosts or url.username or url.password or url.port not in (None, 443):
                raise ValueError("source URL is outside official allowlist")
    coverage = catalog.get("checked_families")
    if not isinstance(coverage, list):
        raise ValueError("catalog needs checked_families coverage")
    covered = set()
    for check in coverage:
        if not all(nonempty(check.get(key)) for key in ("provider", "family", "evidence")):
            raise ValueError("family check missing provider/family/evidence")
        official_sources(check.get("source_urls"))
        covered.add((check["provider"], check["family"]))
    required = {(x["provider"], x["family"]) for x in config["roles"].values() if x["update_mode"] == "auto_major"}
    if not required <= covered:
        raise ValueError("catalog does not cover every auto_major provider/family")
    candidates = catalog.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    for entry in candidates:
        for key in ("model", "provider", "family", "release_evidence", "availability_evidence"):
            if not nonempty(entry.get(key)):
                raise ValueError("candidate missing " + key)
        if type(entry.get("generation")) is not int or entry["generation"] < 1:
            raise ValueError("invalid candidate generation")
        if date(entry.get("released_at")) > now() + timedelta(minutes=5):
            raise ValueError("release date is in the future")
        official_sources(entry.get("source_urls"))
        if type(entry.get("available")) is not bool:
            raise ValueError("available must be an observed boolean")
        if not recent(entry.get("availability_checked_at"), config["updates"]["evidence_max_age_days"]):
            raise ValueError("availability evidence is stale")
        if entry.get("release_status") not in ("stable", "preview", "deprecated"):
            raise ValueError("invalid release status")
        efforts = entry.get("supported_efforts")
        if not isinstance(efforts, list) or not efforts or any(x not in EFFORTS for x in efforts):
            raise ValueError("invalid supported efforts")


def evaluation_gate(ev, role, candidate, config):
    if not ev or ev.get("fixture") is True:
        return "missing real paired evaluation"
    baseline = config["roles"][role]
    if ev.get("config_fingerprint") != fingerprint(config):
        return "evaluation baseline configuration has changed"
    if (ev.get("baseline_model"), ev.get("candidate_model"), ev.get("role")) != (baseline["model"], candidate["model"], role):
        return "evaluation model/role mismatch"
    if ev.get("reasoning_effort") != baseline["reasoning_effort"]:
        return "evaluation reasoning effort mismatch"
    if not recent(ev.get("evaluated_at"), config["updates"]["evidence_max_age_days"]):
        return "evaluation evidence is stale"
    if ev.get("runtime_models_verified") is not True or ev.get("equal_conditions") is not True:
        return "runtime identity or paired conditions unverified"
    if not nonempty(ev.get("suite_id")) or not nonempty(ev.get("verification_evidence")):
        return "missing suite/evidence"
    if ev.get("usage_metric") not in ("total_tokens", "api_usd", "subscription_units"):
        return "unknown or incompatible usage metric"
    cases = ev.get("cases")
    if not isinstance(cases, list) or len(cases) < config["updates"]["min_eval_cases"]:
        return "not enough paired cases"
    ids = []
    for case in cases:
        if not nonempty(case.get("id")) or not nonempty(case.get("check_evidence")):
            return "missing case ID/check evidence"
        ids.append(case["id"])
        for key in ("baseline_pass", "candidate_pass", "candidate_mandatory_pass"):
            if type(case.get(key)) is not bool:
                return "case results must be observed booleans"
        for key in ("baseline_usage", "candidate_usage"):
            if not number(case.get(key)) or case[key] < 0:
                return "usage is unmeasured or invalid"
    if len(set(ids)) != len(ids):
        return "duplicate evaluation cases"
    if any(not x["candidate_mandatory_pass"] for x in cases):
        return "candidate failed a mandatory check"
    baseline_quality = sum(x["baseline_pass"] for x in cases) / len(cases)
    candidate_quality = sum(x["candidate_pass"] for x in cases) / len(cases)
    if candidate_quality < config["updates"]["min_acceptance_rate"]:
        return "candidate acceptance rate below floor"
    if candidate_quality < baseline_quality - config["updates"]["max_quality_drop"]:
        return "candidate quality regressed"
    baseline_usage = sum(x["baseline_usage"] for x in cases)
    candidate_usage = sum(x["candidate_usage"] for x in cases)
    if baseline_usage <= 0 or candidate_usage / baseline_usage > config["updates"]["max_usage_ratio"]:
        return "candidate usage exceeds gate or baseline is unknown"
    return None


def refresh(project, catalog=None, evaluations=None, apply=False, failed=False):
    with locked(project):
        base, config, state = load(project)
        state["last_check_attempt_at"] = stamp()
        if failed:
            state["check_failed"] = True
            write(base / "state.json", state)
            return {"status": "check_failed", "configuration_preserved": True}
        try:
            check_catalog(catalog, config)
            evs = evaluations.get("evaluations", []) if evaluations else []
            if not isinstance(evs, list):
                raise ValueError("evaluations must be a list")
            pending, selected = [], {}
            for role in ROLES:
                old = config["roles"][role]
                if old["update_mode"] == "pinned":
                    continue
                matches = [x for x in catalog["candidates"] if x["provider"] == old["provider"]
                           and x["family"] == old["family"] and x["generation"] > old["generation"]
                           and x["model"] != old["model"]]
                matches.sort(key=lambda x: (x["generation"], date(x["released_at"])), reverse=True)
                for candidate in matches:
                    reason = None
                    if candidate["release_status"] != "stable":
                        reason = "candidate is not stable"
                    elif not candidate["available"]:
                        reason = "candidate unavailable to this account/runtime"
                    elif old["reasoning_effort"] not in candidate["supported_efforts"]:
                        reason = "configured effort unsupported by candidate"
                    ev = next((x for x in evs if x.get("role") == role and x.get("candidate_model") == candidate["model"]), None)
                    reason = reason or evaluation_gate(ev, role, candidate, config)
                    if reason:
                        pending.append({"role": role, "candidate": candidate, "reason": reason})
                    else:
                        selected[role] = (candidate, ev)
                        break
        except (ValueError, TypeError, KeyError, AttributeError):
            state["check_failed"] = True
            write(base / "state.json", state)
            raise
        state["check_failed"] = False
        state["last_successful_check_at"] = catalog["checked_at"]
        state["pending"] = pending
        state["eligible"] = {r: x[0]["model"] for r, x in selected.items()}
        ident = None
        if apply and selected:
            old_config = copy.deepcopy(config)
            ident = backup(base, old_config)
            for role, (candidate, _) in selected.items():
                config["roles"][role]["model"] = candidate["model"]
                config["roles"][role]["generation"] = candidate["generation"]
            config["updated_at"] = stamp()
            validate(config)
            audit(base, {"action": "major-update", "backup": ident,
                         "before_fingerprint": fingerprint(old_config), "after_fingerprint": fingerprint(config),
                         "receipt": catalog, "evaluations": [x[1] for x in selected.values()]})
            write(base / "config.json", config)
            state["last_config_change_at"] = stamp()
            state["last_evaluation_at"] = max(x[1]["evaluated_at"] for x in selected.values())
        write(base / "state.json", state)
    return {"applied": list(selected) if apply else [], "eligible": state["eligible"],
            "pending": pending, "backup": ident, "runtime_applied": False}


def generate(project):
    with locked(project):
        base, config, state = load(project)
        dest = root(project) / ".codex" / "agents"
        if not dest.resolve().is_relative_to(root(project)):
            raise ValueError("agent directory escapes project")
        contents = {}
        for role in ROLES:
            entry = config["roles"][role]
            filename = "cew-" + role.replace("_", "-") + ".toml"
            target = dest / filename
            if target.is_symlink():
                raise ValueError("refusing symlink agent: " + filename)
            if target.exists():
                expected = state.get("generated", {}).get(filename)
                if expected != hashlib.sha256(target.read_bytes()).hexdigest():
                    raise ValueError("agent modified outside helper; preserved: " + filename)
            data = {"name": "cew_" + role, "description": "Codex Efficient Workflow " + role,
                    "model": entry["model"], "model_reasoning_effort": entry["reasoning_effort"],
                    "developer_instructions": entry["instructions"]}
            if role in ("planner", "reviewer"):
                data["sandbox_mode"] = "read-only"
            # JSON basic strings are compatible with TOML basic strings for this text.
            body = "# Generated by codex-efficient-workflow; customize config.json, not this file.\n"
            body += "\n".join(k + " = " + json.dumps(v, ensure_ascii=False) for k, v in data.items()) + "\n"
            contents[filename] = body
        dest.mkdir(parents=True, exist_ok=True)
        for filename, body in contents.items():
            target = dest / filename
            temp = dest / (filename + ".tmp-" + uuid.uuid4().hex)
            try:
                temp.write_text(body, encoding="utf-8")
                temp.replace(target)
            finally:
                if temp.exists():
                    temp.unlink()
            state.setdefault("generated", {})[filename] = hashlib.sha256(body.encode()).hexdigest()
        state["generated_at"] = stamp()
        state["generated_config_fingerprint"] = fingerprint(config)
        write(base / "state.json", state)
    return {"generated": [str(dest / x) for x in contents], "runtime_loading_verified": False}


def rollback(project, ident):
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}", ident):
        raise ValueError("invalid backup ID")
    with locked(project):
        base, config, state = load(project)
        if not (base / "backups").resolve().is_relative_to(base.resolve()):
            raise ValueError("backup directory escapes state directory")
        restored = validate(read(base / "backups" / (ident + ".json")))
        recovery = backup(base, config)
        restored["updated_at"] = stamp()
        audit(base, {"action": "rollback", "restored_backup": ident, "backup": recovery})
        write(base / "config.json", restored)
        state["last_config_change_at"] = stamp()
        state["eligible"] = {}
        state["pending"] = []
        write(base / "state.json", state)
    return {"restored": ident, "recovery_backup": recovery, "runtime_applied": False}


def record_run(project, receipt):
    if receipt.get("schema_version") != 1 or not nonempty(receipt.get("task_id")):
        raise ValueError("run receipt needs schema_version=1 and opaque task_id")
    if not nonempty(receipt.get("verification_summary")):
        raise ValueError("run receipt needs verification_summary")
    if type(receipt.get("dispatches")) is not int or receipt["dispatches"] < 0:
        raise ValueError("invalid dispatch count")
    if receipt.get("status") not in ("done", "blocked", "needs_review"):
        raise ValueError("invalid task status")
    metric, usage = receipt.get("usage_metric"), receipt.get("usage")
    if metric is None:
        if usage is not None:
            raise ValueError("unknown usage must be null")
    elif metric not in ("total_tokens", "api_usd", "subscription_units") or not number(usage) or usage < 0:
        raise ValueError("invalid measured usage")
    with locked(project):
        base, config, state = load(project)
        audit(base, {"action": "run", "config_fingerprint": fingerprint(config), "receipt": receipt})
        state["last_run_at"] = stamp()
        write(base / "state.json", state)
    return {"recorded": receipt["task_id"], "measured_usage": usage, "metric": metric}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "status", "set-role", "generate", "refresh", "rollback", "record-run"):
        child = sub.add_parser(command)
        child.add_argument("--project", required=True, help="explicit project/workspace path")
        if command == "set-role":
            child.add_argument("--role", choices=ROLES, required=True)
            for name in ("model", "provider", "family"):
                child.add_argument("--" + name)
            child.add_argument("--generation", type=int)
            child.add_argument("--effort", choices=EFFORTS)
            child.add_argument("--update-mode", choices=("auto_major", "pinned"), default="pinned")
        elif command == "refresh":
            child.add_argument("--catalog")
            child.add_argument("--evaluations")
            child.add_argument("--apply", action="store_true")
            child.add_argument("--failed", action="store_true")
        elif command == "rollback":
            child.add_argument("--backup", required=True)
        elif command == "record-run":
            child.add_argument("--receipt", required=True)
    args = parser.parse_args()
    try:
        if args.command in ("init", "status", "generate"):
            result = globals()[args.command](args.project)
        elif args.command == "set-role":
            result = set_role(args.project, args)
        elif args.command == "rollback":
            result = rollback(args.project, args.backup)
        elif args.command == "record-run":
            result = record_run(args.project, read(args.receipt))
        else:
            if not args.failed and not args.catalog:
                parser.error("refresh requires --catalog or --failed")
            result = refresh(args.project, read(args.catalog) if args.catalog else None,
                             read(args.evaluations) if args.evaluations else None, args.apply, args.failed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
