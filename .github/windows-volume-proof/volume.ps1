Set-StrictMode -Version Latest

function Assert-ReefVisionQuotaHosted {
    if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
        $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_REPOSITORY -cne 'Rafael-Del-Valle/ReefVision' -or
        $env:GITHUB_WORKFLOW -cne 'Windows Original Storage Recovery Proof') {
        throw 'The bounded capacity trial requires its dedicated disposable GitHub-hosted Windows workflow.'
    }
}

function Find-ReefVisionQuotaDisk([string]$ImagePath) {
    Assert-ReefVisionQuotaHosted
    $image = Get-DiskImage -ImagePath $ImagePath -ErrorAction Stop
    $disks = @($image | Get-Disk)
    if (-not $image.Attached -or $disks.Count -ne 1) { throw 'The owned VHD did not resolve to exactly one disk.' }
    $disk = $disks[0]
    if ($disk.IsBoot -or $disk.IsSystem -or $disk.IsOffline -or $disk.IsReadOnly -or
        $disk.Size -lt 240MB -or $disk.Size -gt 256MB -or -not $disk.UniqueId) {
        throw 'The resolved disk is not the owned writable VHD within the expected size.'
    }
    return $disk
}

function Get-ReefVisionQuotaVolume($Owned) {
    $disk = Find-ReefVisionQuotaDisk $Owned.ImagePath
    $partition = Get-Partition -DriveLetter $Owned.Drive
    $volume = Get-Volume -DriveLetter $Owned.Drive
    if ($disk.Number -ne $Owned.DiskNumber -or $disk.UniqueId -cne $Owned.DiskId -or
        $partition.DiskNumber -ne $disk.Number -or $partition.Guid -ne $Owned.PartitionGuid -or
        $volume.UniqueId -cne $Owned.VolumeId -or $volume.FileSystemLabel -cne $Owned.Label -or
        $volume.FileSystem -cne 'NTFS' -or $volume.Size -gt $disk.Size -or
        $Owned.Root -ine "$($Owned.Drive):\" -or $Owned.Root.TrimEnd('\') -ieq $env:SystemDrive) {
        throw 'The drive letter does not refer to the owned bounded NTFS partition.'
    }
    if ((Get-Content -LiteralPath (Join-Path $Owned.Root '.reefvision-volume-owner') -Raw).Trim() -cne $Owned.Marker) {
        throw 'The dedicated volume ownership marker changed.'
    }
    return $volume
}

