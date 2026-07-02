from pathlib import Path

from mariabackup_keeper.destinations.ssh import (
    build_rsync_argv,
    build_rsync_file_argv,
    build_ssh_argv,
)


def test_build_ssh_argv_includes_key_port_and_batch_mode():
    argv = build_ssh_argv(ssh_key="/etc/mbkeeper/id_ed25519", port=2222, ssh_options=())

    assert argv == [
        "ssh",
        "-i",
        "/etc/mbkeeper/id_ed25519",
        "-p",
        "2222",
        "-o",
        "BatchMode=yes",
    ]


def test_build_ssh_argv_appends_extra_ssh_options():
    argv = build_ssh_argv(
        ssh_key="/key",
        port=22,
        ssh_options=("-o", "StrictHostKeyChecking=accept-new"),
    )

    assert argv[-2:] == ["-o", "StrictHostKeyChecking=accept-new"]


def test_build_rsync_argv_includes_partial_and_delete():
    ssh_argv = ["ssh", "-i", "/key", "-p", "22", "-o", "BatchMode=yes"]

    argv = build_rsync_argv(
        rsync_path="rsync",
        ssh_argv=ssh_argv,
        src=Path("/work/full-1"),
        dst="backup@store:/backups/full-1.partial",
    )

    assert argv[0] == "rsync"
    assert "-a" in argv
    assert "--partial" in argv
    assert "--delete" in argv
    assert "-e" in argv
    assert argv[argv.index("-e") + 1] == "ssh -i /key -p 22 -o BatchMode=yes"
    assert argv[-2] == "/work/full-1/"
    assert argv[-1] == "backup@store:/backups/full-1.partial"


def test_build_rsync_argv_adds_bwlimit_when_set():
    argv = build_rsync_argv(
        rsync_path="rsync",
        ssh_argv=["ssh"],
        src=Path("/work/full-1"),
        dst="backup@store:/backups/full-1.partial",
        bwlimit_kbps=5000,
    )

    assert "--bwlimit=5000" in argv


def test_build_rsync_argv_omits_bwlimit_when_zero():
    argv = build_rsync_argv(
        rsync_path="rsync",
        ssh_argv=["ssh"],
        src=Path("/work/full-1"),
        dst="backup@store:/backups/full-1.partial",
        bwlimit_kbps=0,
    )

    assert not any(a.startswith("--bwlimit") for a in argv)


def test_build_rsync_argv_adds_exclude_patterns():
    argv = build_rsync_argv(
        rsync_path="rsync",
        ssh_argv=["ssh"],
        src=Path("/work/full-1"),
        dst="backup@store:/backups/full-1.partial",
        exclude=["meta.json"],
    )

    assert "--exclude=meta.json" in argv


def test_build_rsync_argv_uses_custom_rsync_path():
    argv = build_rsync_argv(
        rsync_path="/usr/local/bin/rsync",
        ssh_argv=["ssh"],
        src=Path("/work/full-1"),
        dst="dst",
    )

    assert argv[0] == "/usr/local/bin/rsync"


def test_build_rsync_file_argv_transfers_single_file_without_partial_or_delete():
    argv = build_rsync_file_argv(
        rsync_path="rsync",
        ssh_argv=["ssh", "-i", "/key"],
        src=Path("/work/full-1/meta.json"),
        dst="backup@store:/backups/full-1.partial/meta.json",
    )

    assert argv == [
        "rsync",
        "-a",
        "-e",
        "ssh -i /key",
        "/work/full-1/meta.json",
        "backup@store:/backups/full-1.partial/meta.json",
    ]
