@echo off
setlocal
title MotionSmith Surface Setup
set "MS_SURFACE_INSTALLER=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$raw=[IO.File]::ReadAllText($env:MS_SURFACE_INSTALLER); $body=[regex]::Split($raw,'(?m)^# POWERSHELL_PAYLOAD\r?$')[1]; if(-not $body){exit 1}; & ([scriptblock]::Create($body))"
set "MS_SURFACE_RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %MS_SURFACE_RESULT%
# POWERSHELL_PAYLOAD
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$BackendUrl = 'https://huggingface.co/Serqan/MotionSmith-Surface-Backend/resolve/main/motionsmith_surface_backend_win64_0.1.1.zip?download=true'
$BackendHash = '0a9c26a8592cbf36a8732c5667ebcf924c241d9cbc72a92623d5459b60636ab7'
$BackendSize = [long]4428090499
$Models = @(
    @('diffusion_models/flux-2-klein-base-9b-Q4_0.gguf', 'https://huggingface.co/unsloth/FLUX.2-klein-base-9B-GGUF/resolve/main/flux-2-klein-base-9b-Q4_0.gguf?download=true', [long]5616228640, '02d4c2b55b5a6d4aca65eafd0f0eabe8c1e3837391042b6879be04eb99c7e116'),
    @('text_encoders/qwen_3_8b_fp8mixed.safetensors', 'https://huggingface.co/Comfy-Org/flux2-klein-9B/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors?download=true', [long]8664848742, 'abad16806e0cbabc54e0325d6565847443fe396d5f0be38bb3cd3fe75a1201d6'),
    @('vae/flux2-vae.safetensors', 'https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors?download=true', [long]336213556, 'd64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5'),
    @('loras/ultratex_flux2.safetensors', 'https://www.modelscope.ai/models/Yibo-Zhang/UltraTex/resolve/master/flux2/lora/dit_lora.safetensors?view=false', [long]478172752, '3b1915177a81bc2ab43f501355bf39113df0128e6cbc6fedf8b8621d5e06a01c'),
    @('loras/ultratex_flux2_mr.safetensors', 'https://www.modelscope.ai/models/Yibo-Zhang/UltraTex/resolve/master/flux2_mr/lora/dit_lora.safetensors?view=false', [long]478172752, '13e94f5a30a789b1e3e76d8c96cbba5f52fb2f68411e56377f382e145da23fc1'),
    @('ultratex/ultratex_flux2_decoder.pt', 'https://www.modelscope.ai/models/Yibo-Zhang/UltraTex/resolve/master/flux2/decoder.pt?view=false', [long]99261764, '981dc4c52481687c6da4e6211617615a2b2bcc33456e1953ee6c5478aa00025b'),
    @('deepbump/deepbump256.onnx', 'https://raw.githubusercontent.com/HugoTini/DeepBump/fad19ba87daed12b1d0410a57e74f3d79e82f78d/deepbump256.onnx', [long]26706979, '3a2ababc5fa652b19040a0f3d639b71826368e52ad805cf70ffb0e7c96a54d67'),
    @('background_removal/birefnet.safetensors', 'https://huggingface.co/Comfy-Org/BiRefNet/resolve/main/background_removal/birefnet.safetensors?download=true', [long]444473596, '9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154'),
    @('checkpoints/SD/chord_v1.safetensors', 'https://huggingface.co/Ubisoft/ubisoft-laforge-chord/resolve/main/chord_v1.safetensors?download=true', [long]2761211350, 'b56f48857f1d84f0d051284d0c1f3ac58ecc6e86fba15c4849789f3807dd0cc2')
)

