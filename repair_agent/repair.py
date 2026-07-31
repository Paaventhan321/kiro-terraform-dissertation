import json
import os
import re
import subprocess
import requests
from datetime import datetime


REPAIR_AGENT_VERSION = "v23-2026-07-31-protect-lambda-env-codesigning-rule"

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

# Findings excluded for a DIFFERENT reason than cost: this pipeline has
# no mechanism to supply Terraform -var values (no TF_VAR_* env vars, no
# -var-file). The "correct" fix for hardcoded secrets is a sensitive
# variable with no default - but that makes `terraform plan` fail
# immediately with "No value for required variable" on every attempt,
# regardless of whether the fix is otherwise correct. Until the pipeline
# itself is extended with a secret-injection mechanism, these findings
# cannot be automatically verified, so they are excluded here.
PIPELINE_INCOMPATIBLE_CHECK_IDS = {
    "CKV_SECRET_2",
    "CKV_SECRET_6",
    "CKV_AWS_45",
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


def find_resource_block_range(lines, resource_type, resource_name):
    """
    Finds the (start, end) line indices (inclusive) of a resource block,
    using brace-depth counting to correctly handle nested blocks (e.g.
    tags {}, backup settings, etc.) inside the resource.
    """
    for i, line in enumerate(lines):
        match = re.match(
            rf'\s*resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*{{',
            line
        )
        if match:
            depth = line.count("{") - line.count("}")
            j = i
            while depth > 0 and j + 1 < len(lines):
                j += 1
                depth += lines[j].count("{") - lines[j].count("}")
            return i, j
    return None, None


def find_password_line(hcl_code):
    """
    Locates the first `password = "..."` line and the resource block it
    belongs to. Returns (original_line, resource_type, resource_name) or
    (None, None, None) if no password line is found.
    """
    lines = hcl_code.split("\n")
    password_line_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*password\s*=\s*"', line):
            password_line_idx = i
            break
    if password_line_idx is None:
        return None, None, None

    original_line = lines[password_line_idx]
    resource_type, resource_name = None, None
    for j in range(password_line_idx, -1, -1):
        match = re.match(
            r'\s*resource\s+"([a-zA-Z0-9_]+)"\s+"([a-zA-Z0-9_]+)"\s*{',
            lines[j]
        )
        if match:
            resource_type, resource_name = match.group(1), match.group(2)
            break
    return original_line, resource_type, resource_name


def enforce_correct_password(hcl_code, correct_password_line, resource_type, resource_name):
    """
    GUARANTEES exactly one, correct password assignment inside the
    given resource block, regardless of what the LLM did.

    Earlier approaches tried to prevent the LLM from ever seeing or
    reacting to the password field, but this failed in two different
    ways: (1) masking only the value still let the LLM try to replace
    it with a Terraform variable, and (2) removing the field entirely
    caused the LLM to independently reintroduce ITS OWN password
    argument (since aws_db_instance requires one), which then collided
    with the real line being reinserted, causing a duplicate-attribute
    error. This function takes a different approach: let the LLM see
    and do whatever it wants with the password field, then
    UNCONDITIONALLY strip every password line within that specific
    resource block afterward and insert exactly one correct line -
    guaranteeing correctness regardless of the LLM's behavior.
    """
    if resource_type is None or correct_password_line is None:
        return hcl_code

    lines = hcl_code.split("\n")
    start, end = find_resource_block_range(lines, resource_type, resource_name)
    if start is None:
        # Resource block not found (renamed beyond recognition) - leave
        # as-is; validate_terraform will report a clear missing-password
        # error that gets fed back into the next attempt.
        return hcl_code

    new_lines = []
    for idx, line in enumerate(lines):
        if start <= idx <= end and re.match(r'^\s*password\s*=', line):
            continue  # drop every password line found inside this block
        new_lines.append(line)

    new_lines.insert(start + 1, correct_password_line)
    return "\n".join(new_lines)


def find_environment_block(hcl_code):
    """
    Locates an aws_lambda_function's `environment { ... }` block (which
    typically contains hardcoded credentials as environment variables),
    using brace-depth counting to capture it exactly, including nested
    "variables = {...}" content. Returns (block_text, resource_type,
    resource_name) or (None, None, None) if not found.
    """
    lines = hcl_code.split("\n")
    for i, line in enumerate(lines):
        if re.match(r'\s*environment\s*{', line):
            depth = line.count("{") - line.count("}")
            j = i
            while depth > 0 and j + 1 < len(lines):
                j += 1
                depth += lines[j].count("{") - lines[j].count("}")
            block_text = "\n".join(lines[i:j + 1])

            resource_type, resource_name = None, None
            for k in range(i, -1, -1):
                match = re.match(
                    r'\s*resource\s+"([a-zA-Z0-9_]+)"\s+"([a-zA-Z0-9_]+)"\s*{',
                    lines[k]
                )
                if match:
                    resource_type, resource_name = match.group(1), match.group(2)
                    break
            return block_text, resource_type, resource_name
    return None, None, None


def enforce_correct_environment_block(fixed_code, original_block_text, resource_type, resource_name):
    """
    GENERALIZES the password-enforcement strategy (see
    enforce_correct_password) to Lambda's environment{variables={...}}
    block, where this scenario's hardcoded database credentials live.
    Regardless of what the LLM does to this block (leaves it, replaces
    values with var.xxx references, removes it entirely), this
    unconditionally restores the EXACT original block verbatim within
    the correct resource - removing the repeated failure where the LLM
    spent all 3 attempts trying to move credentials into Terraform
    variables instead of fixing the actual targeted findings.
    """
    if original_block_text is None or resource_type is None:
        return fixed_code

    lines = fixed_code.split("\n")
    start, end = find_resource_block_range(lines, resource_type, resource_name)
    if start is None:
        return fixed_code

    env_start = None
    for i in range(start, end + 1):
        if re.match(r'\s*environment\s*{', lines[i]):
            env_start = i
            break

    if env_start is None:
        # LLM removed the environment block entirely - reinsert the
        # original right after the resource declaration line.
        new_lines = lines[:start + 1] + [original_block_text] + lines[start + 1:]
        return "\n".join(new_lines)

    depth = lines[env_start].count("{") - lines[env_start].count("}")
    env_end = env_start
    while depth > 0 and env_end + 1 < len(lines):
        env_end += 1
        depth += lines[env_end].count("{") - lines[env_end].count("}")

    new_lines = lines[:env_start] + [original_block_text] + lines[env_end + 1:]
    return "\n".join(new_lines)


def check_forbidden_patterns(hcl_code, attempt_findings):
    """
    Programmatically inspects the LLM's returned HCL for known
    rule-violating patterns, INSTEAD OF just trusting the prompt
    instructions to be followed. This directly addresses a demonstrated
    limitation: the LLM has been observed ignoring explicit "do not do X"
    prompt rules (e.g. adding enhanced monitoring + a new IAM role in
    Scenario 5 despite being told not to). Rather than hoping the next
    attempt behaves, this rejects the violating code OUTRIGHT, before it
    is ever deployed to real AWS infrastructure - saving both the cost
    of deploying something that will just be reverted, and closing the
    gap between "instructed not to" and "actually did not".

    Returns a list of violation description strings (empty list = clean).
    """
    violations = []
    attempt_check_ids = set(f.get("check_id") for f in attempt_findings)
    code_lower = hcl_code.lower()

    # ALWAYS forbidden, regardless of findings - replication cost cannot
    # be undone by destroy, so this is never permitted under any ruleset.
    if "aws_s3_bucket_replication_configuration" in code_lower:
        violations.append(
            "Code contains aws_s3_bucket_replication_configuration, which "
            "is NEVER permitted under any circumstances (cross-region "
            "replication cost is incurred immediately and cannot be "
            "undone by destroying the resource afterward)."
        )

    # Enhanced monitoring / new IAM role for monitoring should only
    # appear if a monitoring-related finding is actually in scope.
    monitoring_findings_present = bool(
        attempt_check_ids & {"CKV_AWS_118"}
    )
    if not monitoring_findings_present:
        if "monitoring_interval" in code_lower or "monitoring_role_arn" in code_lower:
            violations.append(
                "Code adds RDS enhanced monitoring (monitoring_interval / "
                "monitoring_role_arn), but no monitoring-related finding "
                "(e.g. CKV_AWS_118) is in the current findings list for "
                "this scenario. This is not permitted - only add fixes "
                "for findings that are actually listed."
            )

    # Any "variable" block is ALWAYS forbidden now - secrets findings
    # are filtered out (see PIPELINE_INCOMPATIBLE_CHECK_IDS) before this
    # function is ever called, so there is never a legitimate reason for
    # the LLM to introduce one. A required variable with no default will
    # break `terraform plan` in this pipeline, since no -var values are
    # ever supplied.
    if "variable \"" in code_lower:
        violations.append(
            "Code introduces a Terraform 'variable' block. This is "
            "never permitted - this pipeline has no mechanism to supply "
            "-var values, so any required variable with no default will "
            "break every subsequent attempt regardless of the reason it "
            "was added."
        )

    # Also catch bare "var.xxx" references even without a declared
    # variable block - this is equally broken (an undeclared reference
    # error) and has been observed to occur even when no "variable"
    # block is present.
    if re.search(r'\bvar\.[a-zA-Z_][a-zA-Z0-9_]*', hcl_code):
        violations.append(
            "Code contains a 'var.xxx' reference. Do not reference any "
            "Terraform input variable, declared or not - this pipeline "
            "cannot supply variable values under any circumstances."
        )

    # KMS key resources should only appear if a KMS-related finding is
    # actually in scope.
    kms_findings_present = bool(
        attempt_check_ids & {"CKV_AWS_145", "CKV_AWS_16", "CKV_AWS_354"}
    )
    if not kms_findings_present and "aws_kms_key" in code_lower:
        violations.append(
            "Code adds an aws_kms_key resource, but no KMS-related "
            "finding is in the current findings list for this scenario. "
            "Only add a KMS key if a listed finding actually requires it."
        )

    # This exact typo has recurred twice (Scenario 5, Scenario 13) -
    # catch it programmatically as a hard backstop, not just a prompt
    # request, since the LLM has repeated it even after being told once.
    if "enable_cloudwatch_logs_exports" in code_lower and \
       "enabled_cloudwatch_logs_exports" not in code_lower:
        violations.append(
            "Code uses 'enable_cloudwatch_logs_exports' (missing the "
            "'d'), which is NOT a valid Terraform argument. The correct "
            "argument name is 'enabled_cloudwatch_logs_exports'. Fix "
            "the spelling exactly."
        )

    # Detect duplicate resource declarations - a new failure mode where
    # the LLM appends a second copy of an existing resource instead of
    # cleanly replacing it in-place (e.g. two "resource aws_db_instance
    # s13_kiro" blocks in the same file, causing a hard Terraform error).
    resource_declarations = re.findall(
        r'resource\s+"([a-zA-Z0-9_]+)"\s+"([a-zA-Z0-9_]+)"', hcl_code
    )
    seen = set()
    for res_type, res_name in resource_declarations:
        key = (res_type, res_name)
        if key in seen:
            violations.append(
                f"Code declares resource \"{res_type}\" \"{res_name}\" "
                f"more than once. You MUST return the corrected file as "
                f"a single, complete REPLACEMENT of the given code - do "
                f"not duplicate any existing resource block. Each "
                f"resource type+name combination must appear exactly once."
            )
        seen.add(key)

    return violations


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

        if entry["check_id"] in COST_RESTRICTED_CHECK_IDS or \
           entry["check_id"] in PIPELINE_INCOMPATIBLE_CHECK_IDS:
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
2. Do NOT use placeholder values for anything.
3. Use 10.0.0.0/8 for restricted SSH/network CIDR blocks unless the
   findings specify otherwise.
4. HARDCODED SECRETS: findings related to hardcoded secrets (e.g.
   CKV_SECRET_6, CKV_AWS_45) are filtered out before reaching you and
   will NOT appear in the findings list below - do not attempt to fix
   them even if you notice a hardcoded value elsewhere in the code. This
   is because the correct fix (a Terraform variable with no default)
   cannot be verified in this pipeline, which has no mechanism to supply
   variable values, and would break every subsequent attempt. If you
   somehow see a secrets-related finding in the list below, do NOT
   introduce any "variable" block to fix it - leave it unresolved.
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
23. EC2 IAM ATTACHMENT: an aws_instance's "iam_instance_profile" argument
    MUST reference an aws_iam_instance_profile resource's .name attribute
    (e.g. aws_iam_instance_profile.NAME.name) - NEVER an aws_iam_role's
    name or ARN directly. AWS requires an instance profile as a separate
    wrapper resource around a role; a role cannot be attached to an EC2
    instance directly. If you add an aws_iam_role to satisfy an
    "IAM role attached to EC2" finding, you MUST also add a matching
    aws_iam_instance_profile resource (with role = aws_iam_role.NAME.name)
    and reference THAT instance profile's .name on the instance - never
    the role's name.
24. DO NOT introduce any "variable" block, or any other new required
    input with no default value, under any circumstances. This pipeline
    has no mechanism to supply -var values, so any required variable
    with no default will cause `terraform plan` to fail immediately for
    every remaining attempt. Do not add, reference, or reason about
    credentials/passwords/variables at all - focus only on the findings
    actually listed above.
25. RDS LOGGING ARGUMENT NAME: the correct Terraform argument for
    enabling RDS log exports to CloudWatch is EXACTLY
    "enabled_cloudwatch_logs_exports" (plural "exports", "enabled" not
    "enable"). It is a list of strings, e.g. for postgres:
    enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
    for mysql:
    enabled_cloudwatch_logs_exports = ["error", "general", "slowquery"]
    Do NOT use "enable_cloudwatch_logs_exports" (missing the "d") or any
    other variation - this exact typo has caused repeated validation
    failures. Double-check the spelling character-by-character before
    returning your response.
26. VPC FLOW LOGS: if a finding requires VPC flow logs (e.g. CKV2_AWS_11,
    CKV2_AWS_19), use exactly this pattern, logging to S3 (simplest,
    avoids needing a CloudWatch log group + IAM role):

      resource "aws_flow_log" "NAME" {{
        vpc_id               = aws_vpc.EXISTING_VPC.id
        traffic_type         = "ALL"
        log_destination_type = "s3"
        log_destination      = aws_s3_bucket.NEW_LOG_BUCKET.arn
      }}

    You MUST also declare the aws_s3_bucket.NEW_LOG_BUCKET resource
    referenced above in the same file if it does not already exist -
    never leave this reference dangling.
27. CLOUDTRAIL: if a finding requires CloudTrail (e.g. for audit
    logging), use exactly this pattern:

      resource "aws_cloudtrail" "NAME" {{
        name                          = "some-name"
        s3_bucket_name                = aws_s3_bucket.EXISTING_OR_NEW_BUCKET.id
        include_global_service_events = true
        is_multi_region_trail         = true
        enable_log_file_validation    = true
      }}

    The S3 bucket referenced by s3_bucket_name MUST have a bucket policy
    granting cloudtrail.amazonaws.com permission to write to it (AWS
    requires this or CloudTrail creation will fail at apply time) - add
    an aws_s3_bucket_policy resource granting s3:GetBucketAcl and
    s3:PutObject to the Service principal "cloudtrail.amazonaws.com" for
    that specific bucket if one does not already exist.
28. IAM LEAST PRIVILEGE FOR SPECIFIC-RESOURCE ACCESS: if the ORIGINAL
    SPECIFICATION (not just the Checkov findings) describes access to a
    named, specific resource (e.g. "read from one specific DynamoDB
    table", "read from a specific S3 bucket"), and the given code
    instead uses a broad AWS-managed policy (e.g. AmazonDynamoDBReadOnlyAccess
    covering ALL tables), you may replace it with an inline
    aws_iam_role_policy scoped to only the specific resource's ARN, using
    minimal required actions (e.g. dynamodb:GetItem, dynamodb:Query,
    dynamodb:Scan for read-only DynamoDB access) - but ONLY if a
    corresponding Checkov finding is actually present in this scenario's
    findings list. Do not do this speculatively if no finding requires it.
29. Do NOT add an aws_kms_key resource, or any KMS-related argument,
    UNLESS a KMS-related finding (e.g. CKV_AWS_145, CKV_AWS_16 when it
    specifically requires KMS rather than default encryption) is
    actually present in the findings list above for THIS attempt. Adding
    a speculative KMS key "to be safe" when no finding requires it is
    NOT permitted and will be rejected before deployment.
30. LAMBDA CODE SIGNING: if a finding requires code-signing validation
    (e.g. CKV_AWS_272), the correct pattern uses a TOP-LEVEL resource,
    NOT a nested block inside aws_lambda_function:

      resource "aws_lambda_code_signing_config" "NAME" {{
        allowed_publishers {{
          signing_profile_version_arns = [aws_signer_signing_profile.NAME.version_arn]
        }}
      }}

    Then reference it on the Lambda function with:
      code_signing_config_arn = aws_lambda_code_signing_config.NAME.arn

    There is NO "code_signing_config" or "code_signing_policy" BLOCK
    inside aws_lambda_function - only the "code_signing_config_arn"
    ARGUMENT referencing the separate resource above. The argument
    inside allowed_publishers is "signing_profile_version_arns" (plural,
    a list) - NOT "signing_profile_version_arn" (singular).
31. NEVER attempt to fix hardcoded credentials (database passwords,
    hosts, ports, usernames, API keys, tokens) that appear inside a
    Lambda "environment {{ variables = {{...}} }}" block, under any
    circumstances, even if you notice them in the code and even if no
    explicit rule number is cited for a specific one. Leave that entire
    block completely untouched. This has caused repeated, wasted repair
    attempts - focus exclusively on the findings listed above and never
    reason about credential values.
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
            cwd=terraform_dir, capture_output=True, text=True, timeout=1500
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
                cwd=terraform_dir, capture_output=True, text=True, timeout=1500
            )
            if destroy_result.returncode != 0:
                print("WARNING: targeted cleanup failed. Manual cleanup may "
                      "be required to avoid orphaned AWS resources / cost.")
                print(destroy_result.stdout + destroy_result.stderr)
        else:
            print("No new resources were planned for creation - nothing to clean up.")

        return False, error_text

    except subprocess.TimeoutExpired:
        print("terraform apply timed out. IMPORTANT: the underlying AWS "
              "resources may have finished being created in the "
              "background even though this client gave up waiting. "
              "Attempting a best-effort cleanup of the planned resources...")
        try:
            if planned_addresses:
                target_flags = []
                for addr in planned_addresses:
                    target_flags += ["-target", addr]
                subprocess.run(
                    ["terraform", "destroy", "-auto-approve"] + target_flags,
                    cwd=terraform_dir, capture_output=True, text=True,
                    timeout=1500
                )
        except Exception as cleanup_error:
            print(f"WARNING: best-effort cleanup after timeout also failed "
                  f"or timed out ({cleanup_error}). The underlying AWS "
                  f"resource(s) may still exist and require MANUAL deletion "
                  f"to avoid ongoing cost and to unblock future attempts "
                  f"(e.g. a duplicate-identifier error on retry).")
        return False, ("terraform apply timed out - a best-effort cleanup "
                        "was attempted, but manually verify in the AWS "
                        "console that no orphaned resources remain, since "
                        "AWS may have finished creating them after this "
                        "client gave up waiting.")
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
    print(f"Skipped (replication + secrets, NOT attempted): {len(skipped_findings)}")
    if skipped_findings:
        print("The following findings were deliberately SKIPPED (replication "
              "due to cost risk; secrets findings due to pipeline "
              "incompatibility - no mechanism to supply variable values):")
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

        original_password_line, pw_resource_type, pw_resource_name = find_password_line(terraform_code)
        original_env_block, env_resource_type, env_resource_name = find_environment_block(terraform_code)
        prompt = build_prompt(terraform_code, attempt_findings, previous_error)
        fixed_code = call_repair_agent(prompt)

        if not fixed_code:
            print(f"Attempt {attempt}: Repair failed (no code returned).")
            continue

        fixed_code = enforce_correct_password(
            fixed_code, original_password_line, pw_resource_type, pw_resource_name
        )
        fixed_code = enforce_correct_environment_block(
            fixed_code, original_env_block, env_resource_type, env_resource_name
        )

        with open("terraform/main.tf", "w") as f:
            f.write(fixed_code)

        print(f"Attempt {attempt}: Code written. Running terraform validate...")
        is_valid, error_text = validate_terraform("terraform")

        if is_valid:
            # NEW: check the code for known rule violations BEFORE
            # spending time/cost on a real deployment. This is a hard,
            # programmatic check - not a prompt request - so it actually
            # enforces restrictions the LLM has been observed ignoring.
            violations = check_forbidden_patterns(fixed_code, attempt_findings)
            if violations:
                violation_text = "\n".join(f"- {v}" for v in violations)
                print(f"Attempt {attempt}: Code passed terraform validate, "
                      f"but VIOLATES enforced restrictions:\n{violation_text}")
                terraform_code = fixed_code
                previous_error = (
                    f"Your previous response violated these hard "
                    f"restrictions and was REJECTED before deployment:\n"
                    f"{violation_text}\nYou MUST remove these violations "
                    f"in your next response."
                )
                continue

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