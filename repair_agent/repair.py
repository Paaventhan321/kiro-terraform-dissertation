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


def build_prompt(terraform_code, failures):
    findings_text = json.dumps(failures, indent=2)
    return f"""
You are an AWS Terraform security expert.

The following Terraform code has security issues:

TERRAFORM CODE:
{terraform_code}

SECURITY FINDINGS TO FIX:
{findings_text}

STRICT RULES:
1. Fix ALL security issues listed above
2. Do NOT use placeholder values
3. Use 10.0.0.0/8 for restricted SSH CIDR
4. Do NOT add replication configuration
5. Do NOT add event notification resources
6. Do NOT add Lambda or SNS resources
7. Do NOT add KMS key resources
   instead use SSE-S3 AES256 encryption
8. For lifecycle add simple expiration rule only
9. For logging add simple logging block only
10. Every resource block must be complete
11. Return ONLY valid HCL Terraform code
12. No explanations no markdown no backticks
"""


def call_repair_agent(prompt):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("No OpenAI API key found.")
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
                "content": "You are an AWS Terraform security expert. Return only valid complete HCL Terraform code. No markdown. No backticks. No explanations. Every resource block must have all required arguments."
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
        return response.json()["choices"][0]["message"]["content"]
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
    print(f"Medium: {len(failures['MEDIUM'])}")
    print(f"Low: {len(failures['LOW'])}")

    if total == 0:
        print("No issues found. Already compliant.")
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
            fixed_code = fixed_code.strip()
            if fixed_code.startswith("```"):
                lines = fixed_code.split("\n")
                fixed_code = "\n".join(lines[1:-1])
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