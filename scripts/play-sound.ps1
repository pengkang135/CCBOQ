Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
$player = New-Object System.Windows.Media.MediaPlayer
$player.add_MediaOpened({ $player.Play() })
$player.add_MediaEnded({ [System.Windows.Threading.Dispatcher]::ExitAllFrames() })
$player.add_MediaFailed({ Write-Error "play failed: $($_.ErrorException.Message)"; [System.Windows.Threading.Dispatcher]::ExitAllFrames() })
$timer = New-Object System.Timers.Timer(10000)
$timer.AutoReset = $false
$timer.add_Elapsed({ Write-Error "timeout"; [System.Windows.Threading.Dispatcher]::ExitAllFrames() })
$player.Open($args[0])
$timer.Start()
[System.Windows.Threading.Dispatcher]::Run()
$timer.Dispose()
$player.Close()
