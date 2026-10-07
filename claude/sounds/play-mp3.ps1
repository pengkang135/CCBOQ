param([string]$Path)

# Play a WAV completion sound with System.Media.SoundPlayer (Windows built-in).
# Replaces the old WPF MediaPlayer approach (PresentationCore + Media
# Foundation), whose media-codec DLL init failed with 0xc0000142.

# --- 临时诊断日志（定位完就删）---
$__log = 'C:/Users/Kevin/albedo-cfg/claude/sounds/play-diag.log'
function __L([string]$m) { try { Add-Content -Path $__log -Value ("[{0}] pid={1} {2}" -f ([DateTime]::Now.ToString('HH:mm:ss.fff')), $PID, $m) } catch {} }
$__sw = [System.Diagnostics.Stopwatch]::StartNew()
__L "start exists=$(Test-Path $Path) path=$Path"
# --------------------------------

try {
	$player = New-Object System.Media.SoundPlayer
	$player.SoundLocation = $Path
	$player.Load()
	__L ("loaded in {0}ms" -f $__sw.ElapsedMilliseconds)
	$player.PlaySync()
	__L ("done in {0}ms" -f $__sw.ElapsedMilliseconds)
} catch {
	__L ("error: " + $_.Exception.Message)
}
