#!/usr/bin/env python3
"""
Chaos tool — kills a random ECS task and measures RTO.

Supports two modes:
  1. Interactive: run manually with --trials N to test the cluster
  2. Pipeline:    run with --pipeline to exit non-zero if RTO exceeds
                  the threshold, triggering an automatic rollback in CI
"""
import argparse
import random
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


# ── Helpers ──────────────────────────────────────────────────

def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


def get_running_tasks(ecs, cluster, service):
    """Return a list of task ARNs currently running in the service."""
    resp = ecs.list_tasks(
        cluster=cluster,
        serviceName=service,
        desiredStatus="RUNNING"
    )
    return resp.get("taskArns", [])


def get_task_ips(ecs, cluster, task_arns):
    """Return {task_arn: private_ip} for each task."""
    if not task_arns:
        return {}
    resp = ecs.describe_tasks(cluster=cluster, tasks=task_arns)
    result = {}
    for task in resp.get("tasks", []):
        for attachment in task.get("attachments", []):
            for detail in attachment.get("details", []):
                if detail["name"] == "privateIPv4Address":
                    result[task["taskArn"]] = detail["value"]
    return result


def healthy_target_ips(elbv2, tg_arn):
    """Return set of IPs currently healthy in the ECS target group."""
    resp = elbv2.describe_target_health(TargetGroupArn=tg_arn)
    return {
        d["Target"]["Id"]
        for d in resp["TargetHealthDescriptions"]
        if d["TargetHealth"]["State"] == "healthy"
    }


def all_target_states(elbv2, tg_arn):
    """Return {ip: state} for every target in the group."""
    resp = elbv2.describe_target_health(TargetGroupArn=tg_arn)
    return {
        d["Target"]["Id"]: d["TargetHealth"]["State"]
        for d in resp["TargetHealthDescriptions"]
    }


# ── Core experiment ───────────────────────────────────────────

def run_experiment(region, cluster, service, tg_arn, dry_run, poll_interval, timeout):
    """
    1. Snapshot healthy task IPs before chaos.
    2. Stop one task at random.
    3. Poll until a NEW healthy IP appears and we're back to full count.
    Returns RTO in seconds, or None on timeout / dry-run.
    """
    ecs   = boto3.client("ecs",   region_name=region)
    elbv2 = boto3.client("elbv2", region_name=region)

    # ── 1. Snapshot healthy targets before chaos ──
    baseline_healthy = healthy_target_ips(elbv2, tg_arn)
    log(f"Healthy task IPs before chaos: {sorted(baseline_healthy) or 'NONE'}")

    if not baseline_healthy:
        log("ERROR: No healthy tasks. Is the service stable?")
        sys.exit(1)

    # ── 2. Pick a victim task and stop it ──
    running_tasks = get_running_tasks(ecs, cluster, service)
    if not running_tasks:
        log("ERROR: No running tasks found.")
        sys.exit(1)

    victim_arn = random.choice(running_tasks)
    victim_id  = victim_arn.split("/")[-1]

    if dry_run:
        log(f"[DRY RUN] Would stop task: {victim_id}")
        log("[DRY RUN] No task was harmed. Exiting.")
        return None

    log(f"CHAOS: Stopping task {victim_id} ...")
    kill_time = time.monotonic()

    try:
        ecs.stop_task(
            cluster=cluster,
            task=victim_arn,
            reason="Chaos engineering — automated RTO measurement"
        )
    except ClientError as e:
        log(f"ERROR stopping task: {e}")
        sys.exit(1)

    log(f"Kill issued. Waiting for recovery "
        f"(poll every {poll_interval}s, timeout {timeout}s)...")

    # ── 3. Poll until a NEW healthy task IP appears ──
    deadline = kill_time + timeout

    while time.monotonic() < deadline:
        time.sleep(poll_interval)

        states      = all_target_states(elbv2, tg_arn)
        healthy_now = {ip for ip, s in states.items() if s == "healthy"}
        new_healthy = healthy_now - baseline_healthy

        elapsed      = int(time.monotonic() - kill_time)
        state_summary = ", ".join(f"{ip}={s}" for ip, s in sorted(states.items()))
        log(f"  t+{elapsed:>3}s | {state_summary or 'no targets registered'}")

        # Recovery = a brand-new IP is healthy AND we're back to original count
        if new_healthy and len(healthy_now) >= len(baseline_healthy):
            rto = time.monotonic() - kill_time
            log("")
            log(f"RECOVERED. New healthy task IP(s): {sorted(new_healthy)}")
            log(f"RTO = {rto:.1f} seconds")
            return rto

    log(f"TIMEOUT after {timeout}s — system did not recover in time.")
    return None


