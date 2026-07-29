import json
import os
import subprocess
import requests
from datetime import datetime


REPAIR_AGENT_VERSION = "v13-2026-07-28-retain-best-partial-fix"

# Only cross-region replication is excluded. Unlike KMS keys, Secrets
# Manager, Multi-AZ, enhanced monitoring, or SG-attachment fixes -
# replication's cost (cross-region data transfer fees) is triggered the
# MOMENT data is replicated, not by how long resources exist. A fast
# `terraform destroy` in your pipeline does NOT undo this cost, and
# destroy can also be BLOCKED entirely if replicated objects/versions
# exist without force_destroy = true set. Every other cost-risky finding
# is now attempted, on the assumption that a destroy step runs promptly
# after each test (see build_prompt rules for cost-minimization guidance
# on each one, e.g. short KMS deletion windows, force_destroy flags).
COST_RESTRICTED_CHECK_IDS = {
    "CKV_AWS_144",   # S3 cross-region replication - transfer cost is
                     # incurred immediately on replication, not undone by
                     # fast teardown; destroy can also be blocked without
                     # force_destroy, leaving the 2nd-region bucket live.
}


def _extract_json(raw_text):
    """
    Fallback text-based extraction, kept as a safety net. Prefer
    run_json_command() below wherever possible, since it avoids this
    problem at the source instead of trying to clean up polluted text.
    """
    lines = raw_text.split("\n")
    filtered_lines = [line for line in lines if not line.startswith("[command]")]
    cleaned_text = "\n".join(filtered_lines)

    first_brace = cleaned_text.find("{")
    first_bracket = cleaned_text.find("[")
    candidates = [i for i in (first_brace, first_bracket) if i != -1]
    if not candidates:
        raise json.JSONDecodeError("No JSON object/array found in output", raw_text, 0)
    start = min(candidates)

    decoder = json.JSONDecoder()
    parsed_value, _end_index = decoder.raw_decode(cleaned_text[start:])
    return parsed_value


def run_json_command(command_list, cwd, timeout, temp_filename, temp_dir=None):
    """
    Runs a command and captures its stdout by redirecting it DIRECTLY TO
    A FILE at the OS level, instead of using subprocess capture_output.

    ROOT CAUSE THIS SOLVES: some CI environments (e.g. GitHub Actions
    with step debug logging enabled) inject extra text - like a literal
    "[command]/path/to/binary ...\\n" echo line, or output from other
    commands - into whatever capture_output=True collects as "stdout".
    This appears to be an artifact of how the CI runner's own logging
    wraps captured output, NOT something Terraform/Checkov themselves
    produce. Redirecting the child process's stdout straight to a file
    (via the `stdout=` file handle, not shell=True) captures ONLY that
    process's real output, sidestepping the runner's logging layer
    entirely - so no prefix-stripping or "find the first brace" guessing
    is needed at all.

    temp_dir: where to write the temp output file. Defaults to cwd, but
    should be set to a location OUTSIDE any directory being scanned by
    the command itself (e.g. Checkov scanning a Terraform directory
    could otherwise mistake its own not-yet-complete JSON output file
    for an IaC template).

    Returns (parsed_json_or_None, returncode, error_text_or_None).
    """
    write_dir = temp_dir if temp_dir is not None else cwd
    temp_path = os.path.join(write_dir, temp_filename)
    try:
        with open(temp_path, "w") as outfile:
            result = subprocess.run(
                command_list,
                cwd=cwd,
                stdout=outfile,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )

        with open(temp_path, "r") as f:
            file_content = f.read()

        try:
            os.remove(temp_path)
        except OSError:
            pass

        if not file_content.strip():
            return None, result.returncode, (
                f"Command produced no output on stdout. Stderr: {result.stderr}"
            )

        try:
            parsed = json.loads(file_content)
            return parsed, result.returncode, None
        except json.JSONDecodeError:
            # Fall back to the text-cleaning extractor in case something
            # unexpected still made it into the file.
            try:
                parsed = _extract_json(file_content)
                return parsed, result.returncode, None
            except json.JSONDecodeError as e:
                return None, result.returncode, (
                    f"Could not parse command output as JSON even after "
                    f"file-redirect capture: {e}. First 500 chars: "
                    f"{file_content[:500]!r}"
                )

    except subprocess.TimeoutExpired:
        return None, None, "Command timed out."
    except Exception as e:
        return None, None, f"Unexpected error running command: {e}"


def read_checkov_results():
    try:
        with open("results/checkov_results.json", "r") as f:
            return json.load(f)
    except:
        return {}


