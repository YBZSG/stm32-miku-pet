param([Parameter(Mandatory=$true)][string]$Port,[string]$VoicePack="$PSScriptRoot\..\assets\miku_voice.bin",[int]$Baud=115200)
$ErrorActionPreference='Stop';$payload=[IO.File]::ReadAllBytes((Resolve-Path $VoicePack))
function Crc([byte[]]$d){[uint32]$c=[uint32]::MaxValue;foreach($v in $d){$c=$c-bxor$v;1..8|%{if($c-band 1){$c=($c-shr 1)-bxor 0xEDB88320}else{$c=$c-shr 1}}};$c-bxor[uint32]::MaxValue}
[uint32]$crc=Crc $payload;$s=[IO.Ports.SerialPort]::new($Port,$Baud,'None',8,'One');$s.ReadTimeout=1000;$s.WriteTimeout=10000
try{
    $s.Open();Start-Sleep -Seconds 2;$s.DiscardInBuffer();$s.Write('A');Start-Sleep -Milliseconds 100
    $m=New-Object byte[] 8;[BitConverter]::GetBytes([uint32]$payload.Length).CopyTo($m,0);[BitConverter]::GetBytes($crc).CopyTo($m,4);$s.Write($m,0,8)
    $deadline=[datetime]::UtcNow.AddSeconds(60);do{try{$line=$s.ReadLine();Write-Host $line}catch{}}until($line-match 'AUDIO_READY'-or[datetime]::UtcNow-gt$deadline)
    if($line-notmatch'AUDIO_READY'){throw'等待开发板握手超时 (AUDIO_READY)'}
    Write-Host "[*] 开始烧录语音包 ($($payload.Length) 字节)..."
    for($n=0;$n-lt$payload.Length;$n+=256){
        $count=[math]::Min(256,$payload.Length-$n)
        $s.Write($payload,$n,$count)
        Start-Sleep -Milliseconds 10
        if(($n % 65536) -eq 0 -or ($n + $count) -eq $payload.Length){
            $pct = [math]::Round(($n + $count) * 100.0 / $payload.Length, 1)
            Write-Host -NoNewline "`r[*] 烧录进度: $pct% ($($n + $count)/$($payload.Length) 字节)"
        }
    }
    Write-Host "`n[*] 数据发送完毕，等待 Flash 校验确认..."
    $deadline=[datetime]::UtcNow.AddSeconds(180);do{try{$line=$s.ReadLine();Write-Host $line}catch{}}until($line-match'AUDIO_OK'-or[datetime]::UtcNow-gt$deadline)
    if($line-notmatch'AUDIO_OK'){throw'音频 Flash 烧录超时或校验失败'}
    Write-Host "[OK] 专属 Miku 语音包烧录成功！"
}finally{if($s.IsOpen){$s.Close()};$s.Dispose()}
