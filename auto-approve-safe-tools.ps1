# Auto-approve safe tools for Claude Code PermissionRequest hook
# Workaround for VS Code extension bug #36884 (ignores Edit/Write allow rules)
$input = $input | Out-String
if ([string]::IsNullOrWhiteSpace($input)) { exit 0 }
try {
  $data = $input | ConvertFrom-Json
  $tool = $data.tool_name
  # Read-only tools + safe edit tools: always allow
  $safeTools = @("Read", "Glob", "Grep", "WebSearch", "WebFetch", "Edit", "Write", "NotebookEdit")
  if ($tool -in $safeTools) {
    $output = @{
      hookSpecificOutput = @{
        hookEventName = "PermissionRequest"
        permissionDecision = "allow"
      }
    }
    $output | ConvertTo-Json -Compress
  }
  # For all other tools: output nothing → normal permission prompt
} catch {
  exit 0
}