def read_terraform_code():
    with open("terraform/main.tf", "r") as f:
        return f.read()


def classify_failures(checkov_results):
    """
    Returns (classified, total, attempt_failures, skipped_failures).
    - classified: all findings, by severity (for logging/reporting only)
    - total: total count of all findings
    - attempt_failures: findings the Repair Agent will actually try to fix
    - skipped_failures: findings deliberately NOT attempted, due to cost risk
    """
    classified = {
        "CRITICAL": [],
        "HIGH": [],
        "MEDIUM": [],
        "LOW": []
    }

    if isinstance(checkov_results, list):
        blocks = checkov_results
    else:
        blocks = [checkov_results]

    all_failed = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        failed = block.get("results", {}).get("failed_checks", [])
        all_failed.extend(failed)

    attempt_list = []
    skipped_list = []

    for check in all_failed:
        severity = check.get("severity", "LOW")
        if severity is None or severity not in classified:
            severity = "LOW"
        entry = {
            "check_id": check.get("check_id"),
            "check_name": check.get("check_name"),
            "resource": check.get("resource")
        }
        classified[severity].append(entry)

        if entry["check_id"] in COST_RESTRICTED_CHECK_IDS:
            skipped_list.append(entry)
        else:
            attempt_list.append(entry)

    return classified, len(all_failed), attempt_list, skipped_list


