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
YOUR PREVIOUS ATTEMPT FAILED TERRAFORM VALIDATION WITH THIS EXACT ERROR:
{previous_error}

You MUST fix this specific error in your next attempt, in addition to the
security findings below. Do not repeat the same mistake.
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

    if total == 0:
        print("No issues found. Already compliant.")
        save_metrics("kiro+repair", 0, 0, 0, True)
        return

    original_code = read_terraform_code()
    terraform_code = original_code
    max_attempts = 3
    attempt = 0
    fixed = False
    previous_error = None

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
            print(f"Attempt {attempt}: Code repaired and VALID.")
            fixed = True
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

    save_metrics(
        "kiro+repair",
        total,
        0 if fixed else total,
        attempt,
        fixed
    )

    if not fixed:
        print("Human intervention required.")


if __name__ == "__main__":
    main()