function Test-Download {
    param([string]$Path, [long]$Size, [string]$Hash)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne $Size) { return $false }
    Write-Host "Checking SHA-256: $([IO.Path]::GetFileName($Path))"
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
        return $actual -eq $Hash
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function Get-Download {
    param([string]$Url, [string]$Path, [long]$Size, [string]$Hash, [string]$Token = '')
    if (Test-Path -LiteralPath $Path) {
        if (Test-Download $Path $Size $Hash) {
            Write-Host 'Already installed and verified.' -ForegroundColor Green
            return
        }
        throw "Existing file differs from this release: $Path . Move it aside before retrying; it was not overwritten."
    }
    $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Path)) -Force
    $partial = $Path + '.part'
    if ((Test-Path -LiteralPath $partial) -and (Get-Item -LiteralPath $partial).Length -ge $Size) {
        if (-not (Test-Download $partial $Size $Hash)) {
            throw "Partial download is invalid: $partial . Move it aside and run setup again."
        }
    } else {
        Write-Host ('Downloading {0:N2} GiB -> {1}' -f ($Size / 1GB), $Path)
        # Send auth through stdin, never a process argument or a credential file.
        $curlConfig = ''
        if ($Token) {
            if ($Token -notmatch '^hf_[A-Za-z0-9]+$') { throw 'Invalid Hugging Face token format.' }
            $curlConfig = 'header = "Authorization: Bearer ' + $Token + '"'
        }
        $httpCode = $curlConfig | & curl.exe --config - --location --fail --retry 3 --retry-delay 3 --connect-timeout 30 --speed-limit 1024 --speed-time 120 --continue-at - --progress-bar --output $partial --write-out '%{http_code}' --url $Url
        $curlExit = $LASTEXITCODE
        $curlConfig = $null
        if ($curlExit -ne 0) {
            throw "Download failed (curl $curlExit, HTTP $httpCode). Partial data was kept. Run this BAT again to resume."
        }
        if (-not (Test-Download $partial $Size $Hash)) {
            throw "Download verification failed: $partial . Move this file aside before retrying."
        }
    }
    Move-Item -LiteralPath $partial -Destination $Path
    Write-Host 'Verified.' -ForegroundColor Green
}

function Test-Backend {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath (Join-Path $Path 'main.py') -PathType Leaf)) { return $false }
    if (-not (Get-BackendPython $Path)) { return $false }
    foreach ($node in @('ComfyUI-UltraTex', 'comfyui_ultratex_modular', 'ComfyUI-Chord', 'ComfyUI-GGUF', 'comfy-mtb')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path ('custom_nodes\' + $node)))) { return $false }
    }
    return $true
}

function Get-BackendPython {
    param([string]$Path)
    foreach ($relative in @('.venv\Scripts\python.exe', 'venv\Scripts\python.exe', '..\python_embeded\python.exe', '..\python_embedded\python.exe')) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $Path $relative))
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return ''
}

function Find-ComfyInstallations {
    param([string[]]$Roots)
    $found = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $modelRoots = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $queue = New-Object 'System.Collections.Generic.Queue[string]'
    foreach ($root in $Roots) { $queue.Enqueue($root) }
    $skip = @('Windows', '$Recycle.Bin', 'System Volume Information', 'WinSxS', 'node_modules', '.git', '.venv', 'venv', '__pycache__', 'site-packages', 'python_embeded', 'python_embedded')
    $count = 0
    while ($queue.Count) {
        $directory = $queue.Dequeue()
        $count++
        if ($count % 500 -eq 0) { Write-Progress -Activity 'Finding ComfyUI installations (directory names only)' -Status "$count folders checked; $($found.Count) installations found" }
        if ([IO.File]::Exists((Join-Path $directory 'main.py')) -and [IO.File]::Exists((Join-Path $directory 'folder_paths.py'))) {
            if ($found.Add($directory)) { Write-Host "Found ComfyUI: $directory" -ForegroundColor Green }
            $null = $modelRoots.Add((Join-Path $directory 'models'))
            continue
        }
        try {
            foreach ($child in [IO.Directory]::EnumerateDirectories($directory)) {
                $name = [IO.Path]::GetFileName($child)
                if ($name -match '(?i)(comfy.*model|model.*comfy|^models$|^weights$)') {
                    $null = $modelRoots.Add($child)
                    continue
                }
                if ($name -in $skip) { continue }
                # Do not follow directory links; avoids loops and repeated disk scans.
                if (([IO.File]::GetAttributes($child) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
                $queue.Enqueue($child)
            }
        } catch { continue }
    }
    Write-Progress -Activity 'Finding ComfyUI installations (directory names only)' -Completed
    return @{ Installations = @($found); ModelRoots = @($modelRoots) }
}

function Get-ModelIndex {
    param([string[]]$Roots, [object[]]$RequiredModels)
    $sizes = @{}
    foreach ($model in $RequiredModels) { $sizes[[string]$model[2]] = $true }
    $index = @{}
    $visited = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $queue = New-Object 'System.Collections.Generic.Queue[string]'
    foreach ($root in $Roots) { if ([IO.Directory]::Exists($root)) { $queue.Enqueue([IO.Path]::GetFullPath($root)) } }
    while ($queue.Count) {
        $directory = $queue.Dequeue()
        if (-not $visited.Add($directory)) { continue }
        try {
            foreach ($path in [IO.Directory]::EnumerateFiles($directory)) {
                if ([IO.Path]::GetExtension($path) -notin @('.safetensors', '.gguf', '.pt', '.onnx')) { continue }
                $file = New-Object IO.FileInfo($path)
                $key = [string]$file.Length
                if ($sizes.ContainsKey($key)) {
                    if (-not $index.ContainsKey($key)) { $index[$key] = New-Object 'System.Collections.Generic.List[string]' }
                    $index[$key].Add($path)
                }
            }
            foreach ($child in [IO.Directory]::EnumerateDirectories($directory)) {
                if (([IO.File]::GetAttributes($child) -band [IO.FileAttributes]::ReparsePoint) -eq 0) { $queue.Enqueue($child) }
                else {
                    # Category links are common in shared model libraries. Visit their resolved target once.
                    $target = (Get-Item -LiteralPath $child -Force).Target
                    if ($target) {
                        $resolved = [string]@($target)[0]
                        if (-not [IO.Path]::IsPathRooted($resolved)) { $resolved = Join-Path $directory $resolved }
                        $queue.Enqueue([IO.Path]::GetFullPath($resolved))
                    }
                }
            }
        } catch { continue }
    }
    return $index
}

function Install-Model {
    param([object[]]$Model, [string]$Target, [hashtable]$Index, [string]$Token = '')
    if (-not (Test-Path -LiteralPath $Target)) {
        foreach ($candidate in $Index[[string]$Model[2]]) {
            if (Test-Download $candidate $Model[2] $Model[3]) {
                $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Target)) -Force
                try {
                    $null = New-Item -ItemType HardLink -Path $Target -Target $candidate -ErrorAction Stop
                    Write-Host "Reusing existing model (hard link): $candidate" -ForegroundColor Green
                } catch {
                    Write-Host "Reusing existing model (copy across disks): $candidate"
                    Copy-Item -LiteralPath $candidate -Destination $Target -ErrorAction Stop
                }
                return
            }
        }
    }
    Get-Download $Model[1] $Target $Model[2] $Model[3] $Token
}