def build_prompt(terraform_code, attempt_findings, previous_error=None):
    findings_text = json.dumps(attempt_findings, indent=2)

    error_section = ""
    if previous_error:
        error_section = f"""
THIS CODE CURRENTLY FAILS TERRAFORM VALIDATION WITH THIS EXACT ERROR:
{previous_error}

You MUST fix this specific error (this is a code correctness / syntax /
schema problem, separate from the security findings below). Do not repeat
this mistake. Fixing this error takes priority - the code must pass
`terraform validate` in addition to addressing the security findings.
"""

    return f"""
You are an AWS Terraform security expert.

The following Terraform code has security issues:

TERRAFORM CODE:
{terraform_code}

SECURITY FINDINGS TO FIX:
{findings_text}
{error_section}
STRICT RULES:
1. Fix ALL security issues listed above
2. Do NOT use placeholder values for anything EXCEPT credentials/secrets -
   see rule 4 below for the correct way to handle hardcoded secrets.
3. Use 10.0.0.0/8 for restricted SSH/network CIDR blocks unless the
   findings specify otherwise.
4. HARDCODED SECRETS: if a finding flags a hardcoded password/key/token
   (e.g. CKV_SECRET_6, CKV_AWS_45), do NOT invent a different hardcoded
   value. Instead, replace it with a Terraform variable reference (e.g.
   var.db_password), and add a matching "variable" block marked
   sensitive = true with NO default value. Do NOT create an
   aws_secretsmanager_secret resource unless a finding specifically
   requires it - the variable approach is the minimal, no-new-resource fix.
5. Do NOT add replication configuration (aws_s3_bucket_replication_configuration)
   under any circumstances - this is the one finding type excluded from
   automated repair, because its cost (cross-region data transfer) is
   incurred immediately on replication and is not undone by later
   destroying the resources.
6. KMS ENCRYPTION: if a finding requires KMS-based encryption
   (e.g. CKV_AWS_145), you MAY add an aws_kms_key resource. Use a minimal,
   safe key policy that grants the account root full access (to avoid a
   lockout scenario), and set deletion_window_in_days = 7 (the minimum
   allowed) to reduce how long the key remains billable after destroy.
7. RDS MULTI-AZ: if a finding requires Multi-AZ (e.g. CKV_AWS_157), you
   MAY set multi_az = true on the existing aws_db_instance. Do not create
   a separate/second database instance for this - it is a single argument
   on the existing resource.
8. RDS ENHANCED MONITORING: if a finding requires enhanced monitoring
   (e.g. CKV_AWS_118), you MAY add monitoring_interval (e.g. 60) and a
   minimal supporting aws_iam_role with the AWS-managed
   "AmazonRDSEnhancedMonitoringRole" policy attached, referenced via
   monitoring_role_arn. Do not add any other unrelated IAM permissions.
9. SECURITY GROUP ATTACHMENT: if a finding requires a security group to be
   attached to another resource (e.g. CKV2_AWS_5) and no suitable existing
   resource is present in the code, you MAY add a minimal
   aws_network_interface as the smallest possible attachment target,
   clearly commented as added solely to satisfy this finding. Do not add
   a full EC2 instance unless a network interface alone cannot satisfy
   the check.
10. EVENT NOTIFICATIONS: if a finding requires S3 event notifications
    (e.g. CKV2_AWS_62), you MAY add the minimum required target (e.g. a
    single aws_sns_topic) needed to satisfy aws_s3_bucket_notification -
    do not add Lambda functions unless the finding specifically requires
    Lambda as the target.
11. Do NOT invent, add, or introduce any resource that is not directly
    required to resolve one of the specific findings listed above. Every
    new resource you add must have a clear, traceable justification tied
    to a specific finding ID from the list above.
12. LIFECYCLE RULE: if you add aws_s3_bucket_lifecycle_configuration, every
    single "rule" block MUST include either an empty "filter {{}}" block or
    a "prefix" argument. Never omit both.
13. LOGGING RULE: if you add a logging block referencing a target bucket,
    you MUST also declare that exact bucket resource in the same file, or
    skip the logging fix entirely rather than leave a dangling reference.
14. If you add any resource that supports force_destroy (e.g. an S3
    bucket), set force_destroy = true so that automated test teardown via
    `terraform destroy` does not get blocked by leftover objects/versions.
15. Do not remove or break any resource that is already working correctly
16. Every resource block must be syntactically complete with all required
    arguments per the current Terraform AWS provider schema. Double-check
    exact argument names - do not guess or approximate them.
17. Return ONLY valid HCL Terraform code
18. No explanations, no markdown, no backticks, no code fences
19. Be aware that some errors only appear at actual AWS deployment time,
    not at validate/plan time (e.g. an EC2 root_block_device volume_size
    smaller than the selected AMI's snapshot minimum). If a previous error
    mentions a required minimum size, increase the value accordingly.
20. Do NOT alter a description or comment to claim a fix was made unless
    the underlying value has genuinely changed to match.
21. For S3 lifecycle rules that need to "abort incomplete multipart
    uploads", the CORRECT syntax is a NESTED BLOCK, never a flat
    argument. Use exactly this structure:

      rule {{
        id     = "some-rule-id"
        status = "Enabled"

        abort_incomplete_multipart_upload {{
          days_after_initiation = 7
        }}
      }}

    Do NOT use "days_after_incomplete", "days_after_incomplete_upload",
    or any other flat argument name for this - the Terraform AWS
    provider schema requires the nested "abort_incomplete_multipart_upload"
    block with a "days_after_initiation" argument inside it. If a
    previous error says an argument like this was "not expected here",
    that means you used a flat argument instead of this nested block -
    switch to the nested block form shown above, do not just rename the
    flat argument again.
22. KMS KEY REFERENCES: when referencing an aws_kms_key resource from
    another resource's encryption argument (e.g. kms_key_id on an
    aws_ebs_volume, aws_db_instance, or aws_s3_bucket encryption
    configuration), you MUST use the key's ARN attribute
    (aws_kms_key.NAME.arn), NEVER its raw ID attribute
    (aws_kms_key.NAME.id). Using .id instead of .arn will fail at
    deployment with "invalid ARN: arn: invalid prefix", because most
    kms_key_id/kms_key_arn arguments expect the full ARN format, not the
    bare key ID. Also, the correct argument name for setting a custom key
    policy on aws_kms_key is "policy", NOT "key_policy" - "key_policy" is
    not a valid argument for this resource.
"""


def call_repair_agent(prompt):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("No OpenAI API key found. Skipping repair.")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an AWS Terraform security expert. Return only "
                    "valid, complete HCL Terraform code. No markdown, no "
                    "backticks, no explanations. Every resource block must "
                    "have all required arguments and every referenced "
                    "resource must be declared in the same file. You MAY add "
                    "KMS keys, Multi-AZ, enhanced monitoring, event "
                    "notifications, or minimal attachment resources if a "
                    "specific finding requires them, using the minimum "
                    "resources necessary. Never add S3 replication "
                    "configuration - that is the one finding type explicitly "
                    "out of scope. For hardcoded secrets, use a Terraform "
                    "variable (sensitive = true, no default) instead of a "
                    "new hardcoded value or a Secrets Manager resource. "
                    "For S3 lifecycle 'abort incomplete multipart upload' "
                    "rules, always use the nested "
                    "abort_incomplete_multipart_upload { days_after_initiation "
                    "= N } block - never a flat argument name."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.1
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=body
    )

    if response.status_code == 200:
        content = response.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        return content
    else:
        print(f"API Error: {response.status_code}")
        print(response.text)
        return None


