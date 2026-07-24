import json
import os
import subprocess
import requests
from datetime import datetime


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
    classified = {
        "CRITICAL": [],
        "HIGH": [],
        "MEDIUM": [],
        "LOW": []
    }
    failed = checkov_results.get(
        "results", {}
    ).get("failed_checks", [])

    for check in failed:
        severity = check.get("severity", "LOW")
        if severity is None or severity not in classified:
            severity = "LOW"
        classified[severity].append({
            "check_id": check.get("check_id"),
            "check_name": check.get("check_name"),
            "resource": check.get("resource")
        })
    return classified, len(failed)


def build_prompt(terraform_code, failures, previous_error=None):
    findings_text = json.dumps(failures, indent=2)

    error_section = ""
    if previous_error:
        error_section = f"""
THIS CODE CURRENTLY FAILS TERRAFORM VALIDATION WITH THIS EXACT ERROR:
{previous_error}

You MUST fix this specific error (this is a code correctness / syntax /
schema problem, separate from the security findings below). Do not repeat
this mistake. Fixing this error takes priority — the code must pass
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
1. Fix ALL security issues listed above that you are able to fix under these rules
2. Do NOT use placeholder values
3. Use 10.0.0.0/8 for restricted SSH CIDR
4. Do NOT add replication configuration (aws_s3_bucket_replication_configuration)
5. Do NOT add event notification resources (aws_s3_bucket_notification)
6. Do NOT add Lambda or SNS resources
7. Do NOT add KMS key resources — instead use SSE-S3 AES256 encryption
8. LIFECYCLE RULE: if you add aws_s3_bucket_lifecycle_configuration, every
   single "rule" block MUST include either an empty "filter {{}}" block or a
   "prefix" argument. Never omit both. A rule with neither is invalid HCL.
9. LOGGING RULE: if you add a logging block that references a target bucket
   (e.g. target_bucket = aws_s3_bucket.X.id), you MUST also declare that
   exact resource "aws_s3_bucket" "X" {{ ... }} as a complete, valid resource
   in the same file. Never reference a bucket, key, role, or any other
   resource that you do not also fully declare in this same file. If you
   cannot safely add both the logging block AND its target bucket, skip the
   logging fix entirely rather than leaving a dangling reference.
10. Do not remove or break any resource that is already working correctly
11. Every resource block must be syntactically complete with all required
    arguments per the current Terraform AWS provider schema
12. Return ONLY valid HCL Terraform code
13. No explanations, no markdown, no backticks, no code fences
14. Be aware that some errors only appear at actual AWS deployment time,
    not at validate/plan time - for example, an EC2 root_block_device
    volume_size smaller than the selected AMI's underlying snapshot size
    will be rejected by AWS even though Terraform accepts it as valid
    syntax. If a previous error mentions a required minimum size, increase
    the relevant value accordingly rather than leaving it unchanged.
15. Do NOT invent, add, or introduce ANY resource type, resource name, or
    service that is not already present in the TERRAFORM CODE shown above.
    For example, if the given code only contains an aws_security_group and
    no aws_s3_bucket exists anywhere in it, you must NEVER add an
    aws_s3_bucket or any S3-related resource. Only modify arguments and
    blocks within the resources that already exist, or add narrowly-scoped
    supporting resources that are a direct, minimal requirement of an
    existing resource (e.g. a target bucket strictly required by a
    logging block you are adding to an existing aws_s3_bucket - never for
    unrelated resource types like security groups, EC2, or IAM).
16. If a fix requires changing a value like a restricted CIDR block and no
    specific range was provided in the findings, use 10.0.0.0/8 as the
    default restricted range consistently - do not invent a different or
    more specific CIDR without justification.
17. Do NOT alter a description or comment to claim a fix was made unless
    the underlying value has genuinely changed to match. Descriptions must
    accurately reflect the actual configuration.
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
                    "resource must be declared in the same file."
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
    """
    Runs `terraform init` (no backend, no interactivity) and
    `terraform validate -json` against the repaired code.
    Returns (is_valid: bool, error_text: str or None).
    """
    try:
        init_result = subprocess.run(
            ["terraform", "init", "-input=false", "-backend=false"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        if init_result.returncode != 0:
            return False, f"terraform init failed:\n{init_result.stdout}\n{init_result.stderr}"

        validate_result = subprocess.run(
            ["terraform", "validate", "-json"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        try:
            parsed = json.loads(validate_result.stdout)
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
    """
    Runs `terraform plan` and returns the list of resource addresses that
    would be newly CREATED by this plan (not updated, not destroyed, not
    already-existing). Used so that if apply fails partway through, we
    only clean up resources THIS attempt tried to create - never the
    entire state, which could include unrelated pre-existing
    infrastructure from previous successful runs or other scenarios.
    Returns (addresses: list or None, error_text: str or None).
    """
    try:
        plan_result = subprocess.run(
            ["terraform", "plan", "-out=tfplan", "-input=false"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            timeout=180
        )
        if plan_result.returncode != 0:
            return None, plan_result.stdout + plan_result.stderr

        show_result = subprocess.run(
            ["terraform", "show", "-json", "tfplan"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        if show_result.returncode != 0:
            return None, (f"terraform show -json tfplan failed "
                           f"(returncode {show_result.returncode}):\n"
                           f"{show_result.stdout}\n{show_result.stderr}")
        if not show_result.stdout.strip():
            return None, "terraform show -json tfplan produced no output."

        parsed = json.loads(show_result.stdout)
        addresses = []
        for rc in parsed.get("resource_changes", []):
            actions = rc.get("change", {}).get("actions", [])
            if "create" in actions and "delete" not in actions:
                addresses.append(rc["address"])
        return addresses, None
    except Exception as e:
        return None, f"Could not determine planned resources: {e}"


def apply_terraform(terraform_dir="terraform"):
    """
    Runs `terraform apply -auto-approve` against the current code.
    This actually creates real AWS resources. On failure, it cleans up
    ONLY the resources this attempt planned to create (via -target),
    never the whole state - protecting any unrelated, already-existing
    infrastructure from being destroyed by a failed repair attempt.
    Returns (is_success: bool, error_text: str or None).
    """
    try:
        planned_addresses, plan_error = get_planned_create_addresses(terraform_dir)
        if planned_addresses is None:
            return False, f"Could not plan before apply: {plan_error}"

        apply_result = subprocess.run(
            ["terraform", "apply", "-auto-approve", "tfplan"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        if apply_result.returncode == 0:
            return True, None

        error_text = apply_result.stdout + apply_result.stderr

        if planned_addresses:
            print(f"Apply failed. Cleaning up ONLY the {len(planned_addresses)} "
                  f"resource(s) this attempt tried to create (not the full "
                  f"state): {planned_addresses}")
            target_flags = []
            for addr in planned_addresses:
                target_flags += ["-target", addr]
            destroy_result = subprocess.run(
                ["terraform", "destroy", "-auto-approve"] + target_flags,
                cwd=terraform_dir,
                capture_output=True,
                text=True,
                timeout=300
            )
            if destroy_result.returncode != 0:
                print("WARNING: targeted cleanup failed. Manual cleanup may "
                      "be required to avoid orphaned AWS resources / "
                      "ongoing cost.")
                print(destroy_result.stdout + destroy_result.stderr)
        else:
            print("No new resources were planned for creation - nothing to "
                  "clean up.")

        return False, error_text

    except subprocess.TimeoutExpired:
        return False, "terraform apply or destroy timed out."
    except Exception as e:
        return False, f"Unexpected error running terraform apply: {e}"


def run_checkov(terraform_dir="terraform"):
    """
    Re-runs Checkov against the current code and returns the set of
    check_ids that FAILED, so we can compare against the original
    findings and know whether the repair actually worked - not just
    whether the code happened to validate and deploy.
    """
    try:
        result = subprocess.run(
            ["checkov", "-d", terraform_dir, "--output", "json",
             "--compact", "--quiet"],
            capture_output=True,
            text=True,
            timeout=180
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            print("Could not parse Checkov output as JSON:")
            print(result.stdout[-2000:])
            return None  # unknown - caller should treat cautiously

        # Checkov's JSON output can be a list (multiple frameworks) or a
        # single dict depending on version/flags - handle both.
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


def save_metrics(scenario, before_count, after_count,
                  attempts, success):
    row = (f"{datetime.now().isoformat()},"
           f"{scenario},{before_count},"
           f"{after_count},{attempts},{success}\n")
    with open("results/metrics.csv", "a") as f:
        f.write(row)


def main():
    print("Starting Repair Agent...")
    results = read_checkov_results()
    failures, total = classify_failures(results)

    print(f"Total issues found: {total}")
    print(f"Critical: {len(failures['CRITICAL'])}")
    print(f"High: {len(failures['HIGH'])}")
    print(f"Medium: {len(failures['MEDIUM'])}")
    print(f"Low: {len(failures['LOW'])}")

    original_code = read_terraform_code()
    final_unresolved_count = None  # tracked precisely once we know

    # Collect the exact check_ids we need to resolve, so we can verify
    # against them specifically after repair, not just trust the model.
    original_failing_check_ids = set()
    for severity_list in failures.values():
        for check in severity_list:
            if check.get("check_id"):
                original_failing_check_ids.add(check["check_id"])

    # NEW: check whether Kiro's OWN code is even valid Terraform,
    # independent of Checkov security findings. This catches syntax /
    # schema mistakes Kiro itself introduced (e.g. Scenario 10 style
    # broken HCL) that Checkov would never report, since Checkov only
    # scans for security misconfigurations, not correctness.
    print("Checking correctness of the original Kiro-generated code...")
    original_is_valid, original_error = validate_terraform("terraform")

    if original_is_valid:
        print("Original code passed terraform validate (no correctness errors).")
    else:
        print("Original code FAILED terraform validate:")
        print(original_error)

    if total == 0 and original_is_valid:
        print("No security issues and no correctness errors. Already compliant.")
        save_metrics("kiro+repair", 0, 0, 0, True)
        return

    if total == 0 and not original_is_valid:
        print("No security issues found, but Kiro's code has a correctness "
              "error. Repair Agent will attempt a correctness-only fix.")

    terraform_code = original_code
    max_attempts = 3
    attempt = 0
    fixed = False
    # Seed the first prompt with the correctness error (if any) so the very
    # first repair attempt already knows about syntax/schema problems, not
    # just security findings.
    previous_error = original_error if not original_is_valid else None

    while attempt < max_attempts and not fixed:
        attempt += 1
        print(f"Repair attempt {attempt} of {max_attempts}...")
        prompt = build_prompt(terraform_code, failures, previous_error)
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
                print(f"Attempt {attempt}: terraform apply FAILED "
                      f"(passed validate, but rejected by AWS API):")
                print(apply_error)
                terraform_code = fixed_code
                previous_error = apply_error
                continue

            # NEW: apply succeeding is NOT enough - actually re-scan with
            # Checkov and confirm the ORIGINAL findings are resolved.
            # A successful deploy does not prove the security content of
            # the fix is correct (e.g. an EC2 instance without detailed
            # monitoring or EBS optimization still deploys fine).
            print(f"Attempt {attempt}: Deployed successfully. Re-running "
                  f"Checkov to verify the original findings are actually "
                  f"resolved...")
            still_failing = run_checkov("terraform")

            if still_failing is None:
                print("WARNING: Could not verify via Checkov (scan failed "
                      "or unavailable). Treating repair as UNVERIFIED, not "
                      "confirmed fixed.")
                fixed = False
                previous_error = ("Previous attempt deployed successfully "
                                   "but security findings could not be "
                                   "independently verified via Checkov.")
                terraform_code = fixed_code
                break  # don't burn remaining attempts on an unverifiable loop

            unresolved = original_failing_check_ids & still_failing
            final_unresolved_count = len(unresolved)
            if not unresolved:
                print(f"Attempt {attempt}: Checkov CONFIRMS all original "
                      f"findings resolved. Code repaired AND verified.")
                fixed = True
            else:
                print(f"Attempt {attempt}: Checkov re-scan shows these "
                      f"findings are STILL FAILING (not actually fixed): "
                      f"{unresolved}")
                terraform_code = fixed_code
                previous_error = (
                    f"The code deployed successfully, but a Checkov "
                    f"re-scan shows these specific checks are STILL "
                    f"FAILING and were NOT actually fixed: "
                    f"{', '.join(unresolved)}. You must make concrete "
                    f"changes (e.g. add missing arguments) to resolve "
                    f"these exact checks, not just leave the code "
                    f"unchanged from a version that already 'validated'."
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

    # If we never got as far as a Checkov re-scan (e.g. validate/apply
    # kept failing every attempt), we genuinely don't know how many
    # findings would remain, so fall back to the honest worst case: total.
    after_count = 0 if fixed else (
        final_unresolved_count if final_unresolved_count is not None else total
    )

    save_metrics(
        "kiro+repair",
        total,
        after_count,
        attempt,
        fixed
    )

    if not fixed:
        print("Human intervention required.")


if __name__ == "__main__":
    main()