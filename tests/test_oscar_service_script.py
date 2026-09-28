"""The OSCAR service script returns results, not logs, and keeps them.

Measured 2026-09-24 against real services (docs/demo-plan.md, step 4):

  * a synchronous call answered with the job's LOG, the result buried in it as
    one Python-repr line — line 221 of about 230 for the image classifier;
  * the classifier's bucket result was discarded, because DEEPaaS 2.6 colours
    the log line naming the result file and upstream's `cut` kept the escape
    code in the filename, so the `mv` that should save it found nothing.

Patch 0022 fixes both. These tests run the script's closing shell block with
bash, against a log coloured exactly as DEEPaaS 2.6 colours it, in both modes.
"""

import shutil
import string
import subprocess

import pytest
import yaml

COLOURED = "===================> New output is {path}\x1b[00m\n"
PLAIN = "===================> New output is {path}\n"


@pytest.fixture(scope="module")
def script(root, tmp_path_factory):
    src = root / "vendor" / "ai4-papi"
    if not src.is_dir():
        pytest.skip("vendor/ai4-papi not cloned")
    work = tmp_path_factory.mktemp("papi") / "ai4-papi"
    shutil.copytree(src, work, symlinks=True)
    for patch in sorted((root / "patches" / "ai4-papi").glob("*.patch")):
        subprocess.run(["git", "-C", str(work), "apply", str(patch)], check=True, capture_output=True)
    text = (work / "etc" / "oscar" / "service.yaml").read_text(encoding="utf-8")
    # Rendered the way PAPI renders it, so a $placeholder clash would show here.
    rendered = string.Template(text).safe_substitute(
        CLUSTER_ID="oscar", NAME="svc", IMAGE="img", CPU="1", MEMORY="1000",
        ALLOWED_USERS="[]", VO="vo.caios.ca", ENV_VARS="{}")
    return yaml.safe_load(rendered)["script"]


def _tail(script):
    """The shell that runs after the Python heredoc: where the answer is chosen."""
    return script.split("\nEOF\n", 1)[1]


def _run(script, tmp_path, file_name, log_line):
    result = tmp_path / "tmp-file-abcde.json"
    result.write_text('[{"name": "person", "confidence": 0.9}]')
    (tmp_path / "out").mkdir()
    (tmp_path / "service.log").write_text("some warning\n" + log_line.format(path=result) + "done\n")
    env = {"FILE_NAME": file_name, "OUTPUT_FILE": str(tmp_path / "out" / file_name), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["bash", "-c", _tail(script)], cwd=tmp_path, env=env,
                       capture_output=True, text=True, check=True)
    return r.stdout, sorted(p.name for p in (tmp_path / "out").iterdir())


@pytest.mark.parametrize("line", [COLOURED, PLAIN], ids=["deepaas-2.6-coloured", "plain"])
def test_a_synchronous_call_answers_with_the_result(script, tmp_path, line):
    stdout, _ = _run(script, tmp_path, "event-file-1234", line)
    assert stdout.strip() == '[{"name": "person", "confidence": 0.9}]'


@pytest.mark.parametrize("line", [COLOURED, PLAIN], ids=["deepaas-2.6-coloured", "plain"])
def test_a_bucket_upload_keeps_its_result(script, tmp_path, line):
    stdout, outputs = _run(script, tmp_path, "probe-1", line)
    assert outputs == ["probe-1.json", "probe-1.log"], outputs
    assert stdout == ""


def test_a_synchronous_failure_still_explains_itself(script, tmp_path):
    """No result file: the caller gets the log, which is where the reason is."""
    stdout, _ = _run(script, tmp_path, "event-file-1234", "Traceback: it broke\n")
    assert "Traceback: it broke" in stdout


def test_a_synchronous_answer_is_only_the_answer(script):
    """OSCAR answers a synchronous call with everything the script prints,
    stderr included — measured 2026-09-27, after moving two version lines to
    stderr left them opening every answer. So nothing is printed before the
    Python heredoc unless the call is an upload."""
    head = script.split("python >service.log", 1)[0]
    guard = 'if ! echo "$FILE_NAME" | grep -q event-file'
    assert guard in head
    unguarded = head.split(guard, 1)[0]
    assert "echo \"" not in unguarded, "something is printed before the guard"


def test_a_synchronous_result_is_written_outside_the_output_folder(script):
    """OSCAR answers a synchronous call with any file in TMP_OUTPUT_DIR,
    base64-encoded — measured 2026-09-27: `W1t7Im5hbWUiOi…` instead of
    `[[{"name": …`. Written elsewhere, the answer is the script's stdout: the
    result as plain JSON."""
    assert 'OUT_PATH = os.path.join("/tmp", os.path.basename(OUT_PATH))' in script


def test_users_are_shown_a_minio_address_they_can_open(root):
    """Patch 0023. The Inference detail page showed the in-cluster address
    OSCAR's jobs use — http://minio.minio.svc.cluster.local:9000 — found in a
    browser walk on 2026-09-28. PAPI now replaces it in both the listing and
    the detail with CAIOS_OSCAR_MINIO_URL, and compose passes that through."""
    patch = (root / "patches/ai4-papi/0023-oscar-minio-url-for-users.patch").read_text()
    assert patch.count("_minio_for_users(client_conf[\"minio_provider\"])") == 2
    assert 'os.getenv("CAIOS_OSCAR_MINIO_URL", "")' in patch
    compose = (root / "compose/docker-compose.yml").read_text()
    assert "CAIOS_OSCAR_MINIO_URL: ${CAIOS_OSCAR_MINIO_URL:-}" in compose
