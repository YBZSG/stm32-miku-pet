param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('idle','working','waiting','failed')]
    [string]$State,
    [string]$StateFile = "$PSScriptRoot\..\runtime\codex_pet_state.txt"
)

$ErrorActionPreference = 'SilentlyContinue'
# Codex sends one JSON object on stdin. Drain it so the hook always completes.
$inputJson = [Console]::In.ReadToEnd()
$directory = Split-Path -Parent $StateFile
if (-not (Test-Path -LiteralPath $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
[IO.File]::WriteAllText($StateFile, $State, [Text.Encoding]::ASCII)
if ($State -eq 'working' -and -not [string]::IsNullOrWhiteSpace($inputJson)) {
    try {
        $hookInput = $inputJson | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace($hookInput.prompt)) {
            $title = (($hookInput.prompt -replace '[\r\n\t]+', ' ') -replace '\s+', ' ').Trim()
            if ($title.Length -gt 18) { $title = $title.Substring(0, 18) }
            $titleFile = Join-Path $directory 'codex_pet_session.txt'
            [IO.File]::WriteAllText($titleFile, $title, [Text.Encoding]::UTF8)
        }
    } catch {}
}
# Stop/UserPromptSubmit hooks require valid JSON on stdout.
[Console]::Out.WriteLine('{}')
