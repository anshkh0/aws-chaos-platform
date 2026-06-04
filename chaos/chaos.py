#!/usr/bin/env python3
import argparse
import random
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError



# Helpers

def ts():
    """Current UTC timestamp as a readable string."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


def get_asg(autoscaling, asg_name):
    """Fetch the ASG description, or exit if it doesn't exist."""
    resp = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name]
    )
    groups = resp.get("AutoScalingGroups", [])
    if not groups:
        log(f"ERROR: Auto Scaling Group '{asg_name}' not found.")
        sys.exit(1)
    return groups[0]


def get_target_group_arn(asg):
    """Pull the target group ARN attached to the ASG."""
    arns = asg.get("TargetGroupARNs", [])
    if not arns:
        log("ERROR: ASG has no target group attached.")
        sys.exit(1)
    return arns[0]


def healthy_target_ids(elbv2, tg_arn):
    """Return the set of instance IDs currently 'healthy' in the target group."""
    resp = elbv2.describe_target_health(TargetGroupArn=tg_arn)
    healthy = set()
    for desc in resp["TargetHealthDescriptions"]:
        if desc["TargetHealth"]["State"] == "healthy":
            healthy.add(desc["Target"]["Id"])
    return healthy


def all_target_states(elbv2, tg_arn):
    """Return {instance_id: state} for every target (for richer logging)."""
    resp = elbv2.describe_target_health(TargetGroupArn=tg_arn)
    return {
        d["Target"]["Id"]: d["TargetHealth"]["State"]
        for d in resp["TargetHealthDescriptions"]
    }



# Core experiment


def run_experiment(region, asg_name, dry_run, poll_interval, timeout):
    """
    Run one chaos experiment:
      1. Snapshot the currently healthy targets.
      2. Terminate one at random.
      3. Poll until a NEW healthy instance joins (recovery).
    Returns RTO in seconds, or None on timeout / dry-run.
    """
    ec2 = boto3.client("ec2", region_name=region)
    autoscaling = boto3.client("autoscaling", region_name=region)
    elbv2 = boto3.client("elbv2", region_name=region)

    asg = get_asg(autoscaling, asg_name)
    tg_arn = get_target_group_arn(asg)

    log(f"Target group: {tg_arn.split(':')[-1]}")

    # --- 1. Snapshot healthy targets BEFORE chaos ---
    baseline_healthy = healthy_target_ids(elbv2, tg_arn)
    log(f"Healthy instances before chaos: {sorted(baseline_healthy) or 'NONE'}")

    if not baseline_healthy:
        log("ERROR: No healthy instances to kill. Is the system stable?")
        sys.exit(1)

    if len(baseline_healthy) < 2:
        log("WARNING: Only 1 healthy instance. Killing it means full downtime "
            "until the replacement boots (still a valid RTO test).")

    # --- 2. Pick a victim and terminate ---
    victim = random.choice(sorted(baseline_healthy))

    if dry_run:
        log(f"[DRY RUN] Would terminate: {victim}")
        log("[DRY RUN] No instance was harmed. Exiting.")
        return None

    log(f"CHAOS: Terminating instance {victim} ...")
    kill_time = time.monotonic()

    try:
        # Let the ASG handle replacement
        autoscaling.terminate_instance_in_auto_scaling_group(
            InstanceId=victim,
            ShouldDecrementDesiredCapacity=False,
        )
    except ClientError as e:
        log(f"ERROR terminating instance: {e}")
        sys.exit(1)

    log(f"Kill issued. Waiting for the system to heal "
        f"(poll every {poll_interval}s, timeout {timeout}s)...")

    #Poll until a NEW healthy instance appears
    remaining_baseline = baseline_healthy - {victim}
    deadline = kill_time + timeout

    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        states = all_target_states(elbv2, tg_arn)
        healthy_now = {i for i, s in states.items() if s == "healthy"}
        new_healthy = healthy_now - baseline_healthy

        elapsed = int(time.monotonic() - kill_time)
        state_summary = ", ".join(f"{i}={s}" for i, s in sorted(states.items()))
        log(f"  t+{elapsed:>3}s | {state_summary or 'no targets registered'}")

        # Recovery condition: a brand-new instance is healthy AND we're
        # back to or above the original healthy count.
        if new_healthy and len(healthy_now) >= len(baseline_healthy):
            rto = time.monotonic() - kill_time
            log("")
            log(f"RECOVERED. New healthy instance(s): {sorted(new_healthy)}")
            log(f"RTO = {rto:.1f} seconds")
            return rto

    log("")
    log(f"TIMEOUT after {timeout}s — system did not fully recover in time.")
    log("Check the ASG activity history and target group health manually.")
    return None


# Entry point

def main():
    parser = argparse.ArgumentParser(
        description="Chaos tool: kill a random app instance and measure RTO."
    )
    parser.add_argument("--region", default="us-east-2",
                        help="AWS region (default: us-east-2)")
    parser.add_argument("--asg", default="chaos-app-asg",
                        help="Auto Scaling Group name (default: chaos-app-asg)")
    parser.add_argument("--trials", type=int, default=1,
                        help="Number of experiments to run (default: 1)")
    parser.add_argument("--poll-interval", type=int, default=10,
                        help="Seconds between health polls (default: 10)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Max seconds to wait for recovery per trial "
                             "(default: 600)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the victim but terminate nothing.")
    args = parser.parse_args()

    log("=" * 60)
    log("AWS CHAOS ENGINEERING — INSTANCE FAILURE / RTO TEST")
    log("=" * 60)
    log(f"Region: {args.region} | ASG: {args.asg} | Trials: {args.trials}")
    log("")

    results = []
    for n in range(1, args.trials + 1):
        log(f"----- TRIAL {n}/{args.trials} -----")
        rto = run_experiment(
            region=args.region,
            asg_name=args.asg,
            dry_run=args.dry_run,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )
        if rto is not None:
            results.append(rto)
        log("")

        # Between trials, give the ASG a moment to fully settle before
        # the next kill to measure clean recoveries.
        if n < args.trials and not args.dry_run:
            settle = 30
            log(f"Letting the cluster settle for {settle}s before next trial...")
            time.sleep(settle)
            log("")

    #Summary
    if results:
        log("=" * 60)
        log("RESULTS")
        log("=" * 60)
        for i, r in enumerate(results, 1):
            log(f"  Trial {i}: RTO = {r:.1f}s")
        mean = sum(results) / len(results)
        log("")
        log(f"  Successful recoveries: {len(results)}/{args.trials}")
        log(f"  Mean RTO:  {mean:.1f}s")
        log(f"  Best RTO:  {min(results):.1f}s")
        log(f"  Worst RTO: {max(results):.1f}s")
        log("=" * 60)
    elif not args.dry_run:
        log("No successful recoveries recorded.")


if __name__ == "__main__":
    main()