function Install-Surface {
    $null = Get-Command curl.exe -ErrorAction Stop
    Write-Host 'MotionSmith Surface - Backend + Models Setup' -ForegroundColor Cyan
    Write-Host 'Full download is about 21.5 GiB. Existing verified models are reused instead.'
    Write-Host 'The Blender add-on ZIP is installed separately in Blender.'
    Write-Host 'Close ComfyUI before installing. No administrator access is required.'
    Write-Host "`nScanning local fixed disks for ComfyUI and shared model folders..."
    $drives = @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -eq 'Fixed' } | ForEach-Object { $_.RootDirectory.FullName })
    $discovery = Find-ComfyInstallations $drives
    $compatible = @($discovery.Installations | Where-Object { Test-Backend $_ } | Sort-Object)
    $defaultRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'MotionSmith\Surface'
    if ($compatible.Count) {
        $defaultRoot = $compatible[0]
        Write-Host "Existing backend has the Surface nodes and Python: $defaultRoot"
    } elseif ($discovery.Installations.Count) {
        Write-Host 'Found ComfyUI, but required Surface nodes/Python are missing. A separate Surface backend will be installed; existing models will be reused.'
    }
    Write-Host "Default installation folder: $defaultRoot"
    $chosen = Read-Host 'Press Enter for the default, or enter an installation folder / existing comfyui folder'
    if ([string]::IsNullOrWhiteSpace($chosen)) { $chosen = $defaultRoot }
    $installRoot = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($chosen.Trim().Trim('"')))
    $comfy = Join-Path $installRoot 'comfyui'
    if (Test-Backend $installRoot) { $comfy = $installRoot }
    $null = New-Item -ItemType Directory -Path $installRoot -Force

    Write-Host "`n[1/3] Backend" -ForegroundColor Cyan
    if (Test-Backend $comfy) {
        Write-Host "Using existing backend: $comfy"
    } else {
        if (Test-Path -LiteralPath $comfy) {
            throw "Incomplete or different backend at $comfy . Select a new folder; no existing installation was overwritten."
        }
        $archive = Join-Path $installRoot 'motionsmith_surface_backend_win64_0.1.1.zip'
        Get-Download $BackendUrl $archive $BackendSize $BackendHash
        Write-Host 'Extracting backend. This can take several minutes...'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $staging = Join-Path $installRoot ('.surface-extract-' + [Guid]::NewGuid().ToString('N'))
        [IO.Compression.ZipFile]::ExtractToDirectory($archive, $staging)
        $extracted = Join-Path $staging 'comfyui'
        if (-not (Test-Backend $extracted)) { throw "Unexpected backend layout in $staging" }
        Move-Item -LiteralPath $extracted -Destination $comfy
        # Only remove the now-empty staging directory; never delete user content.
        [IO.Directory]::Delete($staging, $false)
        Write-Host 'Backend extracted.' -ForegroundColor Green
    }

    Write-Host "`nReading extra_model_paths.yaml and indexing model file sizes..."
    $modelRoots = @($discovery.ModelRoots) + @((Join-Path $comfy 'models'))
    # Parse YAML with the selected backend's PyYAML; never execute YAML tags.
    $yamlProbe = @'
