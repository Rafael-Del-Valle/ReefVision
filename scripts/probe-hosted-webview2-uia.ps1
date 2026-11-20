param(
    [Parameter(Mandatory)][int]$DesktopProcessId,
    [Parameter(Mandatory)][string]$Api,
    [Parameter(Mandatory)][string]$Evidence,
    [Parameter(Mandatory)][string]$Name
)
$ErrorActionPreference='Stop'
if ($Api -notmatch '^http://127[.]0[.]0[.]1:[0-9]{1,5}/api/v1$') { throw 'UI Automation probe requires isolated loopback API.' }
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$receipt = [ordered]@{engine='Windows UI Automation'; desktop_pid=$DesktopProcessId; controls=@(); project_id=$null; persisted=$false}
function Find-ProbeControl([string]$Label, $ControlType, [int]$Seconds=8) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        $window = Get-Process -Id $DesktopProcessId
        if ($window.MainWindowHandle -ne [IntPtr]::Zero) {
            $root = [System.Windows.Automation.AutomationElement]::FromHandle($window.MainWindowHandle)
            $condition = [System.Windows.Automation.AndCondition]::new(
                [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty, $Label),
                [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty, $ControlType)
            )
            $matches = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
            for ($i=$matches.Count-1; $i -ge 0; $i--) {
                $control = $matches.Item($i)
                if ($control.Current.IsEnabled -and -not $control.Current.IsOffscreen) { return $control }
            }
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}
function Invoke-ProbeButton([string]$Label, [int]$Seconds=8, [switch]$Optional) {
    $control = Find-ProbeControl -Label $Label -ControlType ([System.Windows.Automation.ControlType]::Button) -Seconds $Seconds
    if ($control) {
        $control.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $receipt.controls += $Label
    } elseif (-not $Optional) {
        throw "Could not find the enabled UI Automation button '$Label'."
    }
}
try {
    Invoke-ProbeButton -Label 'Skip for now' -Seconds 5 -Optional
    Invoke-ProbeButton -Label 'New project'
    $inputText = Find-ProbeControl -Label 'Project name' -ControlType ([System.Windows.Automation.ControlType]::Edit)
    if (-not $inputText) { throw 'Could not find the ordinary Project name field through Accessibility.' }
    $inputText.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($Name)
    $receipt.controls += 'Project name'
    Invoke-ProbeButton -Label 'Create project'
    $deadline=[DateTime]::UtcNow.AddSeconds(8)
    do {
        $project = @(Invoke-RestMethod "$Api/projects" | Where-Object { $_.name -ceq $Name })
        if ($project.Count -eq 1) {
            $receipt.project_id = $project[0].id
            $receipt.persisted = (Invoke-RestMethod "$Api/projects/$($project[0].id)").name -ceq $Name
            break
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $receipt.persisted) { throw 'The normal native project creation action did not persist through the packaged API.' }
} finally {
    $receipt | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $Evidence -Encoding utf8
}