def validate_terraform(terraform_dir="terraform"):
    try:
        init_result = subprocess.run(
            ["terraform", "init", "-input=false", "-backend=false"],
            cwd=terraform_dir, capture_output=True, text=True, timeout=120
        )
        if init_result.returncode != 0:
            return False, f"terraform init failed:\n{init_result.stdout}\n{init_result.stderr}"

        parsed, returncode, error_text = run_json_command(
            ["terraform", "validate", "-json"],
            cwd=terraform_dir,
            timeout=60,
            temp_filename="_validate_output.json"
        )

        if parsed is None:
            if returncode == 0:
                return True, None
            return False, error_text or "terraform validate failed with no output."

        if parsed.get("valid") is True:
            return True, None

        diagnostics = parsed.get("diagnostics", [])
        error_lines = []
        for diag in diagnostics:
            summary = diag.get("summary", "")
            detail = diag.get("detail", "")
            range_info = diag.get("range", {})
            filename = range_info.get("filename", "")
            start_line = range_info.get("start", {}).get("line", "")
            error_lines.append(f"{filename}:{start_line}: {summary} - {detail}")

        return False, "\n".join(error_lines) if error_lines else \
            "terraform validate reported invalid, but no diagnostics were returned."

    except FileNotFoundError:
        return False, "terraform binary not found on PATH. Skipping validation."
    except subprocess.TimeoutExpired:
        return False, "terraform validate timed out."
    except Exception as e:
        return False, f"Unexpected error running terraform validate: {e}"


def get_planned_create_addresses(terraform_dir="terraform"):
    try:
        plan_result = subprocess.run(
            ["terraform", "plan", "-out=tfplan", "-input=false"],
            cwd=terraform_dir, capture_output=True, text=True, timeout=180
        )
        if plan_result.returncode != 0:
            print("DEBUG: terraform plan -out=tfplan failed.")
            print("STDOUT:", plan_result.stdout)
            print("STDERR:", plan_result.stderr)
            return None, plan_result.stdout + plan_result.stderr

        show_parsed, show_returncode, show_error = run_json_command(
            ["terraform", "show", "-json", "tfplan"],
            cwd=terraform_dir,
            timeout=60,
            temp_filename="_show_output.json"
        )

        if show_parsed is None:
            print("DEBUG: terraform show -json tfplan failed or produced "
                  "unparseable output.")
            print(f"DEBUG: {show_error}")
            return None, show_error or "terraform show -json tfplan produced no usable output."

        addresses = []
        for rc in show_parsed.get("resource_changes", []):
            actions = rc.get("change", {}).get("actions", [])
            if "create" in actions and "delete" not in actions:
                addresses.append(rc["address"])
        return addresses, None
    except Exception as e:
        return None, f"Could not determine planned resources: {e}"


def apply_terraform(terraform_dir="terraform"):
    try:
        planned_addresses, plan_error = get_planned_create_addresses(terraform_dir)
        if planned_addresses is None:
            return False, f"Could not plan before apply: {plan_error}"

        apply_result = subprocess.run(
            ["terraform", "apply", "-auto-approve", "tfplan"],
            cwd=terraform_dir, capture_output=True, text=True, timeout=300
        )

        if apply_result.returncode == 0:
            return True, None

        error_text = apply_result.stdout + apply_result.stderr

        if planned_addresses:
            print(f"Apply failed. Cleaning up ONLY the {len(planned_addresses)} "
                  f"resource(s) this attempt tried to create: {planned_addresses}")
            target_flags = []
            for addr in planned_addresses:
                target_flags += ["-target", addr]
            destroy_result = subprocess.run(
                ["terraform", "destroy", "-auto-approve"] + target_flags,
                cwd=terraform_dir, capture_output=True, text=True, timeout=300
            )
            if destroy_result.returncode != 0:
                print("WARNING: targeted cleanup failed. Manual cleanup may "
                      "be required to avoid orphaned AWS resources / cost.")
                print(destroy_result.stdout + destroy_result.stderr)
        else:
            print("No new resources were planned for creation - nothing to clean up.")

        return False, error_text

    except subprocess.TimeoutExpired:
        return False, "terraform apply or destroy timed out."
    except Exception as e:
        return False, f"Unexpected error running terraform apply: {e}"