# ── Entry point ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Chaos tool: stop a random ECS task and measure RTO."
    )
    parser.add_argument("--region",        default="us-east-2")
    parser.add_argument("--cluster",       default="chaos-platform-cluster")
    parser.add_argument("--service",       default="chaos-platform-service")
    parser.add_argument("--tg-arn",        required=True,
                        help="ECS target group ARN (from Terraform output)")
    parser.add_argument("--trials",        type=int, default=1)
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--timeout",       type=int, default=300)
    parser.add_argument("--dry-run",       action="store_true")

    # Pipeline mode: exit non-zero if mean RTO exceeds threshold.
    # GitHub Actions checks the exit code — non-zero triggers rollback.
    parser.add_argument("--pipeline",      action="store_true",
                        help="Exit non-zero if RTO exceeds threshold (for CI)")
    parser.add_argument("--rto-threshold", type=float, default=120.0,
                        help="Max acceptable mean RTO in seconds (default: 120)")

    args = parser.parse_args()

    log("=" * 60)
    log("CHAOS ENGINEERING — ECS TASK FAILURE / RTO TEST")
    log("=" * 60)
    log(f"Cluster: {args.cluster} | Service: {args.service} | Trials: {args.trials}")
    if args.pipeline:
        log(f"Pipeline mode: RTO threshold = {args.rto_threshold}s")
    log("")

    results = []
    for n in range(1, args.trials + 1):
        log(f"----- TRIAL {n}/{args.trials} -----")
        rto = run_experiment(
            region        = args.region,
            cluster       = args.cluster,
            service       = args.service,
            tg_arn        = args.tg_arn,
            dry_run       = args.dry_run,
            poll_interval = args.poll_interval,
            timeout       = args.timeout,
        )
        if rto is not None:
            results.append(rto)
        log("")

        if n < args.trials and not args.dry_run:
            settle = 30
            log(f"Letting the cluster settle for {settle}s ...")
            time.sleep(settle)
            log("")

    # ── Summary ──
    if results:
        log("=" * 60)
        log("RESULTS")
        log("=" * 60)
        for i, r in enumerate(results, 1):
            log(f"  Trial {i}: RTO = {r:.1f}s")
        mean = sum(results) / len(results)
        log("")
        log(f"  Successful recoveries : {len(results)}/{args.trials}")
        log(f"  Mean RTO              : {mean:.1f}s")
        log(f"  Best RTO              : {min(results):.1f}s")
        log(f"  Worst RTO             : {max(results):.1f}s")
        log("=" * 60)

        # Pipeline mode: fail the build if RTO is too slow
        if args.pipeline:
            if mean > args.rto_threshold:
                log("")
                log(f"PIPELINE FAIL: Mean RTO {mean:.1f}s exceeds threshold "
                    f"{args.rto_threshold}s — triggering rollback.")
                sys.exit(1)
            else:
                log("")
                log(f"PIPELINE PASS: Mean RTO {mean:.1f}s is within threshold "
                    f"{args.rto_threshold}s — deployment validated.")
                sys.exit(0)

    elif not args.dry_run:
        log("No successful recoveries recorded.")
        if args.pipeline:
            sys.exit(1)


if __name__ == "__main__":
    main()