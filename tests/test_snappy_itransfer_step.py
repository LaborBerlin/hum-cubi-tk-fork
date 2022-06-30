"""Tests for ``cubi_tk.snappy.itransfer_step``.

We only run some smoke tests here.
"""

import os
from unittest import mock
from unittest.mock import ANY

import pytest
from pyfakefs import fake_filesystem

from .conftest import my_exists, my_get_sodar_info
from cubi_tk.__main__ import setup_argparse, main


def test_run_snappy_itransfer_ngs_mapping_help(capsys):
    parser, subparsers = setup_argparse()
    with pytest.raises(SystemExit) as e:
        parser.parse_args(["snappy", "itransfer-step", "--help"])

    assert e.value.code == 0

    res = capsys.readouterr()
    assert res.out
    assert not res.err


def test_run_snappy_itransfer_ngs_mapping_nostep(capsys):
    sodar_uuid = "466ab946-ce6a-4c78-9981-19b79e7bbe86"
    argv = ["snappy", "itransfer-step", "--sodar-api-token", "XXXX", sodar_uuid, "--tool", "bwa"]

    parser, subparsers = setup_argparse()

    res = main(argv)
    assert res == 1


def test_run_snappy_itransfer_ngs_mapping_nothing(capsys):
    parser, subparsers = setup_argparse()

    with pytest.raises(SystemExit) as e:
        parser.parse_args(["snappy", "itransfer-step"])

    assert e.value.code == 2

    res = capsys.readouterr()
    assert not res.out
    assert res.err


def test_run_snappy_itransfer_ngs_mapping_smoke_test(
    mocker, germline_trio_sheet_tsv, minimal_config
):
    fake_base_path = "/base/path"
    dest_path = "/irods/dest"
    sodar_uuid = "466ab946-ce6a-4c78-9981-19b79e7bbe86"
    argv = [
        "--verbose",
        "snappy",
        "itransfer-step",
        "--step",
        "ngs_mapping",
        "--base-path",
        fake_base_path,
        "--sodar-api-token",
        "XXXX",
        sodar_uuid,
        "--tool",
        "bwa",
    ]

    parser, subparsers = setup_argparse()
    args = parser.parse_args(argv)

    # Setup fake file system but only patch selected modules.  We cannot use the Patcher approach here as this would
    # break both biomedsheets and multiprocessing.
    fs = fake_filesystem.FakeFilesystem()

    fake_file_paths = []
    for member in ("index", "father", "mother"):
        for ext in ("", ".md5"):
            fake_file_paths.append(
                "%s/ngs_mapping/output/bwa.%s-N1-DNA1-WES1/out/%s-N1-DNA1-WES1.bam%s"
                % (fake_base_path, member, member, ext)
            )
            fs.create_file(fake_file_paths[-1])
            fake_file_paths.append(
                "%s/ngs_mapping/output/bwa.%s-N1-DNA1-WES1/log/bwa.%s-N1-DNA1-WES1.log%s"
                % (fake_base_path, member, member, ext)
            )
            fs.create_file(fake_file_paths[-1])

    # Create sample sheet in fake file system
    sample_sheet_path = fake_base_path + "/.snappy_pipeline/sheet.tsv"
    fs.create_file(sample_sheet_path, contents=germline_trio_sheet_tsv, create_missing_dirs=True)
    # Create config in fake file system
    config_path = fake_base_path + "/.snappy_pipeline/config.yaml"
    fs.create_file(config_path, contents=minimal_config, create_missing_dirs=True)

    # Print path to all created files
    print("\n".join(fake_file_paths + [sample_sheet_path, config_path]))

    # Remove index's log MD5 file again so it is recreated.
    fs.remove(fake_file_paths[3])

    # Set Mocker
    mocker.patch("pathlib.Path.exists", my_exists)
    mocker.patch(
        "cubi_tk.snappy.itransfer_common.SnappyItransferCommandBase.get_sodar_info",
        my_get_sodar_info,
    )

    fake_os = fake_filesystem.FakeOsModule(fs)
    mocker.patch("glob.os", fake_os)
    mocker.patch("cubi_tk.snappy.itransfer_common.os", fake_os)
    mocker.patch("cubi_tk.snappy.itransfer_step.os", fake_os)

    mock_check_output = mock.mock_open()
    mocker.patch("cubi_tk.snappy.itransfer_common.check_output", mock_check_output)

    fake_open = fake_filesystem.FakeFileOpen(fs)
    mocker.patch("cubi_tk.snappy.itransfer_common.open", fake_open)
    mocker.patch("cubi_tk.snappy.common.open", fake_open)

    mock_check_call = mock.mock_open()
    mocker.patch("cubi_tk.snappy.itransfer_common.check_call", mock_check_call)

    # Actually exercise code and perform test.
    res = main(argv)

    assert not res

    # We do not care about call order but simply test call count and then assert that all files are there which would
    # be equivalent of comparing sets of files.

    assert fs.exists(fake_file_paths[3])

    assert mock_check_call.call_count == 1
    mock_check_call.assert_called_once_with(
        ["md5sum", "bwa.index-N1-DNA1-WES1.log"],
        cwd=os.path.dirname(fake_file_paths[3]),
        stdout=ANY,
    )

    assert mock_check_output.call_count == len(fake_file_paths) * 3
    for path in fake_file_paths:
        mapper_index, rel_path = os.path.relpath(
            path, os.path.join(fake_base_path, "ngs_mapping/output")
        ).split("/", 1)
        _mapper, index = mapper_index.rsplit(".", 1)
        remote_path = os.path.join(dest_path, index, "ngs_mapping", args.remote_dir_date, rel_path)
        expected_mkdir_argv = ["imkdir", "-p", os.path.dirname(remote_path)]
        expected_irsync_argv = ["irsync", "-a", "-K", path, "i:%s" % remote_path]
        expected_ils_argv = ["ils", os.path.dirname(remote_path)]
        mock_check_output.assert_any_call(expected_mkdir_argv)
        mock_check_output.assert_any_call(expected_irsync_argv)
        mock_check_output.assert_any_call(expected_ils_argv, stderr=-2)