def run_checkov(terraform_dir="terraform"):
    try:
        parsed, returncode, error_text = run_json_command(
            ["checkov", "-d", terraform_dir, "--output", "json",
             "--compact", "--quiet"],
            cwd=".",
            timeout=180,
            temp_filename="_checkov_output.json",
            temp_dir="."
        )

        if parsed is None:
            print("Could not parse Checkov output as JSON:")
            print(error_text)
            return None

        if isinstance(parsed, list):
            failed_ids = set()
            for block in parsed:
                for check in block.get("results", {}).get("failed_checks", []):
                    failed_ids.add(check.get("check_id"))
            return failed_ids
        else:
            failed_ids = set()
            for check in parsed.get("results", {}).get("failed_checks", []):
                failed_ids.add(check.get("check_id"))
            return failed_ids

    except FileNotFoundError:
        print("checkov binary not found on PATH. Cannot verify security fix.")
        return None
    except subprocess.TimeoutExpired:
        print("checkov scan timed out.")
        return None
    except Exception as e:
        print(f"Unexpected error running checkov: {e}")
        return None


def save_metrics(scenario, before_count, after_count, attempts, success):
    row = (f"{datetime.now().isoformat()},"
           f"{scenario},{before_count},"
           f"{after_count},{attempts},{success}\n")
    with open("results/metrics.csv", "a") as f:
        f.write(row)


import hashlib