function New-ReefVisionQuotaVolume([string]$ProofRoot,[string]$EvidenceRoot) {
    Assert-ReefVisionQuotaHosted
    $resolved = (Resolve-Path -LiteralPath $ProofRoot).Path
    $expected = [IO.Path]::GetFullPath("${env:SystemDrive}/rv-storage-proof-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT")
    if ($resolved -ine $expected) { throw 'Use the job-owned staging root.' }
    Assert-ReefVisionNoReparseAncestors $resolved
    $path = Join-Path $resolved 'capacity-fixture.vhdx'
    if (Test-Path -LiteralPath $path) { throw 'The scratch VHD already exists.' }
    $drive = $env:SystemDrive.TrimEnd(':')
    if ((Get-Volume -DriveLetter $drive).SizeRemaining -lt 1GB) { throw 'Insufficient host space for the bounded VHD fixture.' }
    $script = Join-Path $resolved 'attach-capacity.vhdx.diskpart'
    @(
        ('create vdisk file="{0}" maximum=256 type=expandable' -f $path)
        ('select vdisk file="{0}"' -f $path)
        'attach vdisk'
        'exit'
    ) | Set-Content -LiteralPath $script -Encoding ascii
    & (Join-Path $env:SystemRoot 'System32/diskpart.exe') /s $script *> (Join-Path $EvidenceRoot 'attach-volume.log')
    if ($LASTEXITCODE) { throw 'DiskPart could not attach the isolated VHD.' }

    $disk = Find-ReefVisionQuotaDisk $path
    if ($disk.PartitionStyle -cne 'RAW' -or @(Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue).Count) {
        throw 'Only the newly created raw VHD can be initialized.'
    }
    Initialize-Disk -InputObject $disk -PartitionStyle GPT -Confirm:$false | Out-Null
    $verified = Find-ReefVisionQuotaDisk $path
    if ($verified.Number -ne $disk.Number -or $verified.UniqueId -cne $disk.UniqueId -or $verified.PartitionStyle -cne 'GPT') {
        throw 'Owned VHD identity changed during initialization.'
    }
    $partition = New-Partition -DiskNumber $verified.Number -UseMaximumSize -AssignDriveLetter
    if ($partition.DiskNumber -ne $verified.Number -or -not $partition.DriveLetter -or
        "$($partition.DriveLetter):" -ieq $env:SystemDrive -or $partition.IsBoot -or $partition.IsSystem) {
        throw 'Refusing to format a partition outside the owned VHD.'
    }
    $drive = [string]$partition.DriveLetter
    $readback = Get-Partition -DriveLetter $drive
    if ($readback.DiskNumber -ne $verified.Number -or $readback.Guid -ne $partition.Guid) { throw 'Drive mapping changed.' }
    $label = 'RV' + ([guid]::NewGuid().ToString('N').Substring(0,16))
    $volume = Format-Volume -DriveLetter $drive -FileSystem NTFS -NewFileSystemLabel $label -Confirm:$false
    if (-not $partition.Guid -or -not $volume.UniqueId) { throw 'The bounded partition and volume must both have an identity.' }
    $root = "${drive}:\"
    $owned = [ordered]@{
        ImagePath=$path; DiskId=$verified.UniqueId; DiskNumber=$verified.Number; PartitionGuid=$partition.Guid;
        Drive=$drive; Root=$root; Label=$label; VolumeId=$volume.UniqueId; Marker=[guid]::NewGuid().ToString()
    }
    Set-Content -LiteralPath (Join-Path $root '.reefvision-volume-owner') -Value $owned.Marker -Encoding ascii
    $actual = Get-ReefVisionQuotaVolume $owned
    [ordered]@{capacity_bytes=$actual.Size; free_after_format_bytes=$actual.SizeRemaining;
        file_system=$actual.FileSystem; disk_number=$owned.DiskNumber; drive=$owned.Drive; media_is_boot_or_system=$false;
        disk_identity_sha256=([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([string]$owned.DiskId)))).ToLowerInvariant()
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'volume-identity.json')
    return $owned
}

function Set-ReefVisionQuotaPressure($Owned) {
    $volume = Get-ReefVisionQuotaVolume $Owned
    $path = Join-Path $Owned.Root '.reefvision-capacity-padding.bin'
    if (Test-Path -LiteralPath $path) { throw 'The unique capacity file must be new.' }
    $before = [long]$volume.SizeRemaining
    if ($before -lt 32MB -or $before -gt 256MB) { throw 'Unexpected capacity of the freshly seeded dedicated volume.' }
    $remaining = $before - 16KB
    $buffer = [byte[]]::new(1MB)
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    $stream = [IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
        while ($remaining -gt 0) {
            $amount = [int][Math]::Min($remaining,$buffer.Length)
            $stream.Write($buffer,0,$amount)
            $remaining -= $amount
        }
        $stream.Flush($true)
    } catch [IO.IOException] {
        # NTFS allocation granularity may consume the final cluster. Never continue on unrelated I/O errors.
        if (($_.Exception.HResult -band 0xFFFF) -notin 39,112) { throw }
    } finally { $stream.Dispose() }
    $after = Get-ReefVisionQuotaVolume $Owned
    $file = Get-Item -LiteralPath $path -Force
    if ($file.Attributes -band ([IO.FileAttributes]::ReparsePoint -bor [IO.FileAttributes]::SparseFile -bor [IO.FileAttributes]::Compressed) -or
        $after.SizeRemaining -gt 32KB -or $file.Length -gt 256MB) {
        throw 'The dedicated NTFS volume did not reach real bounded pressure.'
    }
    return [ordered]@{before_bytes=$before; pressured_bytes=$after.SizeRemaining; padding_bytes=$file.Length}
}

function Clear-ReefVisionQuotaPressure($Owned) {
    $before = Get-ReefVisionQuotaVolume $Owned
    $path = Join-Path $Owned.Root '.reefvision-capacity-padding.bin'
    if (Test-Path -LiteralPath $path) {
        $file = Get-Item -LiteralPath $path -Force
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The owned padding file is no longer a regular file.'
        }
        Remove-Item -LiteralPath $path -Force
    }
    $after = Get-ReefVisionQuotaVolume $Owned
    return [ordered]@{before_bytes=$before.SizeRemaining; released_bytes=$after.SizeRemaining}
}
