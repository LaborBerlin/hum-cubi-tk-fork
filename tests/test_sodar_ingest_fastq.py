"""Tests for ``cubi_tk.sodar.ingest_fastq``.

We only run some smoke tests here.
"""

import os
from unittest import mock

import json
import pytest

from cubi_tk.__main__ import setup_argparse, main


def test_run_sodar_ingest_fastq_help(capsys):
    parser, subparsers = setup_argparse()
    with pytest.raises(SystemExit) as e:
        parser.parse_args(["sodar", "ingest-fastq", "--help"])

    assert e.value.code == 0

    res = capsys.readouterr()
    assert res.out
    assert not res.err


def test_run_sodar_ingest_fastq_nothing(capsys):
    parser, subparsers = setup_argparse()

    with pytest.raises(SystemExit) as e:
        parser.parse_args(["sodar", "ingest-fastq"])

    assert e.value.code == 2

    res = capsys.readouterr()
    assert not res.out
    assert res.err


def test_run_sodar_ingest_fastq_smoke_test(mocker, fs, requests_mock):
    # --- setup arguments
    irods_path = "/irods/dest"
    landing_zone_uuid = "landing_zone_uuid"
    dest_path = "target/folder/generic_file.fq.gz"
    fake_base_path = "/base/path"
    argv = [
        "--verbose",
        "sodar",
        "ingest-fastq",
        "--sodar-api-token",
        "XXXX",
        "--yes",
        "--remote-dir-pattern",
        dest_path,
        fake_base_path,
        landing_zone_uuid,
    ]

    parser, subparsers = setup_argparse()
    args = parser.parse_args(argv)

    # --- add test files
    fake_file_paths = []
    for member in ("sample1", "sample2", "sample3"):
        for ext in ("", ".md5"):
            fake_file_paths.append(
                "%s/%s/%s-N1-RNA1-RNA_seq1.fastq.gz%s" % (fake_base_path, member, member, ext)
            )
            fs.create_file(fake_file_paths[-1])
            fake_file_paths.append(
                "%s/%s/%s-N1-DNA1-WES1.fq.gz%s" % (fake_base_path, member, member, ext)
            )
            fs.create_file(fake_file_paths[-1])

    # Remove index's log MD5 file again so it is recreated.
    fs.remove(fake_file_paths[3])

    # --- mock modules
    mock_check_output = mock.mock_open()
    # mocker.patch("cubi_tk.sodar.ingest_fastq.check_output", mock_check_output)
    mocker.patch("cubi_tk.snappy.itransfer_common.check_output", mock_check_output)

    mock_check_call = mock.mock_open()
    mocker.patch("cubi_tk.snappy.itransfer_common.check_call", mock_check_call)

    # necessary because independent test fail
    mock_value = mock.mock_open()
    mocker.patch("cubi_tk.sodar.ingest_fastq.Value", mock_value)
    mocker.patch("cubi_tk.snappy.itransfer_common.Value", mock_value)

    # requests mock
    return_value = dict(
        assay="",
        config_data="",
        configuration="",
        date_modified="",
        description="",
        irods_path=irods_path,
        project="",
        sodar_uuid="",
        status="",
        status_info="",
        title="",
        user=dict(sodar_uuid="", username="", name="", email=""),
    )
    url = os.path.join(args.sodar_url, "landingzones", "api", "retrieve", args.destination)
    requests_mock.register_uri("GET", url, text=json.dumps(return_value))

    # --- run tests
    res = main(argv)

    assert not res

    assert fs.exists(fake_file_paths[3])

    assert mock_check_call.call_count == 1
    assert mock_check_call.call_args[0] == (["md5sum", "sample1-N1-DNA1-WES1.fq.gz"],)

    assert mock_check_output.call_count == len(fake_file_paths) * 3 * 5
    remote_path = os.path.join(irods_path, dest_path)
    for path in fake_file_paths:
        expected_mkdir_argv = ["imkdir", "-p", os.path.dirname(remote_path)]
        ext = ".md5" if path.split(".")[-1] == "md5" else ""
        expected_irsync_argv = ["irsync", "-a", "-K", path, ("i:%s" + ext) % remote_path]
        expected_ils_argv = ["ils", os.path.dirname(remote_path)]

        assert ((expected_mkdir_argv,),) in mock_check_output.call_args_list
        assert ((expected_irsync_argv,),) in mock_check_output.call_args_list
        assert ((expected_ils_argv,), {"stderr": -2}) in mock_check_output.call_args_list