def main():
    print("Starting Repair Agent (Unrestricted Mode - Replication Excluded)...")
    print(f"Repair Agent version: {REPAIR_AGENT_VERSION}")

    # Print a hash of THIS running file's own source code, so you can
    # compare it directly against the reference file and know for
    # certain whether the code actually executing matches what you
    # intended to deploy - no more guessing based on version strings
    # alone, which can be edited without changing the actual logic.
    try:
        with open(__file__, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        print(f"Repair Agent script SHA-256: {file_hash}")
    except Exception as e:
        print(f"Could not compute script hash: {e}")

    results = read_checkov_results()
    classified, total, attempt_findings, skipped_findings = classify_failures(results)

    print(f"Total issues found: {total}")
    print(f"Critical: {len(classified['CRITICAL'])}")
    print(f"High: {len(classified['HIGH'])}")
    print(f"Medium: {len(classified['MEDIUM'])}")
    print(f"Low: {len(classified['LOW'])}")
    print(f"Attemptable: {len(attempt_findings)}")
    print(f"Skipped (replication only, NOT attempted): {len(skipped_findings)}")
    if skipped_findings:
        print("The following findings were deliberately SKIPPED due to cost risk:")
        for f in skipped_findings:
            print(f"  - {f['check_id']}: {f['check_name']}")

    original_code = read_terraform_code()
    final_unresolved_count = None

    attempt_check_ids = set(f["check_id"] for f in attempt_findings if f.get("check_id"))

    print("Checking correctness of the original Kiro-generated code...")
    original_is_valid, original_error = validate_terraform("terraform")
    if original_is_valid:
        print("Original code passed terraform validate (no correctness errors).")
    else:
        print("Original code FAILED terraform validate:")
        print(original_error)

    if not attempt_findings and original_is_valid:
        print("No issues to fix, and no correctness errors. "
              f"({len(skipped_findings)} replication findings left untouched.)")
        save_metrics("kiro+repair-unrestricted", total, len(skipped_findings), 0, True)
        return

    terraform_code = original_code
    max_attempts = 3
    attempt = 0
    fixed = False
    previous_error = original_error if not original_is_valid else None

    # Track the BEST verified result across all attempts, so that if a
    # later attempt fails, we don't discard genuine, Checkov-verified
    # progress made by an earlier attempt. "Best" = the attempt with the
    # fewest still-failing findings, among attempts that actually passed
    # validate + apply + a real Checkov re-scan.
    best_code = None
    best_unresolved = None  # set of check_ids still failing, for the best attempt

    while attempt < max_attempts and not fixed:
        attempt += 1
        print(f"Repair attempt {attempt} of {max_attempts}...")
        prompt = build_prompt(terraform_code, attempt_findings, previous_error)
        fixed_code = call_repair_agent(prompt)

        if not fixed_code:
            print(f"Attempt {attempt}: Repair failed (no code returned).")
            continue

        with open("terraform/main.tf", "w") as f:
            f.write(fixed_code)

        print(f"Attempt {attempt}: Code written. Running terraform validate...")
        is_valid, error_text = validate_terraform("terraform")

        if is_valid:
            print(f"Attempt {attempt}: Code is syntactically VALID. "
                  f"Testing real deployment with terraform apply...")
            apply_success, apply_error = apply_terraform("terraform")

            if not apply_success:
                print(f"Attempt {attempt}: terraform apply FAILED:")
                print(apply_error)
                terraform_code = fixed_code
                previous_error = apply_error
                continue

            print(f"Attempt {attempt}: Deployed successfully. Re-running "
                  f"Checkov to verify the findings are resolved...")
            still_failing = run_checkov("terraform")

            if still_failing is None:
                print("WARNING: Could not verify via Checkov. Treating as UNVERIFIED.")
                previous_error = ("Previous attempt deployed successfully but "
                                   "could not be verified via Checkov.")
                terraform_code = fixed_code
                continue

            unresolved = attempt_check_ids & still_failing

            # Record this as the best result so far if it beats the
            # current best (fewer unresolved findings), regardless of
            # whether it's a full or partial success.
            if best_unresolved is None or len(unresolved) < len(best_unresolved):
                best_code = fixed_code
                best_unresolved = unresolved
                print(f"Attempt {attempt}: New best result - {len(unresolved)} "
                      f"of {len(attempt_check_ids)} attempted findings still "
                      f"failing (previously best: "
                      f"{'N/A' if best_unresolved is None else len(best_unresolved)}).")

            if not unresolved:
                print(f"Attempt {attempt}: Checkov CONFIRMS all attempted "
                      f"findings resolved. ({len(skipped_findings)} replication "
                      f"findings were deliberately left unresolved.)")
                fixed = True
            else:
                print(f"Attempt {attempt}: Checkov re-scan shows these "
                      f"attempted findings are STILL FAILING: {unresolved}")
                terraform_code = fixed_code
                previous_error = (
                    f"The code deployed successfully, but a Checkov re-scan "
                    f"shows these checks are STILL FAILING: "
                    f"{', '.join(unresolved)}. Make concrete changes to "
                    f"resolve these exact checks."
                )
        else:
            print(f"Attempt {attempt}: terraform validate FAILED:")
            print(error_text)
            terraform_code = fixed_code
            previous_error = error_text

    final_unresolved_count = None

    if fixed:
        # Full success on the final attempt - already deployed correctly.
        final_unresolved_count = len(skipped_findings)
    elif best_code is not None:
        # No attempt achieved full success, but at least one attempt made
        # genuine, VERIFIED partial progress. Re-deploy that best version
        # instead of discarding it, since it is strictly better than the
        # original Kiro code and has already been confirmed via Checkov.
        print(f"Repair Agent could not fully resolve all findings after "
              f"{max_attempts} attempts. However, an earlier attempt made "
              f"verified partial progress ({len(best_unresolved)} of "
              f"{len(attempt_check_ids)} attempted findings still failing, "
              f"vs {len(attempt_check_ids)} in the original code). "
              f"Re-deploying that best partial fix instead of reverting to "
              f"the original, fully-unresolved code.")
        with open("terraform/main.tf", "w") as f:
            f.write(best_code)
        redeploy_valid, redeploy_error = validate_terraform("terraform")
        if redeploy_valid:
            redeploy_success, redeploy_apply_error = apply_terraform("terraform")
            if redeploy_success:
                print("Best partial fix re-deployed and confirmed live.")
                final_unresolved_count = len(best_unresolved) + len(skipped_findings)
            else:
                print(f"WARNING: Could not re-deploy the best partial fix "
                      f"({redeploy_apply_error}). Falling back to reverting "
                      f"to the original code for safety.")
                with open("terraform/main.tf", "w") as f:
                    f.write(original_code)
                final_unresolved_count = total
        else:
            print(f"WARNING: Best partial fix no longer validates cleanly "
                  f"on re-check ({redeploy_error}). Falling back to "
                  f"reverting to the original code for safety.")
            with open("terraform/main.tf", "w") as f:
                f.write(original_code)
            final_unresolved_count = total
    else:
        # No attempt ever produced a verified result at all - revert to
        # the original code, same as before.
        print(f"Repair Agent could not produce any verified result after "
              f"{max_attempts} attempts. Reverting to last known-good code.")
        with open("terraform/main.tf", "w") as f:
            f.write(original_code)
        final_unresolved_count = total

    save_metrics("kiro+repair-unrestricted", total, final_unresolved_count, attempt, fixed)

    if not fixed:
        print("Human intervention may still be required for any remaining "
              "unresolved findings.")
    print(f"Note: {len(skipped_findings)} replication findings were never "
          f"attempted by design and remain unresolved regardless of outcome.")


if __name__ == "__main__":
    main()