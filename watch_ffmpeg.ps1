# Surveille les processus ffmpeg en cours et logue ceux qui dépassent un seuil de RAM.
# Lance ce script dans une fenêtre PowerShell pendant que tu testes DerushTool.exe.
# Usage : powershell -ExecutionPolicy Bypass -File watch_ffmpeg.ps1

$Threshold_MB = 200   # alerte au-dessus de 200 MB par ffmpeg
$Interval_Sec = 2

Write-Host "=== watch_ffmpeg : surveille les ffmpeg > $Threshold_MB MB toutes les $Interval_Sec s ===" -ForegroundColor Cyan
Write-Host "Ctrl+C pour quitter." -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" -ErrorAction SilentlyContinue
    $count = if ($procs) { @($procs).Count } else { 0 }

    $timestamp = Get-Date -Format "HH:mm:ss"
    if ($count -gt 0) {
        # Récupère la RAM via Get-Process (les CimInstance n'ont pas WorkingSet de la même façon)
        $rams = @{}
        Get-Process -Name ffmpeg -ErrorAction SilentlyContinue | ForEach-Object {
            $rams[$_.Id] = [math]::Round($_.WorkingSet64 / 1MB, 1)
        }

        $heavy = @()
        $totalMB = 0
        foreach ($p in $procs) {
            $mb = $rams[[int]$p.ProcessId]
            if ($null -ne $mb) {
                $totalMB += $mb
                if ($mb -ge $Threshold_MB) {
                    $heavy += [PSCustomObject]@{
                        PID = $p.ProcessId
                        MB  = $mb
                        Cmd = $p.CommandLine
                    }
                }
            }
        }

        $line = "[$timestamp] $count ffmpeg actifs, total ~$([math]::Round($totalMB))MB"
        if ($heavy.Count -gt 0) {
            Write-Host $line -ForegroundColor Yellow
            foreach ($h in $heavy) {
                # Tronquer la commande pour rester lisible
                $cmdShort = $h.Cmd
                if ($cmdShort.Length -gt 250) { $cmdShort = $cmdShort.Substring(0, 250) + "..." }
                Write-Host ("    -> PID {0,-6} {1,8:N0} MB  {2}" -f $h.PID, $h.MB, $cmdShort) -ForegroundColor Red
            }
        } else {
            Write-Host $line -ForegroundColor DarkGray
        }
    } else {
        Write-Host "[$timestamp] (aucun ffmpeg)" -ForegroundColor DarkGray
    }

    Start-Sleep -Seconds $Interval_Sec
}
