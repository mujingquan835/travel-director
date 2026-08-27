from scanner.telemetry import ResourceMonitor, collect_environment


def test_environment_contains_capacity_without_private_paths() -> None:
    environment = collect_environment()

    assert environment["cpu_logical"] >= 1
    assert environment["memory_total_bytes"] > 0
    assert "executable_name" in environment
    assert "executable_path" not in environment


def test_resource_monitor_returns_bounded_summary() -> None:
    monitor = ResourceMonitor(interval_seconds=0.01).start()
    allocation = bytearray(1024 * 1024)
    allocation[0] = 1
    snapshot = monitor.stop()

    assert snapshot.sample_interval_ms == 10
    assert snapshot.sample_count >= 2
    assert snapshot.wall_ms >= 0
    assert snapshot.peak_process_tree_rss_bytes >= snapshot.final_process_rss_bytes
    assert snapshot.process_user_cpu_ms >= 0
    assert snapshot.process_system_cpu_ms >= 0
