using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

internal static class Program
{
    private const string Owner = "Rafael-Del-Valle";
    private const string Repository = "ReefVision";
    private const string DownloadName = "ReefVision Windows downloader";
    private static readonly Regex ReleaseTag = new(
        @"^v(?<version>\d+\.\d+\.\d+)(?:-rc\.(?<rc>\d+))?$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly Regex CabinetName = new(
        @"^rv(?<number>[1-9]\d*)\.cab$",
        RegexOptions.CultureInvariant | RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private sealed record Asset(string Name, long Size, string Sha256);
    private sealed record ReleaseCandidate(
        string Tag,
        string VersionText,
        Version Number,
        bool IsPrerelease,
        int RcNumber,
        string InstallerName,
        IReadOnlyDictionary<string, long> Sizes);

    private static string AssetUrl(string tag, string name) =>
        $"https://github.com/{Owner}/{Repository}/releases/download/{Uri.EscapeDataString(tag)}/{Uri.EscapeDataString(name)}";

    public static async Task<int> Main(string[] args)
    {
        Console.Title = DownloadName;
        Console.WriteLine("ReefVision — Windows downloader");
        Console.WriteLine("Downloads the Windows MSI and its CAB files from official GitHub releases.");
        Console.WriteLine("Model checkpoints and other software are not included.");
        Console.WriteLine();

        bool checkOnly = args.Contains("--check-release", StringComparer.Ordinal);
        bool stableOnly = args.Contains("--stable", StringComparer.Ordinal);
        if (args.Any(arg => arg is not ("--check-release" or "--stable")))
        {
            Console.Error.WriteLine("Supported options: --check-release, --stable");
            return 2;
        }

        using var cancellation = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };

        using var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = true });
        client.Timeout = Timeout.InfiniteTimeSpan;
        client.DefaultRequestHeaders.UserAgent.ParseAdd("ReefVision-Windows-Downloader/1.1");

        try
        {
            var release = await SelectReleaseAsync(client, stableOnly, cancellation.Token);
            var assets = await ReadReleaseManifestAsync(client, release, cancellation.Token);
            Console.WriteLine($"Selected: {release.Tag} ({(release.IsPrerelease ? "TEST RELEASE" : "stable release")})");
            Console.WriteLine($"Installer: {release.InstallerName}; CAB files: {assets.Count - 1}");
            Console.WriteLine("Required release assets and checksums: OK");
            Console.WriteLine();

            if (checkOnly)
            {
                Console.WriteLine("Release metadata check passed. No installer files were downloaded.");
                return 0;
            }

            if (release.IsPrerelease)
            {
                Console.WriteLine("NOTICE: This is a release candidate for testing, not a final stable release.");
                Console.WriteLine("For the stable version, start this downloader with --stable.");
                Console.WriteLine();
            }

            var downloads = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Downloads", "ReefVision-" + release.Tag.TrimStart('v'));
            Directory.CreateDirectory(downloads);
            Console.WriteLine($"Installer folder: {downloads}");
            Console.WriteLine();

            foreach (var asset in assets)
                await EnsureDownloadedAsync(client, asset, release.Tag, downloads, cancellation.Token);

            Console.WriteLine();
            Console.WriteLine($"All {assets.Count} installer files were downloaded and verified.");
            Console.WriteLine("Press Enter to open the Windows installer, or close this window to install later.");
            Console.ReadLine();

            var installerPath = Path.Combine(downloads, release.InstallerName);
            Process.Start(new ProcessStartInfo(installerPath) { UseShellExecute = true });
            Console.WriteLine("Windows installer opened. Follow its on-screen instructions.");
            return 0;
        }
        catch (OperationCanceledException)
        {
            Console.WriteLine("Download cancelled. Previously verified files are kept.");
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine();
            Console.Error.WriteLine("Download could not complete: " + ex.Message);
            Console.Error.WriteLine("Existing verified files are kept. Run the downloader again to retry.");
            if (!Console.IsInputRedirected)
            {
                Console.Error.WriteLine("Press Enter to close.");
                Console.ReadLine();
            }
            return 1;
        }
    }

    private static async Task<ReleaseCandidate> SelectReleaseAsync(
        HttpClient client, bool stableOnly, CancellationToken cancellation)
    {
        // GitHub's /releases/latest ignores prereleases. Read the release list instead.
        using var response = await client.GetAsync(
            $"https://api.github.com/repos/{Owner}/{Repository}/releases?per_page=100",
            HttpCompletionOption.ResponseHeadersRead, cancellation);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync(cancellation);
        using var json = await JsonDocument.ParseAsync(stream, cancellationToken: cancellation);

        var candidates = new List<ReleaseCandidate>();
        foreach (var entry in json.RootElement.EnumerateArray())
        {
            if (entry.GetProperty("draft").GetBoolean())
                continue;
            bool prerelease = entry.GetProperty("prerelease").GetBoolean();
            if (stableOnly && prerelease)
                continue;

            var tag = entry.GetProperty("tag_name").GetString() ?? "";
            var match = ReleaseTag.Match(tag);
            if (!match.Success || (match.Groups["rc"].Success != prerelease))
                continue;

            var versionText = match.Groups["version"].Value;
            if (!Version.TryParse(versionText, out var version))
                continue;
            int rc = 0;
            if (prerelease && !int.TryParse(match.Groups["rc"].Value, out rc))
                continue;

            var installer = $"ReefVision_{versionText}_x64_en-US.msi";
            var sizes = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
            foreach (var asset in entry.GetProperty("assets").EnumerateArray())
            {
                var name = asset.GetProperty("name").GetString() ?? "";
                if (asset.GetProperty("state").GetString() != "uploaded")
                    continue;
                if (name != installer && name != "build-provenance.json"
                    && !CabinetName.IsMatch(name))
                    continue;
                var size = asset.GetProperty("size").GetInt64();
                if (size <= 0 || !sizes.TryAdd(name, size))
                    throw new InvalidDataException($"Unexpected release asset metadata: {name}");
            }

            if (!sizes.ContainsKey(installer) || !sizes.ContainsKey("build-provenance.json")
                || !sizes.Keys.Any(k => CabinetName.IsMatch(k)))
                continue;

            candidates.Add(new ReleaseCandidate(
                tag, versionText, version, prerelease, rc, installer, sizes));
        }

        var selected = candidates
            .OrderByDescending(r => r.Number)
            .ThenByDescending(r => !r.IsPrerelease)
            .ThenByDescending(r => r.RcNumber)
            .FirstOrDefault();
        return selected ?? throw new InvalidDataException(
            stableOnly
                ? "No complete stable ReefVision Windows release was found."
                : "No complete ReefVision Windows release was found.");
    }

    private static async Task<IReadOnlyList<Asset>> ReadReleaseManifestAsync(
        HttpClient client, ReleaseCandidate release, CancellationToken cancellation)
    {
        using var response = await client.GetAsync(
            AssetUrl(release.Tag, "build-provenance.json"),
            HttpCompletionOption.ResponseHeadersRead, cancellation);
        response.EnsureSuccessStatusCode();
        var contents = (ReadOnlyMemory<byte>)await response.Content.ReadAsByteArrayAsync(cancellation);
        if (contents.Span.StartsWith(new byte[] { 0xEF, 0xBB, 0xBF }))
            contents = contents[3..];
        using var json = JsonDocument.Parse(contents);
        var root = json.RootElement;

        if (root.GetProperty("version").GetString() != release.VersionText
            || !root.GetProperty("source_tree_clean").GetBoolean()
            || !root.GetProperty("msi_verified").GetBoolean())
            throw new InvalidDataException(
                "The published provenance does not identify a verified build for " + release.Tag);

        var records = new Dictionary<string, Asset>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in root.GetProperty("files").EnumerateArray())
        {
            var name = entry.GetProperty("name").GetString()
                ?? throw new InvalidDataException("Release file is missing a filename.");
            var hash = entry.GetProperty("sha256").GetString()
                ?? throw new InvalidDataException("Release file is missing its SHA-256.");
            if (!string.Equals(Path.GetFileName(name), name, StringComparison.Ordinal)
                || (!name.Equals(release.InstallerName, StringComparison.OrdinalIgnoreCase)
                    && !CabinetName.IsMatch(name))
                || !release.Sizes.TryGetValue(name, out long size)
                || hash.Length != 64
                || !hash.All(Uri.IsHexDigit)
                || !records.TryAdd(name, new Asset(name, size, hash)))
                throw new InvalidDataException("Release manifest contains an invalid installer file.");
        }

        var cabinetNumbers = new HashSet<int>();
        foreach (var cab in records.Keys.Where(name => CabinetName.IsMatch(name)))
        {
            var numberText = CabinetName.Match(cab).Groups["number"].Value;
            if (!int.TryParse(numberText, out var number) || !cabinetNumbers.Add(number))
                throw new InvalidDataException("Invalid CAB filename sequence.");
        }

        if (!records.ContainsKey(release.InstallerName)
            || cabinetNumbers.Count is < 1 or > 32
            || Enumerable.Range(1, cabinetNumbers.Count).Any(n => !cabinetNumbers.Contains(n))
            || records.Count != cabinetNumbers.Count + 1
            || release.Sizes.Keys.Count(k =>
                k.Equals(release.InstallerName, StringComparison.OrdinalIgnoreCase)
                || CabinetName.IsMatch(k)) != records.Count)
            throw new InvalidDataException("The release is missing an MSI or a required CAB file.");

        return new[] { records[release.InstallerName] }
            .Concat(records.Values.Where(a => CabinetName.IsMatch(a.Name))
                .OrderBy(a => int.Parse(CabinetName.Match(a.Name).Groups["number"].Value)))
            .ToArray();
    }

    private static async Task EnsureDownloadedAsync(
        HttpClient client, Asset asset, string releaseTag, string directory, CancellationToken cancellation)
    {
        var destination = Path.Combine(directory, asset.Name);
        if (File.Exists(destination) && await IsVerifiedAsync(destination, asset, cancellation))
        {
            Console.WriteLine($"Already verified: {asset.Name}");
            return;
        }

        var temp = destination + ".part";
        if (File.Exists(temp))
            File.Delete(temp);

        Console.WriteLine($"Downloading: {asset.Name} ({asset.Size / 1048576.0:F1} MiB)");
        try
        {
            using var response = await client.GetAsync(
                AssetUrl(releaseTag, asset.Name),
                HttpCompletionOption.ResponseHeadersRead,
                cancellation);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long length && length != asset.Size)
                throw new InvalidDataException("Unexpected download size for " + asset.Name);

            await using var incoming = await response.Content.ReadAsStreamAsync(cancellation);
            await using var outgoing = new FileStream(
                temp, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1048576, useAsync: true);
            using var checksum = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);

            var buffer = new byte[1048576];
            long total = 0;
            int percentShown = -1;
            while (true)
            {
                int read = await incoming.ReadAsync(buffer, cancellation);
                if (read == 0)
                    break;

                await outgoing.WriteAsync(buffer.AsMemory(0, read), cancellation);
                checksum.AppendData(buffer, 0, read);
                total += read;
                int percent = (int)Math.Min(100, total * 100 / asset.Size);
                if (percent / 10 > percentShown / 10)
                {
                    percentShown = percent;
                    Console.Write($"\r  {percent}% complete   ");
                }
                if (total > asset.Size)
                    throw new InvalidDataException("Download exceeded expected file size: " + asset.Name);
            }
            Console.WriteLine();

            var actualHash = Convert.ToHexString(checksum.GetHashAndReset());
            if (total != asset.Size
                || !actualHash.Equals(asset.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Size or SHA-256 check failed for " + asset.Name);

            await outgoing.FlushAsync(cancellation);
            outgoing.Close();
            File.Move(temp, destination, overwrite: true);
            Console.WriteLine($"Verified: {asset.Name}");
        }
        finally
        {
            if (File.Exists(temp))
                File.Delete(temp);
        }
    }

    private static async Task<bool> IsVerifiedAsync(
        string path, Asset asset, CancellationToken cancellation)
    {
        if (new FileInfo(path).Length != asset.Size)
            return false;

        await using var file = File.OpenRead(path);
        var hash = await SHA256.HashDataAsync(file, cancellation);
        return Convert.ToHexString(hash).Equals(
            asset.Sha256, StringComparison.OrdinalIgnoreCase);
    }
}
