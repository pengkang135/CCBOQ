param([string]$Path)
Add-Type -AssemblyName PresentationCore

$player = New-Object System.Windows.Media.MediaPlayer
$player.Open($Path)

# Wait for media to load
while ($player.NaturalDuration.HasTimeSpan -eq $false) {
    Start-Sleep -Milliseconds 200
}

$total = $player.NaturalDuration.TimeSpan.TotalSeconds
$player.Play()

# Wait for playback to finish, up to total+2 seconds
$elapsed = 0
while ($elapsed -lt ($total + 2)) {
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
}

$player.Close()
