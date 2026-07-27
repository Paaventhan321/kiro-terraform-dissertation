import json
import os
import subprocess
import requests
from datetime import datetime


REPAIR_AGENT_VERSION = "v9-2026-07-27-fixed-command-bracket-bug"

# Findings that require adding costly infrastructure to resolve (KMS keys,
# cross-region replication, Multi-AZ, enhanced monitoring roles, new
# attachment resources, etc). These are DELIBERATELY skipped rather than
# attempted, to avoid unpredictable AWS billing from automated repair.
# This list is based on real findings observed across Scenarios 1-5; add
# to it as new costly patterns are discovered in future scenarios.
COST_RESTRICTED_CHECK_IDS = {
    "CKV_AWS_145",   # RDS/S3 KMS encryption - $1/month/key + request fees
    "CKV_AWS_144",   # S3 cross-region replication - storage + transfer fees
    "CKV2_AWS_62",   # S3 event notifications - usually needs Lambda/SNS
    "CKV_AWS_157",   # RDS Multi-AZ - roughly doubles instance cost
    "CKV_AWS_118",   # RDS enhanced monitoring - needs new IAM role + cost
    "CKV2_AWS_5",    # SG not attached - typically needs a new EC2 instance
    "CKV_SECRET_6",  # Hardcoded secrets - proper fix needs Secrets Manager (~$0.40/mo)
}