import json, os, sys, yaml
roots=[]
for base in json.loads(sys.stdin.read()):
    config=os.path.join(base, 'extra_model_paths.yaml')
    if not os.path.isfile(config): continue
    try:
        with open(config, encoding='utf-8-sig') as f: doc=yaml.safe_load(f) or {}
        for group in doc.values():
            if not isinstance(group, dict): continue
            prefix=os.path.expandvars(os.path.expanduser(str(group.get('base_path', base))))
            if not os.path.isabs(prefix): prefix=os.path.join(base, prefix)
            for key, value in group.items():
                if key in ('base_path', 'is_default'): continue
                for relative in (value if isinstance(value,list) else str(value).splitlines()):
                    path=os.path.expandvars(os.path.expanduser(str(relative).strip()))
                    if path: roots.append(os.path.normpath(os.path.join(prefix,path)))
    except Exception as e: print('Cannot read '+config+': '+str(e),file=sys.stderr)
print(json.dumps(roots))
'@
    $python = Get-BackendPython $comfy
    $configs = @($discovery.Installations) + @($comfy)
    $extraRootsJson = ConvertTo-Json -InputObject $configs -Compress
    $extraRoots = $extraRootsJson | & $python -c $yamlProbe
    if ($LASTEXITCODE -ne 0) { throw 'Could not read backend model path configuration.' }
    $modelRoots += @($extraRoots | ConvertFrom-Json)
    $modelIndex = Get-ModelIndex $modelRoots $Models

    Write-Host "`n[2/3] Texture models" -ForegroundColor Cyan
    for ($i = 0; $i -lt 7; $i++) {
        $model = $Models[$i]
        Write-Host ("`n[{0}/8] {1}" -f ($i + 1), $model[0])
        $target = Join-Path (Join-Path $comfy 'models') $model[0]
        Install-Model $model $target $modelIndex
    }

    Write-Host "`n[3/3] Chord PBR Material model" -ForegroundColor Cyan
    Write-Host 'Chord uses the Ubisoft Machine Learning Research-Only license.'
    $chord = $Models[7]
    $target = Join-Path (Join-Path $comfy 'models') $chord[0]
    $chordReady = $false
    try {
        Install-Model $chord $target $modelIndex
        $chordReady = $true
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        Write-Host 'If access is denied, sign in and accept the model terms here:'
        Write-Host 'https://huggingface.co/Ubisoft/ubisoft-laforge-chord'
        Write-Host 'Then create a Read token with access to this model: https://huggingface.co/settings/tokens'
        Write-Host 'Paste the token below (hidden), or press Enter to skip Chord for now.'
        $secret = Read-Host 'Hugging Face token' -AsSecureString
        if ($secret.Length -gt 0) {
            $credential = New-Object System.Net.NetworkCredential('', $secret)
            try {
                Install-Model $chord $target $modelIndex $credential.Password
                $chordReady = $true
            } finally {
                $credential = $null
                $secret.Dispose()
            }
        } else { $secret.Dispose() }
    }

    Write-Host "`nTexture setup complete." -ForegroundColor Green
    if ($chordReady) { Write-Host 'PBR Material setup complete.' -ForegroundColor Green }
    else { Write-Host 'PBR Material NOT installed. Run setup again after obtaining Chord access.' -ForegroundColor Yellow }
    Write-Host "`nBlender Preferences > Add-ons > MotionSmith Surface > Backend"
    Write-Host "ComfyUI Directory: $comfy"
    Write-Host ('Python Executable: ' + $python)
    Write-Host 'Save Preferences, start the server, then Refresh Installed Models.'
    Write-Host 'The verified backend ZIP is kept for reuse.'
    if (-not $chordReady) { return 2 }
    return 0
}

try {
    $result = Install-Surface
    exit $result
} catch {
    Write-Host "`nSETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Completed downloads and partial files were kept. Correct the issue and run this BAT again.'
    exit 1
}
