"""Tests for the AWS tool formatting. The `_aws` CLI runner is stubbed so these
run without AWS credentials or the aws CLI."""

from __future__ import annotations

import devops_agent.tools.aws as aws


def _stub(monkeypatch, data):
    monkeypatch.setattr(aws, "_aws", lambda args: (True, data))


def test_tag_helper():
    tags = [{"Key": "Name", "Value": "kafka-1"}, {"Key": "env", "Value": "prod"}]
    assert aws._tag(tags, "Name") == "kafka-1"
    assert aws._tag(tags, "missing") == ""
    assert aws._tag(None, "Name") == ""


def test_describe_instances_formatting(monkeypatch):
    _stub(
        monkeypatch,
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-123",
                            "State": {"Name": "running"},
                            "InstanceType": "m5.large",
                            "Placement": {"AvailabilityZone": "us-east-1a"},
                            "PrivateIpAddress": "10.0.0.5",
                            "Tags": [{"Key": "Name", "Value": "kafka-1"}],
                        }
                    ]
                }
            ]
        },
    )
    out = aws.aws_ec2_describe_instances.invoke({"name_filter": "kafka-*"})
    assert "i-123" in out and "running" in out and "kafka-1" in out and "us-east-1a" in out


def test_instance_status_formatting(monkeypatch):
    _stub(
        monkeypatch,
        {
            "InstanceStatuses": [
                {
                    "InstanceId": "i-9",
                    "InstanceState": {"Name": "running"},
                    "SystemStatus": {"Status": "ok"},
                    "InstanceStatus": {"Status": "impaired"},
                }
            ]
        },
    )
    out = aws.aws_ec2_instance_status.invoke({})
    assert "i-9" in out and "impaired" in out


def test_security_groups_formatting(monkeypatch):
    _stub(
        monkeypatch,
        {
            "SecurityGroups": [
                {
                    "GroupId": "sg-1",
                    "GroupName": "kafka",
                    "VpcId": "vpc-1",
                    "IpPermissions": [
                        {"IpProtocol": "tcp", "FromPort": 9092, "ToPort": 9092, "IpRanges": [{"CidrIp": "10.0.0.0/16"}]}
                    ],
                }
            ]
        },
    )
    out = aws.aws_ec2_describe_security_groups.invoke({"group_ids": "sg-1"})
    assert "sg-1" in out and "9092" in out and "10.0.0.0/16" in out


def test_eks_describe_cluster_formatting(monkeypatch):
    _stub(
        monkeypatch,
        {"cluster": {"name": "prod", "status": "ACTIVE", "version": "1.29", "health": {"issues": []}}},
    )
    out = aws.aws_eks_describe_cluster.invoke({"name": "prod"})
    assert "ACTIVE" in out and "1.29" in out and "health_issues: none" in out


def test_eks_describe_nodegroup_health_issues(monkeypatch):
    _stub(
        monkeypatch,
        {
            "nodegroup": {
                "nodegroupName": "ng-1",
                "status": "DEGRADED",
                "scalingConfig": {"desiredSize": 3, "minSize": 1, "maxSize": 5},
                "health": {"issues": [{"code": "AsgInstanceLaunchFailures", "message": "capacity"}]},
            }
        },
    )
    out = aws.aws_eks_describe_nodegroup.invoke({"cluster": "prod", "nodegroup": "ng-1"})
    assert "DEGRADED" in out and "desired=3" in out and "AsgInstanceLaunchFailures" in out


def test_cloudwatch_alarms_formatting(monkeypatch):
    _stub(
        monkeypatch,
        {"MetricAlarms": [{"StateValue": "ALARM", "AlarmName": "rds-cpu", "Namespace": "AWS/RDS", "MetricName": "CPUUtilization", "StateReason": "high"}]},
    )
    out = aws.aws_cloudwatch_alarms.invoke({"state_value": "ALARM"})
    assert "rds-cpu" in out and "AWS/RDS" in out


def test_cloudwatch_alarms_validates_state():
    assert "must be one of" in aws.aws_cloudwatch_alarms.invoke({"state_value": "bogus"})
