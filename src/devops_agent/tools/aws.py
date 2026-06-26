"""AWS triage tools (read-only `aws` CLI wrappers for EC2, EKS, CloudWatch).

The infrastructure layer beneath the workloads: is the EKS cluster/nodegroup
healthy, are the EC2 instances passing status checks, which CloudWatch alarms are
firing. Output is parsed from JSON and rendered compactly rather than dumped raw.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from ..config import get_settings
from ..safety import MutationBlocked, assert_readonly, format_result
from ..shell import run_command


def _aws(service_args: list[str]) -> tuple[bool, Any]:
    """Run a read-only aws command; return (ok, parsed_json) or (False, error_text)."""
    settings = get_settings()
    cmd = ["aws", *service_args, *settings.aws_global_flags(), "--output", "json"]
    try:
        assert_readonly(cmd, settings.allow_mutations)
    except MutationBlocked as exc:
        return False, f"BLOCKED: {exc}"
    result = run_command(cmd, timeout=settings.command_timeout)
    if result.returncode != 0 or result.timed_out:
        return False, format_result(result, settings.max_output_chars)
    try:
        return True, json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False, format_result(result, settings.max_output_chars)


def _tag(tags: list[dict[str, str]] | None, key: str) -> str:
    for t in tags or []:
        if t.get("Key") == key:
            return t.get("Value", "")
    return ""


# --- EC2 --------------------------------------------------------------------


@tool
def aws_ec2_describe_instances(name_filter: str = "", instance_ids: str = "") -> str:
    """Describe EC2 instances (state, type, AZ, IPs, Name tag).

    Use to check the hosts behind a service (Kafka/Redis/DB brokers on EC2, or
    EKS nodes) — find stopped/terminated/impaired instances.

    Args:
        name_filter: Match the Name tag (wildcards allowed), e.g. "kafka-*".
        instance_ids: Comma-separated instance IDs to scope to.
    """
    args = ["ec2", "describe-instances"]
    if instance_ids:
        args += ["--instance-ids", *[i.strip() for i in instance_ids.split(",") if i.strip()]]
    if name_filter:
        args += ["--filters", f"Name=tag:Name,Values={name_filter}"]
    ok, data = _aws(args)
    if not ok:
        return f"aws ec2 describe-instances failed:\n{data}"
    rows = []
    for res in data.get("Reservations", []):
        for inst in res.get("Instances", []):
            rows.append(
                f"{inst.get('InstanceId', '?')} [{inst.get('State', {}).get('Name', '?')}] "
                f"{inst.get('InstanceType', '?')} az={inst.get('Placement', {}).get('AvailabilityZone', '?')} "
                f"priv={inst.get('PrivateIpAddress', '-')} pub={inst.get('PublicIpAddress', '-')} "
                f"name={_tag(inst.get('Tags'), 'Name') or '-'}"
            )
    if not rows:
        return "No matching EC2 instances."
    return f"{len(rows)} instance(s):\n" + "\n".join(rows[:100])


@tool
def aws_ec2_instance_status(instance_ids: str = "") -> str:
    """Show EC2 instance status checks (system + instance reachability).

    Use to find instances that are running but failing status checks (impaired)
    — a common cause of a host that's "up" but not serving.

    Args:
        instance_ids: Comma-separated instance IDs; empty checks all instances.
    """
    args = ["ec2", "describe-instance-status", "--include-all-instances"]
    if instance_ids:
        args += ["--instance-ids", *[i.strip() for i in instance_ids.split(",") if i.strip()]]
    ok, data = _aws(args)
    if not ok:
        return f"aws ec2 describe-instance-status failed:\n{data}"
    rows = []
    for s in data.get("InstanceStatuses", []):
        rows.append(
            f"{s.get('InstanceId', '?')} state={s.get('InstanceState', {}).get('Name', '?')} "
            f"system={s.get('SystemStatus', {}).get('Status', '?')} "
            f"instance={s.get('InstanceStatus', {}).get('Status', '?')}"
        )
    if not rows:
        return "No instance statuses returned."
    return f"{len(rows)} instance(s):\n" + "\n".join(rows[:100])


@tool
def aws_ec2_describe_security_groups(group_ids: str = "", name_filter: str = "") -> str:
    """Describe EC2 security groups and a summary of their inbound rules.

    Use when connectivity is blocked — confirm a security group actually allows
    the port/CIDR the client needs (e.g. 9092 to Kafka, 6379 to Redis).

    Args:
        group_ids: Comma-separated security group IDs.
        name_filter: Match the group name (wildcards allowed).
    """
    args = ["ec2", "describe-security-groups"]
    if group_ids:
        args += ["--group-ids", *[g.strip() for g in group_ids.split(",") if g.strip()]]
    if name_filter:
        args += ["--filters", f"Name=group-name,Values={name_filter}"]
    ok, data = _aws(args)
    if not ok:
        return f"aws ec2 describe-security-groups failed:\n{data}"
    blocks = []
    for sg in data.get("SecurityGroups", []):
        ingress = []
        for perm in sg.get("IpPermissions", []):
            proto = perm.get("IpProtocol", "?")
            frm, to = perm.get("FromPort", "*"), perm.get("ToPort", "*")
            cidrs = ",".join(r.get("CidrIp", "") for r in perm.get("IpRanges", [])) or "-"
            ingress.append(f"    {proto} {frm}-{to} from {cidrs}")
        blocks.append(
            f"{sg.get('GroupId', '?')} ({sg.get('GroupName', '?')}) vpc={sg.get('VpcId', '?')}\n"
            + ("\n".join(ingress) if ingress else "    (no inbound rules)")
        )
    if not blocks:
        return "No matching security groups."
    return f"{len(blocks)} security group(s):\n" + "\n".join(blocks)


# --- EKS --------------------------------------------------------------------


@tool
def aws_eks_list_clusters() -> str:
    """List EKS clusters in the region.

    Use to discover the cluster names you can then describe.
    """
    ok, data = _aws(["eks", "list-clusters"])
    if not ok:
        return f"aws eks list-clusters failed:\n{data}"
    clusters = data.get("clusters", [])
    return f"{len(clusters)} cluster(s): " + (", ".join(clusters) if clusters else "(none)")


@tool
def aws_eks_describe_cluster(name: str) -> str:
    """Describe an EKS cluster (status, version, endpoint, health issues).

    Use to confirm the control plane is ACTIVE and healthy, and on the expected
    Kubernetes version, before digging into workloads.

    Args:
        name: The EKS cluster name.
    """
    ok, data = _aws(["eks", "describe-cluster", "--name", name])
    if not ok:
        return f"aws eks describe-cluster failed:\n{data}"
    c = data.get("cluster", {})
    issues = c.get("health", {}).get("issues", [])
    issue_str = "; ".join(i.get("message", str(i)) for i in issues) if issues else "none"
    return (
        f"cluster={c.get('name', '?')} status={c.get('status', '?')} "
        f"version={c.get('version', '?')} platform={c.get('platformVersion', '?')}\n"
        f"endpoint={c.get('endpoint', '?')}\nhealth_issues: {issue_str}"
    )


@tool
def aws_eks_list_nodegroups(cluster: str) -> str:
    """List the managed node groups of an EKS cluster.

    Args:
        cluster: The EKS cluster name.
    """
    ok, data = _aws(["eks", "list-nodegroups", "--cluster-name", cluster])
    if not ok:
        return f"aws eks list-nodegroups failed:\n{data}"
    ngs = data.get("nodegroups", [])
    return f"{len(ngs)} nodegroup(s): " + (", ".join(ngs) if ngs else "(none)")


@tool
def aws_eks_describe_nodegroup(cluster: str, nodegroup: str) -> str:
    """Describe an EKS managed node group (status, scaling, health issues).

    Use when pods are Pending or nodes are NotReady — check the node group's
    status, desired/min/max size, and any health issues (e.g. failed scaling,
    instance launch errors).

    Args:
        cluster: The EKS cluster name.
        nodegroup: The node group name.
    """
    ok, data = _aws(
        ["eks", "describe-nodegroup", "--cluster-name", cluster, "--nodegroup-name", nodegroup]
    )
    if not ok:
        return f"aws eks describe-nodegroup failed:\n{data}"
    ng = data.get("nodegroup", {})
    scaling = ng.get("scalingConfig", {})
    issues = ng.get("health", {}).get("issues", [])
    issue_str = "; ".join(f"{i.get('code', '?')}: {i.get('message', '')}" for i in issues) if issues else "none"
    return (
        f"nodegroup={ng.get('nodegroupName', '?')} status={ng.get('status', '?')} "
        f"capacity={ng.get('capacityType', '?')} types={ng.get('instanceTypes', [])}\n"
        f"scaling: desired={scaling.get('desiredSize', '?')} min={scaling.get('minSize', '?')} "
        f"max={scaling.get('maxSize', '?')}\nhealth_issues: {issue_str}"
    )


# --- CloudWatch -------------------------------------------------------------


@tool
def aws_cloudwatch_alarms(state_value: str = "ALARM") -> str:
    """List CloudWatch alarms in a given state.

    Use to see what AWS-side alarms are firing (RDS, ELB, EC2, custom metrics) —
    often the fastest pointer to an infrastructure-level problem.

    Args:
        state_value: ALARM (default), OK, or INSUFFICIENT_DATA.
    """
    state = state_value.upper()
    if state not in {"ALARM", "OK", "INSUFFICIENT_DATA"}:
        return "state_value must be one of ALARM, OK, INSUFFICIENT_DATA."
    ok, data = _aws(["cloudwatch", "describe-alarms", "--state-value", state])
    if not ok:
        return f"aws cloudwatch describe-alarms failed:\n{data}"
    rows = []
    for a in data.get("MetricAlarms", []):
        rows.append(
            f"[{a.get('StateValue', '?')}] {a.get('AlarmName', '?')} "
            f"({a.get('Namespace', '?')}/{a.get('MetricName', '?')}) "
            f"reason={(a.get('StateReason', '') or '')[:120]}"
        )
    for a in data.get("CompositeAlarms", []):
        rows.append(f"[{a.get('StateValue', '?')}] {a.get('AlarmName', '?')} (composite)")
    if not rows:
        return f"No alarms in state {state}."
    return f"{len(rows)} alarm(s) in {state}:\n" + "\n".join(rows[:100])


AWS_TOOLS = [
    aws_ec2_describe_instances,
    aws_ec2_instance_status,
    aws_ec2_describe_security_groups,
    aws_eks_list_clusters,
    aws_eks_describe_cluster,
    aws_eks_list_nodegroups,
    aws_eks_describe_nodegroup,
    aws_cloudwatch_alarms,
]
