import json
import os
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
    failed = checkov_results.get("results", {}).get("failed_checks", [])
    for check in failed:
        severity = check.get("severity", "LOW")
        classified[severity].append({
            "check_id": check.get("check_id"),
            "check_name": check.get("check_name"),
            "resource": check.get("resource")
        })
    return classified, len(failed)

def build_prompt(terraform_code, failures):
    findings_text = json.dumps(failures, indent=2)
    return f"""
You are an AWS Terraform security expert specialising in
CIS Benchmark and AWS security best practices.

The following Terraform code has security issues detected
by Checkov security scanner:

TERRAFORM CODE:
{terraform_code}

SECURITY FINDINGS:
{findings_text}

YOUR TASK:
1. Fix ALL security issues listed above
2. Do not change any functionality
3. Follow AWS security best practices
4. Return ONLY valid HCL Terraform code
5. No explanations, no markdown, no code blocks
"""

def call_repair_agent(prompt):
    # Gets API key from environment variable - never hardcode it
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("No API key found. Skipping repair.")
        return None

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json"
    }

    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body
    )

    if response.status_code == 200:
        return response.json()["content"][0]["text"]
    else:
        print(f"API Error: {response.status_code}")
        print(response.text)
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

    if total == 0:
        print("No issues found. Deployment ready.")
        save_metrics("kiro+repair", 0, 0, 0, True)
        return

    terraform_code = read_terraform_code()
    max_attempts = 3
    attempt = 0
    fixed = False

    while attempt < max_attempts and not fixed:
        attempt += 1
        print(f"Repair attempt {attempt} of {max_attempts}...")
        prompt = build_prompt(terraform_code, failures)
        fixed_code = call_repair_agent(prompt)

        if fixed_code:
            with open("terraform/main.tf", "w") as f:
                f.write(fixed_code)
            print(f"Attempt {attempt}: Code repaired.")
            fixed = True
        else:
            print(f"Attempt {attempt}: Repair failed.")

    save_metrics(
        "kiro+repair",
        total,
        0 if fixed else total,
        attempt,
        fixed
    )

    if not fixed:
        print("Repair Agent could not fix after 3 attempts.")
        print("Human intervention required.")

if __name__ == "__main__":
    main()
