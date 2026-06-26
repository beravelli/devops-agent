"""Kafka triage tools.

Reached by exec-ing the Kafka admin CLI into a broker pod. Covers the usual
Kafka incident questions: which topics exist, is a topic under-replicated, and
is a consumer group lagging.

Assumes the Apache Kafka script names (`kafka-*.sh`) are on PATH in the pod. For
Confluent images (no `.sh`), pass the matching `bin` value.
"""

from __future__ import annotations

from langchain_core.tools import tool

from .kexec import pod_exec


@tool
def kafka_list_topics(
    pod: str, bootstrap: str = "localhost:9092", namespace: str = "", container: str = "", bin: str = "kafka-topics.sh"
) -> str:
    """List Kafka topics (exec'd into a broker pod).

    Use to discover topic names before describing one.

    Args:
        pod: A Kafka broker pod to exec into.
        bootstrap: Bootstrap server, default localhost:9092 (the local broker).
        namespace: Pod namespace; empty uses the configured default.
        container: Container name if the pod has multiple.
        bin: CLI script name (kafka-topics.sh for Apache, kafka-topics for Confluent).
    """
    return pod_exec(pod, [bin, "--bootstrap-server", bootstrap, "--list"], namespace=namespace, container=container)


@tool
def kafka_describe_topic(
    pod: str, topic: str, bootstrap: str = "localhost:9092", namespace: str = "", container: str = "", bin: str = "kafka-topics.sh"
) -> str:
    """Describe a Kafka topic: partitions, replicas, leaders, and ISR.

    Use to find under-replicated partitions (ISR < replicas) or partitions with
    no leader — a common cause of produce/consume failures.

    Args:
        pod: A Kafka broker pod to exec into.
        topic: Topic name.
        bootstrap: Bootstrap server.
        namespace: Pod namespace.
        container: Container name.
        bin: CLI script name.
    """
    return pod_exec(
        pod,
        [bin, "--bootstrap-server", bootstrap, "--describe", "--topic", topic],
        namespace=namespace,
        container=container,
    )


@tool
def kafka_list_consumer_groups(
    pod: str, bootstrap: str = "localhost:9092", namespace: str = "", container: str = "", bin: str = "kafka-consumer-groups.sh"
) -> str:
    """List Kafka consumer groups.

    Args:
        pod: A Kafka broker pod to exec into.
        bootstrap: Bootstrap server.
        namespace: Pod namespace.
        container: Container name.
        bin: CLI script name (kafka-consumer-groups.sh / kafka-consumer-groups).
    """
    return pod_exec(
        pod, [bin, "--bootstrap-server", bootstrap, "--list"], namespace=namespace, container=container
    )


@tool
def kafka_consumer_group_lag(
    pod: str, group: str, bootstrap: str = "localhost:9092", namespace: str = "", container: str = "", bin: str = "kafka-consumer-groups.sh"
) -> str:
    """Describe a consumer group's per-partition offsets and LAG.

    The key tool for "consumers are falling behind": shows current offset, log-end
    offset, and lag per partition, plus the assigned consumer/host. Growing lag
    means consumers can't keep up (or are stuck).

    Args:
        pod: A Kafka broker pod to exec into.
        group: Consumer group id.
        bootstrap: Bootstrap server.
        namespace: Pod namespace.
        container: Container name.
        bin: CLI script name.
    """
    return pod_exec(
        pod,
        [bin, "--bootstrap-server", bootstrap, "--describe", "--group", group],
        namespace=namespace,
        container=container,
    )


KAFKA_TOOLS = [
    kafka_list_topics,
    kafka_describe_topic,
    kafka_list_consumer_groups,
    kafka_consumer_group_lag,
]