def _extract_json(raw_text):
    """
    Some CI environments (e.g. GitHub Actions with step debug logging
    enabled) prefix subprocess stdout with a literal command-echo line
    like "[command]/path/to/terraform-bin show -json tfplan\\n" before
    the actual JSON output. Critically, "[command]" itself contains a
    literal '[' character, which previously confused a naive search for
    the first '{' or '[' - it would match the bracket inside
    "[command]" instead of the real JSON's opening bracket. This strips
    any line starting with "[command]" FIRST, then searches for the
    first '{' or '[' in what remains.
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
    return json.loads(cleaned_text[start:])


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

SECURITY FINDINGS TO FIX (cost-safe subset only):
{findings_text}
{error_section}
STRICT RULES:
1. Fix ALL security issues listed above
2. Do NOT use placeholder values
3. Use 10.0.0.0/8 for restricted SSH/network CIDR blocks
4. Do NOT add KMS key resources (aws_kms_key) - use default AWS-managed
   encryption (e.g. SSE-S3 AES256) instead, since customer-managed KMS
   keys have ongoing cost.
5. Do NOT add replication configuration (aws_s3_bucket_replication_configuration)
   - this requires a second bucket with ongoing storage/transfer costs.
6. Do NOT add event notification resources (aws_s3_bucket_notification),
   Lambda functions, or SNS topics.
7. Do NOT enable Multi-AZ on any RDS instance (multi_az) - this roughly
   doubles the instance's running cost.
8. Do NOT add enhanced monitoring (monitoring_interval / monitoring_role_arn)
   on RDS instances - this requires a new IAM role and adds cost.
9. Do NOT invent, add, or introduce ANY resource type, resource name, or
   service that is not already present in the TERRAFORM CODE shown above.
   Only modify arguments and blocks within resources that already exist.
10. LIFECYCLE RULE: if you add aws_s3_bucket_lifecycle_configuration, every
    single "rule" block MUST include either an empty "filter {{}}" block or
    a "prefix" argument. Never omit both.
11. LOGGING RULE: if you add a logging block referencing a target bucket,
    you MUST also declare that exact bucket resource in the same file, or
    skip the logging fix entirely rather than leave a dangling reference.
12. Do not remove or break any resource that is already working correctly
13. Every resource block must be syntactically complete with all required
    arguments per the current Terraform AWS provider schema. Double-check
    exact argument names - do not guess or approximate them.
14. Return ONLY valid HCL Terraform code
15. No explanations, no markdown, no backticks, no code fences
16. Be aware that some errors only appear at actual AWS deployment time,
    not at validate/plan time (e.g. an EC2 root_block_device volume_size
    smaller than the selected AMI's snapshot minimum). If a previous error
    mentions a required minimum size, increase the value accordingly.
17. Do NOT alter a description or comment to claim a fix was made unless
    the underlying value has genuinely changed to match.
18. For S3 lifecycle rules that need to "abort incomplete multipart
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
                    "resource must be declared in the same file. Never add "
                    "KMS keys, replication, Lambda, SNS, Multi-AZ, or "
                    "enhanced monitoring - these are explicitly out of scope. "
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

        validate_result = subprocess.run(
            ["terraform", "validate", "-json"],
            cwd=terraform_dir, capture_output=True, text=True, timeout=60
        )
        try:
            parsed = _extract_json(validate_result.stdout)
        except json.JSONDecodeError:
            if validate_result.returncode == 0:
                return True, None
            return False, validate_result.stdout + validate_result.stderr

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

        show_result = subprocess.run(
            ["terraform", "show", "-json", "tfplan"],
            cwd=terraform_dir, capture_output=True, text=True, timeout=60
        )
        if show_result.returncode != 0:
            print("DEBUG: terraform show -json tfplan failed.")
            print("STDOUT:", show_result.stdout)
            print("STDERR:", show_result.stderr)
            return None, (f"terraform show -json tfplan failed "
                           f"(returncode {show_result.returncode}):\n"
                           f"{show_result.stdout}\n{show_result.stderr}")
        if not show_result.stdout.strip():
            print("DEBUG: terraform show -json tfplan returned empty stdout. "
                  f"Full stderr was: {show_result.stderr}")
            return None, "terraform show -json tfplan produced no output."

        try:
            parsed = _extract_json(show_result.stdout)
        except json.JSONDecodeError as e:
            print(f"DEBUG: invalid JSON from show. Error: {e}")
            print(f"DEBUG: Raw stdout (first 2000 chars): {show_result.stdout[:2000]!r}")
            return None, f"terraform show -json tfplan produced invalid JSON: {e}"

        addresses = []
        for rc in parsed.get("resource_changes", []):
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
        result = subprocess.run(
            ["checkov", "-d", terraform_dir, "--output", "json",
             "--compact", "--quiet"],
            capture_output=True, text=True, timeout=180
        )
        try:
            parsed = _extract_json(result.stdout)
        except json.JSONDecodeError:
            print("Could not parse Checkov output as JSON:")
            print(result.stdout[-2000:])
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
    print("Starting Repair Agent (Cost-Effective Mode)...")
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
    print(f"Attemptable (cost-safe): {len(attempt_findings)}")
    print(f"Skipped (cost-risky, NOT attempted): {len(skipped_findings)}")
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
        print("No cost-safe issues to fix, and no correctness errors. "
              f"({len(skipped_findings)} cost-risky findings left untouched.)")
        save_metrics("kiro+repair-cost-safe", total, len(skipped_findings), 0, True)
        return

    terraform_code = original_code
    max_attempts = 3
    attempt = 0
    fixed = False
    previous_error = original_error if not original_is_valid else None

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
                  f"Checkov to verify the cost-safe findings are resolved...")
            still_failing = run_checkov("terraform")

            if still_failing is None:
                print("WARNING: Could not verify via Checkov. Treating as UNVERIFIED.")
                fixed = False
                previous_error = ("Previous attempt deployed successfully but "
                                   "could not be verified via Checkov.")
                terraform_code = fixed_code
                break

            unresolved = attempt_check_ids & still_failing
            final_unresolved_count = len(unresolved) + len(skipped_findings)
            if not unresolved:
                print(f"Attempt {attempt}: Checkov CONFIRMS all cost-safe "
                      f"findings resolved. ({len(skipped_findings)} cost-risky "
                      f"findings were deliberately left unresolved.)")
                fixed = True
            else:
                print(f"Attempt {attempt}: Checkov re-scan shows these "
                      f"cost-safe findings are STILL FAILING: {unresolved}")
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

    if not fixed:
        print(f"Repair Agent could not produce valid Terraform after "
              f"{max_attempts} attempts. Reverting to last known-good code.")
        with open("terraform/main.tf", "w") as f:
            f.write(original_code)

    after_count = len(skipped_findings) if fixed else (
        final_unresolved_count if final_unresolved_count is not None else total
    )

    save_metrics("kiro+repair-cost-safe", total, after_count, attempt, fixed)

    if not fixed:
        print("Human intervention required.")
    print(f"Note: {len(skipped_findings)} cost-risky findings were never "
          f"attempted by design and remain unresolved regardless of outcome.")


if __name__ == "__main__":
    main()