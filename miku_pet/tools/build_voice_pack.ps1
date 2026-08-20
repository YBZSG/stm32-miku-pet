$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$voiceDir = Join-Path $root 'assets\voice'
$output = Join-Path $root 'assets\miku_voice.bin'
$names = @('working.wav','waiting.wav','failed.wav','complete.wav')
$header = New-Object byte[] 40
[Text.Encoding]::ASCII.GetBytes('VOIC').CopyTo($header,0)
[BitConverter]::GetBytes([uint32]1).CopyTo($header,4)
$parts = @(); [uint32]$offset = 40
for($i=0;$i-lt 4;$i++){
  [byte[]]$data=[IO.File]::ReadAllBytes((Join-Path $voiceDir $names[$i]));$parts += ,$data
  [BitConverter]::GetBytes($offset).CopyTo($header,8+$i*8)
  [BitConverter]::GetBytes([uint32]$data.Length).CopyTo($header,12+$i*8)
  $offset += $data.Length
}
$stream=[IO.File]::Create($output);try{$stream.Write($header,0,$header.Length);foreach($p in $parts){$stream.Write($p,0,$p.Length)}}finally{$stream.Dispose()}
Write-Host "Created $output ($offset bytes)"
