param([string]$Path)
Add-Type -AssemblyName PresentationCore

$player = New-Object System.Windows.Media.MediaPlayer
$player.Open($Path)

# 等待媒体加载完毕
while ($player.NaturalDuration.HasTimeSpan -eq $false) {
    Start-Sleep -Milliseconds 200
}

$total = $player.NaturalDuration.TimeSpan.TotalSeconds
$player.Play()

# 等待播放完成，最多等 total+2 秒
$elapsed = 0
while ($elapsed -lt ($total + 2)) {
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
}

$player.Close()
